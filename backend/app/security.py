"""Authentication, authorization helpers, masking, rate limiting and the API error type."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import IntegrationClient, User

ROLES = ("AICTE_ADMIN", "AICTE_ANALYST", "INST_ADMIN", "INST_STAFF", "VERIFIER", "AUDITOR", "STUDENT")
AICTE_ROLES = ("AICTE_ADMIN", "AICTE_ANALYST")
INST_ROLES = ("INST_ADMIN", "INST_STAFF")
PBKDF2_ITERATIONS = 210_000


class ApiError(Exception):
    """Raised for every handled error; rendered as {"error": {...}} by the global handler."""

    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


# ---------------------------------------------------------------- passwords


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(iterations))
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


# ---------------------------------------------------------------- tokens


def issue_token(user_id: str, purpose: str = "api", minutes: int | None = None) -> str:
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=minutes if minutes is not None else settings.token_minutes)
    payload = {"sub": user_id, "iat": now, "exp": exp, "jti": uuid.uuid4().hex, "pur": purpose}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str, purpose: str = "api") -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise ApiError(401, "Your session has expired or the token is invalid. Sign in again.") from exc
    if payload.get("pur") != purpose:
        raise ApiError(401, "This token cannot be used here.")
    return payload["sub"]


# ---------------------------------------------------------------- actor


@dataclass
class Actor:
    id: str | None
    role: str
    institution_id: str | None = None
    kind: str = "USER"  # USER | CLIENT | ANONYMOUS
    user: User | None = None
    client: IntegrationClient | None = None
    scopes: list[str] = field(default_factory=list)

    @property
    def student_id(self) -> str | None:
        return self.user.student_id if self.user else None

    @property
    def is_aicte(self) -> bool:
        return self.role in AICTE_ROLES

    @property
    def is_institution(self) -> bool:
        return self.role in INST_ROLES or self.kind == "CLIENT"


ANONYMOUS = Actor(id=None, role="ANONYMOUS", kind="ANONYMOUS")


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def _load_user(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None or not user.active:
        raise ApiError(401, "Your account is not active. Contact your administrator.")
    return user


def actor_from_user(user: User) -> Actor:
    return Actor(id=user.id, role=user.role, institution_id=user.institution_id, user=user)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_api_key() -> tuple[str, str]:
    """Returns (full_key, prefix). Only the hash of full_key is stored."""
    prefix = "apk_" + secrets.token_hex(4)
    return f"{prefix}.{secrets.token_urlsafe(32)}", prefix


def _client_actor(db: Session, key: str) -> Actor:
    prefix = key.split(".", 1)[0]
    client = db.execute(select(IntegrationClient).where(IntegrationClient.key_prefix == prefix)).scalar_one_or_none()
    if client is None or not client.active or not hmac.compare_digest(client.key_hash, hash_api_key(key)):
        raise ApiError(401, "The API key is not valid.")
    return Actor(
        id=client.id,
        role="INTEGRATION_CLIENT",
        institution_id=client.institution_id,
        kind="CLIENT",
        client=client,
        scopes=list(client.scopes),
    )


def current_actor(request: Request, db: Session = Depends(get_db)) -> Actor:
    token = _bearer(request)
    if not token:
        raise ApiError(401, "Sign in to continue.")
    actor = actor_from_user(_load_user(db, decode_token(token)))
    request.state.actor = actor
    return actor


def optional_actor(request: Request, db: Session = Depends(get_db)) -> Actor:
    token = _bearer(request)
    if not token:
        request.state.actor = ANONYMOUS
        return ANONYMOUS
    return current_actor(request, db)


def user_or_client(request: Request, db: Session = Depends(get_db)) -> Actor:
    key = request.headers.get("x-api-key")
    if key:
        actor = _client_actor(db, key)
        request.state.actor = actor
        return actor
    return current_actor(request, db)


def api_client(request: Request, db: Session = Depends(get_db)) -> Actor:
    key = request.headers.get("x-api-key")
    if not key:
        raise ApiError(401, "Send your institution API key in the X-API-Key header.")
    actor = _client_actor(db, key)
    request.state.actor = actor
    return actor


def require_roles(*roles: str):
    def dep(actor: Actor = Depends(current_actor)) -> Actor:
        if actor.role not in roles:
            raise ApiError(403, "Your role does not allow this action.")
        return actor

    return dep


def require_scope(actor: Actor, scope: str) -> None:
    if actor.kind == "CLIENT" and scope not in actor.scopes:
        raise ApiError(403, f"This API key does not have the '{scope}' scope.")


def ensure_institution(actor: Actor, institution_id: str | None) -> None:
    """Institution users may only touch their own institution's objects. Others' objects look absent (404)."""
    if actor.is_institution and actor.institution_id != institution_id:
        raise ApiError(404, "Not found.")


# ---------------------------------------------------------------- APAAR handling


def apaar_ref(apaar_id: str | None) -> str | None:
    if not apaar_id:
        return None
    return hmac.new(settings.apaar_hmac_key.encode(), apaar_id.encode(), hashlib.sha256).hexdigest()[:16]


def mask_apaar(apaar_id: str | None) -> str | None:
    if not apaar_id:
        return None
    return f"XXXX-XXXX-{apaar_id[-4:]}"


def can_see_full_apaar(actor: Actor, owning_institution_ids: set[str]) -> bool:
    if actor.role == "AICTE_ADMIN":
        return True
    if actor.is_institution and actor.institution_id in owning_institution_ids:
        return True
    return False


# ---------------------------------------------------------------- rate limiting


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and os.environ.get("VERCEL"):
        return forwarded.split(",")[0].strip()  # set by the Vercel edge, not by the client
    return request.client.host if request.client else "unknown"
