"""Hash-chained, append-only audit log.

hash = sha256(prev_hash + canonical_json(event)); genesis prev_hash is "0"*64.

Events are buffered on the business session and appended after it commits, in a short
separate transaction under a process-wide lock, so the chain stays linear and audit writes
never wait on the business transaction's database lock. DENIED/FAILED events are durable:
they are written even when the business transaction rolls back. (Production on PostgreSQL:
append in the same transaction under pg_advisory_xact_lock; see PRODUCTION_GAP_ANALYSIS.md.)
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal, after_commit, utcnow
from .models import AuditEvent

GENESIS = "0" * 64
_chain_lock = threading.Lock()
_APAAR_LIKE = re.compile(r"(?<!\d)\d{12}(?!\d)")
_SENSITIVE_KEYS = {"apaar_id", "apaarId", "password", "token", "api_key"}


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def scrub(value):
    """Never let a raw APAAR ID (or a secret) reach the audit log."""
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if k in _SENSITIVE_KEYS else scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        return _APAAR_LIKE.sub("[APAAR-REDACTED]", value)
    return value


def _event_body(ev: dict) -> dict:
    return {
        "at": ev["at"].isoformat(timespec="microseconds"),
        "actor_id": ev["actor_id"],
        "actor_role": ev["actor_role"],
        "institution_id": ev["institution_id"],
        "action": ev["action"],
        "entity_type": ev["entity_type"],
        "entity_id": ev["entity_id"],
        "outcome": ev["outcome"],
        "detail": ev["detail"],
    }


def compute_hash(prev_hash: str, body: dict) -> str:
    return hashlib.sha256((prev_hash + canonical_json(body)).encode()).hexdigest()


def _append(events: list[dict]) -> None:
    if not events:
        return
    with _chain_lock:
        s = SessionLocal()
        try:
            last = s.execute(select(AuditEvent.hash).order_by(AuditEvent.seq.desc()).limit(1)).scalar()
            prev = last or GENESIS
            for ev in events:
                h = compute_hash(prev, _event_body(ev))
                s.add(AuditEvent(**ev, prev_hash=prev, hash=h))
                prev = h
            s.commit()
        finally:
            s.close()


def _make(actor, action, entity_type, entity_id, outcome, detail, institution_id) -> dict:
    return {
        "at": utcnow(),
        "actor_id": getattr(actor, "id", None),
        "actor_role": getattr(actor, "role", None),
        "institution_id": institution_id if institution_id is not None else getattr(actor, "institution_id", None),
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "outcome": outcome,
        "detail": scrub(detail or {}),
    }


def record(
    db: Session,
    actor,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    outcome: str = "SUCCESS",
    detail: dict | None = None,
    institution_id: str | None = None,
) -> None:
    """Queue an audit event; it is appended when db commits (durable outcomes also on rollback)."""
    ev = _make(actor, action, entity_type, entity_id, outcome, detail, institution_id)
    buf = db.info.get("audit_buffer")
    if buf is None:
        buf = db.info["audit_buffer"] = []

        def flush(committed_only=False):
            items = db.info.pop("audit_buffer", [])
            _append(items)

        def flush_durable():
            items = db.info.pop("audit_buffer", [])
            _append([e for e in items if e["outcome"] != "SUCCESS"])

        after_commit(db, flush)
        after_commit(db, flush_durable, durable=True)
    buf.append(ev)


def record_now(
    actor,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    outcome: str = "SUCCESS",
    detail: dict | None = None,
    institution_id: str | None = None,
) -> None:
    """Append immediately in its own transaction (used by error handlers and logins)."""
    _append([_make(actor, action, entity_type, entity_id, outcome, detail, institution_id)])


def verify_chain(db: Session) -> dict:
    prev = GENESIS
    count = 0
    for ev in db.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars():
        body = _event_body(
            {
                "at": ev.at,
                "actor_id": ev.actor_id,
                "actor_role": ev.actor_role,
                "institution_id": ev.institution_id,
                "action": ev.action,
                "entity_type": ev.entity_type,
                "entity_id": ev.entity_id,
                "outcome": ev.outcome,
                "detail": ev.detail,
            }
        )
        if ev.prev_hash != prev or compute_hash(prev, body) != ev.hash:
            return {"valid": False, "events_checked": count, "first_broken_seq": ev.seq}
        prev = ev.hash
        count += 1
    return {"valid": True, "events_checked": count, "first_broken_seq": None, "head_hash": prev}


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None
