from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..db import get_db, utcnow
from ..models import Institution, User
from ..security import (
    Actor,
    ApiError,
    actor_from_user,
    client_ip,
    current_actor,
    issue_token,
    limiter,
    verify_password,
)

router = APIRouter(prefix="/api/v1", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


def user_payload(db: Session, user: User) -> dict:
    inst = db.get(Institution, user.institution_id) if user.institution_id else None
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "institution_id": user.institution_id,
        "institution_name": inst.name if inst else None,
        "institution_code": inst.aicte_code if inst else None,
        "student_id": user.student_id,
        "organisation": user.organisation,
    }


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    if not limiter.hit(f"login:{ip}", settings.login_rate_per_minute, 60):
        raise ApiError(429, "Too many sign-in attempts. Wait a minute and try again.")
    email = body.email.strip().lower()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    now = utcnow()
    anon = Actor(id=None, role="ANONYMOUS", kind="ANONYMOUS")
    if user is not None and user.locked_until and user.locked_until > now:
        audit.record_now(actor_from_user(user), "auth.login", "user", user.id, "DENIED", {"reason": "locked"})
        raise ApiError(423, "This account is locked after repeated failed sign-ins. Try again in 15 minutes.")
    if user is None or not user.active or not verify_password(body.password, user.password_hash):
        if user is not None:
            user.failed_logins += 1
            if user.failed_logins >= settings.lockout_threshold:
                user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
                user.failed_logins = 0
            db.commit()
        audit.record_now(actor_from_user(user) if user else anon, "auth.login", "user", user.id if user else None,
                         "DENIED", {"reason": "bad_credentials", "ip": ip})
        raise ApiError(401, "Email or password is not correct.")
    user.failed_logins = 0
    user.locked_until = None
    actor = actor_from_user(user)
    audit.record(db, actor, "auth.login", "user", user.id, detail={"ip": ip})
    db.commit()
    return {"access_token": issue_token(user.id), "token_type": "bearer",
            "expires_in": settings.token_minutes * 60, "user": user_payload(db, user)}


@router.get("/auth/me")
def me(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    return user_payload(db, actor.user)


@router.post("/auth/stream-token")
def stream_token(actor: Actor = Depends(current_actor)):
    """Short-lived token for the live event stream (EventSource cannot send headers)."""
    return {"token": issue_token(actor.id, purpose="sse", minutes=2)}


@router.get("/auth/demo-accounts")
def demo_accounts(db: Session = Depends(get_db)):
    """Synthetic demo accounts for the login picker (all use password Demo@2026)."""
    users = db.execute(select(User).where(User.email.like("%@demo.local")).order_by(User.role, User.email)).scalars()
    return [{"email": u.email, "full_name": u.full_name, "role": u.role} for u in users]
