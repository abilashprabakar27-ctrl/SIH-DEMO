"""Versioned capacity rule-set management for AICTE administrators."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import (
    AcademicYear,
    ApprovedIntake,
    CapacityRuleEntry,
    CapacityRuleSet,
    Programme,
    RecordRevision,
)
from ..security import AICTE_ROLES, Actor, ApiError, current_actor, require_roles
from . import issues, ledger
from .capacity_rules import caps_from_rule_set
from .normalize import SUPERNUMERARY, valid_academic_year

router = APIRouter(prefix="/api/v1/rule-sets", tags=["capacity rules"])


class EntryIn(BaseModel):
    seat_category: str
    level: str = "*"
    discipline: str = "*"
    percent_bp: int = Field(ge=0, le=10000)
    numerator: int = Field(default=1, ge=1)
    denominator: int = Field(default=1, ge=1)
    rounding: str = "FLOOR"


class RuleSetIn(BaseModel):
    code: str = Field(min_length=2, max_length=60)
    version: int = Field(ge=1)
    source_type: str = Field(min_length=3, max_length=30)
    source_ref: str = Field(min_length=4, max_length=300)
    source_url: str | None = None
    source_accessed_on: date | None = None
    academic_year_from: str
    academic_year_to: str
    effective_from: date
    effective_to: date | None = None
    entries: list[EntryIn] = Field(min_length=1)


class ActivateIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


def _view(rs: CapacityRuleSet) -> dict:
    return {
        "id": rs.id, "code": rs.code, "version": rs.version, "source_type": rs.source_type,
        "source_ref": rs.source_ref, "source_url": rs.source_url,
        "source_accessed_on": rs.source_accessed_on.isoformat() if rs.source_accessed_on else None,
        "verification_status": rs.verification_status, "academic_year_from": rs.academic_year_from,
        "academic_year_to": rs.academic_year_to, "effective_from": rs.effective_from.isoformat(),
        "effective_to": rs.effective_to.isoformat() if rs.effective_to else None,
        "status": rs.status, "reason": rs.reason,
        "entries": [{"id": e.id, "seat_category": e.seat_category, "level": e.level,
                     "discipline": e.discipline, "percent_bp": e.percent_bp, "numerator": e.numerator,
                     "denominator": e.denominator, "rounding": e.rounding} for e in rs.entries],
    }


@router.get("")
def list_rule_sets(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    if actor.role not in (*AICTE_ROLES, "AUDITOR"):
        raise ApiError(403, "Your role does not allow this action.")
    return [_view(rs) for rs in db.execute(select(CapacityRuleSet).order_by(
        CapacityRuleSet.code, CapacityRuleSet.version.desc())).scalars()]


@router.get("/{rule_set_id}")
def get_rule_set(rule_set_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    if actor.role not in (*AICTE_ROLES, "AUDITOR"):
        raise ApiError(403, "Your role does not allow this action.")
    rs = db.get(CapacityRuleSet, rule_set_id)
    if rs is None:
        raise ApiError(404, "Not found.")
    return _view(rs)


@router.post("")
def create_rule_set(body: RuleSetIn, actor: Actor = Depends(require_roles("AICTE_ADMIN")),
                    db: Session = Depends(get_db)):
    if not valid_academic_year(body.academic_year_from) or not valid_academic_year(body.academic_year_to):
        raise ApiError(422, "Academic year range must use YYYY-YY values.")
    if body.academic_year_from > body.academic_year_to:
        raise ApiError(422, "Academic year range is reversed.")
    if any(e.seat_category not in SUPERNUMERARY or e.rounding not in ("FLOOR", "CEIL", "NEAREST")
           for e in body.entries):
        raise ApiError(422, "Rule entries contain an unsupported category or rounding method.")
    existing = db.execute(select(CapacityRuleSet.id).where(
        CapacityRuleSet.code == body.code, CapacityRuleSet.version == body.version)).first()
    if existing:
        raise ApiError(409, "That rule-set code and version already exist.")
    rs = CapacityRuleSet(**body.model_dump(exclude={"entries"}), status="DRAFT", verification_status="UNVERIFIED")
    db.add(rs)
    db.flush()
    for entry in body.entries:
        db.add(CapacityRuleEntry(rule_set_id=rs.id, **entry.model_dump()))
    audit.record(db, actor, "capacity_rules.draft_created", "rule_set", rs.id,
                 detail={"code": rs.code, "version": rs.version})
    db.commit()
    return _view(rs)


@router.post("/{rule_set_id}/impact")
def rule_set_impact(rule_set_id: str, actor: Actor = Depends(require_roles("AICTE_ADMIN")),
                    db: Session = Depends(get_db)):
    rs = db.get(CapacityRuleSet, rule_set_id)
    if rs is None:
        raise ApiError(404, "Not found.")
    rows = db.execute(select(ApprovedIntake, Programme).join(
        Programme, Programme.id == ApprovedIntake.programme_id).where(
            ApprovedIntake.academic_year.between(rs.academic_year_from, rs.academic_year_to))).all()
    impacts = []
    for intake, programme in rows:
        target = caps_from_rule_set(db, rs, intake.approved_intake, programme.discipline, programme.level)
        current = ledger.caps_for(db, intake)
        before_counts = ledger.counts_for(db, programme.id, intake.academic_year)
        before = ledger.position_from_counts(intake.approved_intake, current, before_counts)
        after_caps = {category: spec["cap_seats"] for category, spec in target.items()}
        after = ledger.position_from_counts(intake.approved_intake, after_caps, before_counts)
        changed = {category: {"current": current.get(category, 0), "proposed": cap}
                   for category, cap in after_caps.items() if current.get(category, 0) != cap}
        if changed:
            impacts.append({"programme_id": programme.id, "programme_code": programme.code,
                            "academic_year": intake.academic_year, "changes": changed,
                            "flags_open": after["any_excess"] and not before["any_excess"],
                            "flags_close": before["any_excess"] and not after["any_excess"],
                            "locked": bool(db.get(AcademicYear, intake.academic_year)
                                           and db.get(AcademicYear, intake.academic_year).is_locked)})
    return {"rule_set": {"code": rs.code, "version": rs.version,
                         "verification_status": rs.verification_status}, "programmes": impacts}


@router.post("/{rule_set_id}/activate")
def activate_rule_set(rule_set_id: str, body: ActivateIn, actor: Actor = Depends(require_roles("AICTE_ADMIN")),
                      db: Session = Depends(get_db)):
    rs = db.get(CapacityRuleSet, rule_set_id)
    if rs is None:
        raise ApiError(404, "Not found.")
    if rs.status == "ACTIVE":
        raise ApiError(409, "This rule set is already active.")
    if rs.status not in ("DRAFT", "SUPERSEDED"):
        raise ApiError(409, "Only a draft or superseded rule set can be activated.")
    if not rs.entries:
        raise ApiError(422, "A rule set needs entries before activation.")
    overlapping = db.execute(select(CapacityRuleSet).where(
        CapacityRuleSet.status == "ACTIVE",
        CapacityRuleSet.academic_year_from <= rs.academic_year_to,
        CapacityRuleSet.academic_year_to >= rs.academic_year_from,
    )).scalars().all()
    for old in overlapping:
        old.status = "SUPERSEDED"
    rs.status = "ACTIVE"
    rs.reason = body.reason
    db.flush()
    rows = db.execute(select(ApprovedIntake, Programme).join(
        Programme, Programme.id == ApprovedIntake.programme_id).where(
            ApprovedIntake.academic_year.between(rs.academic_year_from, rs.academic_year_to))).all()
    changed_count = 0
    for intake, programme in rows:
        academic_year = db.get(AcademicYear, intake.academic_year)
        if academic_year and academic_year.is_locked:
            continue
        old_values = {q.seat_category: {"cap_seats": q.cap_seats, "rule_set_id": q.rule_set_id}
                      for q in intake.quotas if q.source != "OVERRIDE"}
        ledger.apply_default_caps(db, intake, programme)
        for quota in intake.quotas:
            old = old_values.get(quota.seat_category)
            if old is None:
                continue
            new = {"cap_seats": quota.cap_seats, "rule_set_id": quota.rule_set_id}
            if old != new:
                quota.version += 1
                db.add(RecordRevision(entity_type="supernumerary_quota", entity_id=quota.id,
                                      version=quota.version, changes={"rule_set": {"old": old, "new": new}},
                                      reason=body.reason, actor_id=actor.id))
                changed_count += 1
        issues.run_capacity_checks(db, programme.id, intake.academic_year, actor)
    audit.record(db, actor, "capacity_rules.activated", "rule_set", rs.id,
                 detail={"code": rs.code, "version": rs.version, "reason": body.reason,
                         "quotas_changed": changed_count})
    db.commit()
    return {"rule_set": _view(rs), "quotas_changed": changed_count}
