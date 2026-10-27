"""Registry (institutions, programmes, intakes, caps), seat-check, live events, rules, notifications."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..db import SessionLocal, get_db, utcnow
from ..models import (
    ApprovedIntake,
    Institution,
    Notification,
    Programme,
    SeatCheckLog,
    SupernumeraryQuota,
    User,
    ValidationRule,
)
from ..security import (
    AICTE_ROLES,
    INST_ROLES,
    Actor,
    ApiError,
    actor_from_user,
    current_actor,
    decode_token,
    require_roles,
    require_scope,
    user_or_client,
)
from . import events, issues, ledger
from .normalize import SEAT_CATEGORIES, SUPERNUMERARY, valid_academic_year

router = APIRouter(prefix="/api/v1", tags=["registry"])


def _inst_view(i: Institution) -> dict:
    return {"id": i.id, "aicte_code": i.aicte_code, "name": i.name, "short_name": i.short_name, "state": i.state,
            "region": i.region, "institution_type": i.institution_type}


@router.get("/institutions")
def list_institutions(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    q = select(Institution).order_by(Institution.aicte_code)
    if actor.is_institution:
        q = q.where(Institution.id == actor.institution_id)
    elif actor.role not in (*AICTE_ROLES, "AUDITOR"):
        raise ApiError(403, "Your role does not allow this action.")
    return [_inst_view(i) for i in db.execute(q).scalars()]


@router.get("/programmes")
def list_programmes(
    academic_year: str = settings.current_year,
    institution_id: str | None = None,
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    if actor.is_institution:
        if institution_id and institution_id != actor.institution_id:
            raise ApiError(403, "You can only list your own institution's programmes.")
        institution_id = actor.institution_id
    elif actor.role not in AICTE_ROLES:
        raise ApiError(403, "Your role does not allow this action.")
    progs = db.execute(
        select(Programme).where(Programme.institution_id == institution_id) if institution_id else select(Programme)
    ).scalars().all()
    positions = {p["programme_id"]: p for p in ledger.all_positions(db, academic_year, [institution_id] if institution_id else None)}
    out = []
    for p in sorted(progs, key=lambda p: (p.institution.aicte_code, p.code)):
        intake = ledger.get_intake(db, p.id, academic_year)
        quotas = []
        if intake:
            quotas = [{"seat_category": q.seat_category, "cap_seats": q.cap_seats, "percent_basis": q.percent_basis,
                       "rule_source": q.rule_source} for q in sorted(intake.quotas, key=lambda q: q.seat_category)]
        out.append({
            "id": p.id, "code": p.code, "name": p.name, "level": p.level, "discipline": p.discipline,
            "institution_id": p.institution_id, "institution_name": p.institution.name,
            "intake": None if intake is None else {
                "id": intake.id, "academic_year": academic_year, "approved_intake": intake.approved_intake,
                "approval_reference": intake.approval_reference,
                "submitted_at": intake.submitted_at.isoformat() if intake.submitted_at else None,
                "quotas": quotas},
            "position": positions.get(p.id),
        })
    return out


class IntakeIn(BaseModel):
    programme_id: str
    academic_year: str
    approved_intake: int = Field(ge=0, le=5000)
    approval_reference: str = Field(min_length=3, max_length=100)


@router.post("/intakes")
def set_intake(body: IntakeIn, actor: Actor = Depends(require_roles("AICTE_ADMIN")), db: Session = Depends(get_db)):
    if not valid_academic_year(body.academic_year):
        raise ApiError(422, "Academic year must look like 2026-27.", field="academic_year")
    prog = db.get(Programme, body.programme_id)
    if prog is None:
        raise ApiError(404, "Programme not found.")
    intake = ledger.get_intake(db, prog.id, body.academic_year)
    old = intake.approved_intake if intake else None
    if intake is None:
        intake = ApprovedIntake(programme_id=prog.id, academic_year=body.academic_year,
                                approved_intake=body.approved_intake, approval_reference=body.approval_reference)
        db.add(intake)
        db.flush()
    else:
        intake.approved_intake = body.approved_intake
        intake.approval_reference = body.approval_reference
    ledger.apply_default_caps(db, intake, prog)
    pos = issues.run_capacity_checks(db, prog.id, body.academic_year, actor)
    audit.record(db, actor, "intake.set", "approved_intake", intake.id,
                 detail={"programme": prog.code, "year": body.academic_year, "old": old, "new": body.approved_intake},
                 institution_id=prog.institution_id)
    db.commit()
    return {"id": intake.id, "approved_intake": intake.approved_intake, "position": pos}


class QuotaIn(BaseModel):
    cap_seats: int = Field(ge=0, le=5000)
    rule_source: str = Field(min_length=5, max_length=300)


@router.patch("/intakes/{intake_id}/quotas/{category}")
def set_quota(intake_id: str, category: str, body: QuotaIn,
              actor: Actor = Depends(require_roles("AICTE_ADMIN")), db: Session = Depends(get_db)):
    if category not in SUPERNUMERARY:
        raise ApiError(422, f"Category must be one of {', '.join(SUPERNUMERARY)}.")
    intake = db.get(ApprovedIntake, intake_id)
    if intake is None:
        raise ApiError(404, "Not found.")
    q = db.execute(select(SupernumeraryQuota).where(SupernumeraryQuota.intake_id == intake_id,
                                                    SupernumeraryQuota.seat_category == category)).scalar_one_or_none()
    if q is None:
        q = SupernumeraryQuota(intake_id=intake_id, seat_category=category, cap_seats=0, rule_source="")
        db.add(q)
    old = q.cap_seats
    q.cap_seats = body.cap_seats
    q.percent_basis = None
    q.rule_source = "CONFIGURED: " + body.rule_source
    db.flush()
    pos = issues.run_capacity_checks(db, intake.programme_id, intake.academic_year, actor)
    audit.record(db, actor, "quota.set", "supernumerary_quota", q.id,
                 detail={"category": category, "old": old, "new": body.cap_seats})
    db.commit()
    return {"position": pos}


@router.post("/intakes/{intake_id}/submit")
def declare_submission(intake_id: str, actor: Actor = Depends(require_roles("INST_ADMIN")), db: Session = Depends(get_db)):
    intake = db.get(ApprovedIntake, intake_id)
    if intake is None or intake.programme.institution_id != actor.institution_id:
        raise ApiError(404, "Not found.")
    if intake.submitted_at is None:
        intake.submitted_at = utcnow()
        intake.submitted_by = actor.id
        audit.record(db, actor, "intake.submit", "approved_intake", intake.id,
                     detail={"programme": intake.programme.code, "year": intake.academic_year})
        db.commit()
    return {"id": intake.id, "submitted_at": intake.submitted_at.isoformat()}


class SeatCheckIn(BaseModel):
    programme_code: str
    academic_year: str = settings.current_year
    seat_category: str
    count: int = Field(default=1, ge=1, le=1000)


@router.post("/seat-check")
def seat_check(body: SeatCheckIn, actor: Actor = Depends(user_or_client), db: Session = Depends(get_db)):
    if not actor.is_institution:
        raise ApiError(403, "Seat check is for institution users and institution systems.")
    require_scope(actor, "seat:check")
    if body.seat_category not in SEAT_CATEGORIES:
        raise ApiError(422, "Seat category must be one of " + ", ".join(SEAT_CATEGORIES) + ".", field="seat_category")
    prog = db.execute(select(Programme).where(Programme.institution_id == actor.institution_id,
                                              Programme.code == body.programme_code.upper())).scalar_one_or_none()
    if prog is None:
        raise ApiError(404, f"Programme {body.programme_code} is not one of your programmes.")
    pos = ledger.position(db, prog.id, body.academic_year)
    if not pos["has_intake"]:
        raise ApiError(422, f"{prog.code} has no approved intake for {body.academic_year}.")
    result = ledger.seat_check(pos, body.seat_category, body.count)
    result.update(programme_code=prog.code, academic_year=body.academic_year, seat_category=body.seat_category,
                  count=body.count)
    db.add(SeatCheckLog(programme_id=prog.id, academic_year=body.academic_year, seat_category=body.seat_category,
                        count=body.count, result=result, actor_id=actor.id))
    audit.record(db, actor, "seat.check", "programme", prog.id,
                 detail={"category": body.seat_category, "count": body.count,
                         "allowed": result["allowed_within_rules"]})
    db.commit()
    return result


@router.get("/events")
async def event_stream(request: Request, token: str):
    """Server-Sent Events. Authenticate with a token from POST /auth/stream-token."""
    user_id = decode_token(token, purpose="sse")
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None or not user.active:
            raise ApiError(401, "Sign in again.")
        actor = actor_from_user(user)
    finally:
        db.close()
    if actor.role not in (*AICTE_ROLES, *INST_ROLES):
        raise ApiError(403, "Live updates are for AICTE and institution users.")
    sub = events.subscribe(actor.role, actor.institution_id)

    async def gen():
        try:
            yield "event: ready\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    kind, payload = await asyncio.wait_for(sub.queue.get(), timeout=15)
                    yield f"event: {kind}\ndata: {payload}\n\n"
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            events.unsubscribe(sub)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- rules


def _rule_view(r: ValidationRule) -> dict:
    return {"rule_id": r.rule_id, "title": r.title, "description": r.description, "severity": r.severity,
            "stage": r.stage, "enabled": r.enabled, "remediation": r.remediation, "locked": r.locked}


@router.get("/rules")
def list_rules(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    if actor.role in ("VERIFIER", "STUDENT"):
        raise ApiError(403, "Your role does not allow this action.")
    return [_rule_view(r) for r in db.execute(select(ValidationRule).order_by(ValidationRule.rule_id)).scalars()]


class RulePatch(BaseModel):
    enabled: bool | None = None
    severity: str | None = None


@router.patch("/rules/{rule_id}")
def patch_rule(rule_id: str, body: RulePatch, actor: Actor = Depends(require_roles("AICTE_ADMIN")),
               db: Session = Depends(get_db)):
    rule = db.get(ValidationRule, rule_id)
    if rule is None:
        raise ApiError(404, "Rule not found.")
    if rule.locked:
        raise ApiError(409, f"{rule_id} is locked: it protects data integrity and cannot be changed.")
    if body.severity is not None and body.severity not in ("ERROR", "WARNING", "REVIEW"):
        raise ApiError(422, "Severity must be ERROR, WARNING or REVIEW.")
    before = {"enabled": rule.enabled, "severity": rule.severity}
    if body.enabled is not None:
        rule.enabled = body.enabled
    if body.severity is not None:
        rule.severity = body.severity
    audit.record(db, actor, "rule.change", "validation_rule", rule_id,
                 detail={"before": before, "after": {"enabled": rule.enabled, "severity": rule.severity}})
    db.commit()
    return _rule_view(rule)


# ---------------------------------------------------------------- notifications


@router.get("/notifications")
def notifications(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    conds = [Notification.user_id == actor.id]
    if actor.institution_id:
        conds.append(Notification.institution_id == actor.institution_id)
    if actor.role == "AICTE_ADMIN":
        conds.append(Notification.audience_role == "AICTE_ADMIN")
    rows = db.execute(select(Notification).where(or_(*conds)).order_by(Notification.created_at.desc()).limit(30)).scalars()
    return [{"id": n.id, "kind": n.kind, "message": n.message, "link": n.link, "read": n.read,
             "created_at": n.created_at.isoformat()} for n in rows]
