"""Audit trail: filtered listing, chain verification, CSV export (AUDITOR and AICTE_ADMIN)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..csvout import csv_response
from ..db import get_db
from ..models import AuditEvent
from ..security import Actor, require_roles

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])
auditor = require_roles("AUDITOR", "AICTE_ADMIN")


def _filtered(action: str | None, outcome: str | None, actor_role: str | None, entity_type: str | None):
    q = select(AuditEvent)
    if action:
        q = q.where(AuditEvent.action.like(f"{action}%"))
    if outcome:
        q = q.where(AuditEvent.outcome == outcome)
    if actor_role:
        q = q.where(AuditEvent.actor_role == actor_role)
    if entity_type:
        q = q.where(AuditEvent.entity_type == entity_type)
    return q


def _view(e: AuditEvent) -> dict:
    return {"seq": e.seq, "at": e.at.isoformat(), "actor_id": e.actor_id, "actor_role": e.actor_role,
            "institution_id": e.institution_id, "action": e.action, "entity_type": e.entity_type,
            "entity_id": e.entity_id, "outcome": e.outcome, "detail": e.detail, "prev_hash": e.prev_hash, "hash": e.hash}


@router.get("")
def list_events(action: str | None = None, outcome: str | None = None, actor_role: str | None = None,
                entity_type: str | None = None, page: int = 1, page_size: int = 50,
                actor: Actor = Depends(auditor), db: Session = Depends(get_db)):
    q = _filtered(action, outcome, actor_role, entity_type)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar()
    page_size = max(1, min(page_size, 200))
    rows = db.execute(q.order_by(AuditEvent.seq.desc()).offset((max(page, 1) - 1) * page_size).limit(page_size)).scalars()
    return {"items": [_view(e) for e in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/verify-chain")
def verify_chain(actor: Actor = Depends(auditor), db: Session = Depends(get_db)):
    result = audit.verify_chain(db)
    audit.record(db, actor, "audit.verify_chain", None, None, detail={"valid": result["valid"],
                                                                      "first_broken_seq": result["first_broken_seq"]})
    db.commit()
    return result


@router.get("/export.csv")
def export(action: str | None = None, outcome: str | None = None, actor: Actor = Depends(auditor),
           db: Session = Depends(get_db)):
    rows = db.execute(_filtered(action, outcome, None, None).order_by(AuditEvent.seq)).scalars().all()
    audit.record(db, actor, "report.export", "audit", None, detail={"rows": len(rows)})
    db.commit()
    return csv_response("audit.csv", ["seq", "at", "actor_role", "actor_id", "institution_id", "action", "entity_type",
                                      "entity_id", "outcome", "detail", "prev_hash", "hash"],
                        [[e.seq, e.at.isoformat(), e.actor_role, e.actor_id, e.institution_id, e.action, e.entity_type,
                          e.entity_id, e.outcome, audit.canonical_json(e.detail), e.prev_hash, e.hash] for e in rows])
