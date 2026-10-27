"""Student records: search, manual entry, detail, corrections, status changes, identity candidates."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from .. import audit
from ..config import settings
from ..db import get_db
from ..models import (
    CorrectionRequest,
    Credential,
    Enrolment,
    IdentityCandidate,
    Institution,
    IssueEvent,
    Programme,
    RecordRevision,
    Student,
    ValidationIssue,
)
from ..security import AICTE_ROLES, INST_ROLES, Actor, ApiError, current_actor, ensure_institution, require_roles
from . import engine, identity, issues, ledger
from .views import enrolment_view, row_from_enrolment, student_view

router = APIRouter(prefix="/api/v1", tags=["records"])
RECORD_ROLES = (*AICTE_ROLES, *INST_ROLES)
SORTS = {
    "name": Student.full_name,
    "roll": Enrolment.institution_student_id,
    "admission_date": Enrolment.admission_date,
    "programme": Programme.code,
    "status": Enrolment.status,
    "updated": Enrolment.updated_at,
}


def _records_actor(actor: Actor = Depends(current_actor)) -> Actor:
    if actor.role not in RECORD_ROLES:
        raise ApiError(403, "Your role cannot view student records.")
    return actor


def load_enrolment(db: Session, enrolment_id: str, actor: Actor) -> Enrolment:
    en = db.execute(
        select(Enrolment).options(joinedload(Enrolment.student), joinedload(Enrolment.programme),
                                  joinedload(Enrolment.institution)).where(Enrolment.id == enrolment_id)
    ).scalar_one_or_none()
    if en is None:
        raise ApiError(404, "Not found.")
    ensure_institution(actor, en.institution_id)
    return en


@router.get("/enrolments")
def search(
    q: str | None = None,
    institution_id: str | None = None,
    programme_code: str | None = None,
    academic_year: str | None = None,
    status: str | None = None,
    seat_category: str | None = None,
    apaar_status: str | None = None,
    sort: str = "name",
    page: int = 1,
    page_size: int = 25,
    actor: Actor = Depends(_records_actor),
    db: Session = Depends(get_db),
):
    if actor.is_institution:
        if institution_id and institution_id != actor.institution_id:
            raise ApiError(403, "You can only search your own institution's records.")
        institution_id = actor.institution_id
    page_size = max(1, min(page_size, 100))
    stmt = (select(Enrolment).join(Student, Student.id == Enrolment.student_id)
            .join(Programme, Programme.id == Enrolment.programme_id)
            .options(joinedload(Enrolment.student), joinedload(Enrolment.programme), joinedload(Enrolment.institution)))
    if institution_id:
        stmt = stmt.where(Enrolment.institution_id == institution_id)
    if programme_code:
        stmt = stmt.where(Programme.code == programme_code.upper())
    if academic_year:
        stmt = stmt.where(Enrolment.academic_year == academic_year)
    if status:
        stmt = stmt.where(Enrolment.status.in_(status.split(",")))
    if seat_category:
        stmt = stmt.where(Enrolment.seat_category == seat_category)
    if apaar_status:
        stmt = stmt.where(Student.apaar_status == apaar_status)
    if q and q.strip():
        term = q.strip()
        digits = re.sub(r"[\s-]", "", term)
        if re.fullmatch(r"\d{12}", digits):
            stmt = stmt.where(Student.apaar_id == digits)  # exact APAAR only; no partial APAAR search
        else:
            like = f"%{term.lower()}%"
            stmt = stmt.where(or_(func.lower(Student.full_name).like(like),
                                  func.lower(Enrolment.institution_student_id).like(like)))
    desc = sort.startswith("-")
    col = SORTS.get(sort.lstrip("-"), Student.full_name)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = db.execute(stmt.order_by(col.desc() if desc else col.asc(), Enrolment.id)
                      .offset((max(page, 1) - 1) * page_size).limit(page_size)).unique().scalars().all()
    return {"items": [enrolment_view(e, actor) for e in rows], "total": total, "page": page, "page_size": page_size}


class ManualIn(BaseModel):
    academic_year: str = settings.current_year
    record: dict[str, str]
    acknowledge_review: bool = False
    status: str = "ACTIVE"


def _blocking(plan: engine.RowPlan, acknowledge: bool) -> None:
    if plan.status == "ERROR":
        raise ApiError(422, "The record has errors. Fix the highlighted fields.", findings=plan.findings,
                       row_status=plan.status)
    if plan.status == "REVIEW" and not acknowledge:
        raise ApiError(422, "This record will open a flag for review. Confirm to save it anyway.",
                       findings=plan.findings, row_status=plan.status, needs_acknowledgement=True)


@router.post("/enrolments")
def manual_entry(body: ManualIn, actor: Actor = Depends(require_roles(*INST_ROLES)), db: Session = Depends(get_db)):
    if body.status not in ("ACTIVE", "PROVISIONAL"):
        raise ApiError(422, "New records start as ACTIVE or PROVISIONAL.", field="status")
    inst = db.get(Institution, actor.institution_id)
    plan = engine.validate_rows(db, inst, body.academic_year, [(0, body.record)])[0]
    _blocking(plan, body.acknowledge_review)
    en = engine.commit_values(db, plan, institution=inst, academic_year=body.academic_year, actor=actor,
                              source="MANUAL", reason=f"Manual entry by {actor.user.full_name}", status=body.status)
    issues.run_capacity_checks(db, en.programme_id, en.academic_year, actor)
    db.commit()
    en = load_enrolment(db, en.id, actor)
    return {"enrolment": enrolment_view(en, actor), "findings": plan.findings, "row_status": plan.status}


@router.get("/enrolments/{enrolment_id}")
def detail(enrolment_id: str, actor: Actor = Depends(_records_actor), db: Session = Depends(get_db)):
    en = load_enrolment(db, enrolment_id, actor)
    revs = db.execute(select(RecordRevision).where(
        or_(RecordRevision.entity_id == en.id, RecordRevision.entity_id == en.student_id))
        .order_by(RecordRevision.at.desc())).scalars().all()
    flags = [i for i in db.execute(select(ValidationIssue).where(
        or_(ValidationIssue.entity_id == en.id, ValidationIssue.entity_id == en.student_id,
            ValidationIssue.entity_id.like(f"%{en.student_id}%")))).scalars() if issues.visible(actor, i)]
    creds = db.execute(select(Credential).where(Credential.enrolment_id == en.id)
                       .order_by(Credential.issued_at.desc())).scalars().all()
    other = db.execute(select(func.count()).select_from(Enrolment).where(
        Enrolment.student_id == en.student_id, Enrolment.institution_id != en.institution_id)).scalar()
    audit.record(db, actor, "record.view", "enrolment", en.id, institution_id=en.institution_id,
                 detail={"apaar_ref": en.student.apaar_ref})
    db.commit()
    return {
        "enrolment": enrolment_view(en, actor),
        "allowed_transitions": sorted(ledger.TRANSITIONS.get(en.status, set())),
        "history": [{"entity_type": r.entity_type, "version": r.version, "changes": _mask_changes(r.changes, actor, en),
                     "reason": r.reason, "actor_id": r.actor_id, "at": r.at.isoformat()} for r in revs],
        "flags": [issues.redact(db, i, actor) for i in flags],
        "credentials": [{"id": c.id, "status": c.status, "issued_at": c.issued_at.isoformat(),
                         "expires_at": c.expires_at.isoformat(), "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None,
                         "revocation_reason": c.revocation_reason} for c in creds],
        "enrolled_elsewhere": other > 0,
        "position": ledger.position(db, en.programme_id, en.academic_year),
    }


def _mask_changes(changes: dict, actor: Actor, en: Enrolment) -> dict:
    out = {}
    for k, v in changes.items():
        if k in ("social_category", "email") and actor.role == "AICTE_ANALYST":
            out[k] = {"old": "(hidden)", "new": "(hidden)"}
        else:
            out[k] = v
    return out


class PatchIn(BaseModel):
    version: int
    reason: str = Field(min_length=5, max_length=1000)
    changes: dict[str, str]
    acknowledge_review: bool = False
    correction_request_id: str | None = None


MASTER_FIELDS = {"full_name", "date_of_birth", "gender", "nationality_status", "citizenship_country", "apaar_id"}


@router.patch("/enrolments/{enrolment_id}")
def correct(enrolment_id: str, body: PatchIn, actor: Actor = Depends(require_roles(*INST_ROLES)),
            db: Session = Depends(get_db)):
    en = load_enrolment(db, enrolment_id, actor)
    if body.version != en.version:
        raise ApiError(409, "Someone else changed this record since you opened it. Reload and re-apply your change.",
                       current_version=en.version)
    row = row_from_enrolment(db, en)
    allowed = set(row) - {"academic_year"}
    bad = [k for k in body.changes if k not in allowed]
    if bad:
        raise ApiError(422, "These fields cannot be changed here: " + ", ".join(bad))
    changed = {k: v for k, v in body.changes.items() if (row.get(k) or "") != (v or "")}
    if not changed:
        raise ApiError(422, "Nothing changed.")
    if MASTER_FIELDS & set(changed):
        elsewhere = db.execute(select(Enrolment.id).where(Enrolment.student_id == en.student_id,
                                                         Enrolment.institution_id != en.institution_id)).first()
        if elsewhere:
            raise ApiError(409, "This student also has a record at another institution, so identity fields are "
                                "shared. Ask AICTE to correct the master record.")
    row.update(changed)
    inst = en.institution
    old_prog, old_year = en.programme_id, en.academic_year
    plan = engine.validate_rows(db, inst, en.academic_year, [(0, row)], self_enrolment_id=en.id)[0]
    plan.findings = [f for f in plan.findings
                     if f["rule_id"] not in ("D001_EXISTING_RECORD", "D004_ATTR_CONFLICT")
                     and not (f["rule_id"] == "D002_ROLL_CONFLICT" and f["evidence"].get("enrolment_id") == en.id)]
    plan.status = {3: "ERROR", 2: "REVIEW", 1: "WARNING", 0: "VALID"}[
        max((engine.SEVERITY_ORDER[f["severity"]] for f in plan.findings), default=0)]
    _blocking(plan, body.acknowledge_review)
    engine.commit_values(db, plan, institution=inst, academic_year=en.academic_year, actor=actor, source=en.source,
                         reason=body.reason, allow_master_update=True)
    if body.correction_request_id:
        cr = db.get(CorrectionRequest, body.correction_request_id)
        if cr and cr.enrolment_id == en.id and cr.status in ("OPEN", "ACCEPTED"):
            cr.status = "ACCEPTED"
            cr.resolution_note = (cr.resolution_note or "") + f" Applied: {body.reason}"
    for pid, year in {(old_prog, old_year), (en.programme_id, en.academic_year)}:
        issues.run_capacity_checks(db, pid, year, actor)
    db.commit()
    en = load_enrolment(db, en.id, actor)
    return {"enrolment": enrolment_view(en, actor), "findings": plan.findings}


class StatusIn(BaseModel):
    status: str
    reason: str = Field(min_length=5, max_length=1000)
    version: int


@router.post("/enrolments/{enrolment_id}/status")
def change_status(enrolment_id: str, body: StatusIn, actor: Actor = Depends(require_roles(*INST_ROLES)),
                  db: Session = Depends(get_db)):
    en = load_enrolment(db, enrolment_id, actor)
    if body.version != en.version:
        raise ApiError(409, "Someone else changed this record since you opened it. Reload and try again.",
                       current_version=en.version)
    if body.status not in ledger.TRANSITIONS.get(en.status, set()):
        allowed = sorted(ledger.TRANSITIONS.get(en.status, set()))
        raise ApiError(422, f"A {en.status} record cannot become {body.status}. "
                            + (f"Allowed: {', '.join(allowed)}." if allowed else "It is final."),
                       allowed=allowed)
    old = en.status
    en.status = body.status
    en.version += 1
    engine.add_revision(db, "enrolment", en.id, en.version, {"status": {"old": old, "new": body.status}},
                        body.reason, actor.id)
    audit.record(db, actor, "enrolment.status", "enrolment", en.id, detail={"from": old, "to": body.status})
    pos = issues.run_capacity_checks(db, en.programme_id, en.academic_year, actor)
    db.commit()
    en = load_enrolment(db, en.id, actor)
    return {"enrolment": enrolment_view(en, actor), "position": pos}


# ---------------------------------------------------------------- identity candidates


@router.get("/identity/candidates")
def candidates(decided: bool | None = None, actor: Actor = Depends(require_roles(*AICTE_ROLES)),
               db: Session = Depends(get_db)):
    q = select(IdentityCandidate).order_by(IdentityCandidate.score.desc())
    if decided is not None:
        q = q.where(IdentityCandidate.decision.is_not(None) if decided else IdentityCandidate.decision.is_(None))
    out = []
    for c in db.execute(q).scalars():
        sides = []
        for sid in (c.student_a, c.student_b):
            st = db.get(Student, sid)
            ens = db.execute(select(Enrolment).where(Enrolment.student_id == sid)).scalars().all()
            sides.append({
                "student": student_view(st, actor, set()),
                "enrolments": [{"institution_name": e.institution.name, "programme_code": e.programme.code,
                                "academic_year": e.academic_year, "status": e.status,
                                "institution_student_id": e.institution_student_id, "id": e.id} for e in ens],
            })
        out.append({"id": c.id, "score": c.score, "weights": c.weights, "decision": c.decision,
                     "decision_note": c.decision_note, "band": "REVIEW" if c.score >= identity.REVIEW_THRESHOLD else "LISTED",
                     "a": sides[0], "b": sides[1]})
    return out


class DecisionIn(BaseModel):
    decision: str
    note: str = Field(min_length=3, max_length=1000)


@router.post("/identity/candidates/{cand_id}/decision")
def decide(cand_id: str, body: DecisionIn, actor: Actor = Depends(require_roles("AICTE_ADMIN")),
           db: Session = Depends(get_db)):
    if body.decision not in ("SAME_PERSON", "DIFFERENT_PEOPLE"):
        raise ApiError(422, "Decision must be SAME_PERSON or DIFFERENT_PEOPLE.")
    c = db.get(IdentityCandidate, cand_id)
    if c is None:
        raise ApiError(404, "Not found.")
    c.decision, c.decided_by, c.decision_note = body.decision, actor.id, body.note
    issue = db.execute(select(ValidationIssue).where(ValidationIssue.rule_id == "D005_POSSIBLE_DUP_IDENTITY",
                                                     ValidationIssue.dedupe_key == f"{c.student_a}:{c.student_b}")
                       ).scalars().first()
    if issue is not None and issue.status in issues.OPEN_STATES:
        if body.decision == "DIFFERENT_PEOPLE":
            issues.apply_action(db, issue, actor, "DISMISS", f"Reviewer decision: different people. {body.note}")
        else:
            db.add(IssueEvent(issue_id=issue.id, actor_id=actor.id, actor_role=actor.role, action="DECISION_SAME_PERSON",
                              note=f"Reviewer decision: same person. Records are not merged automatically. {body.note}"))
    audit.record(db, actor, "identity.decision", "identity_candidate", c.id, detail={"decision": body.decision})
    db.commit()
    return {"id": c.id, "decision": c.decision}
