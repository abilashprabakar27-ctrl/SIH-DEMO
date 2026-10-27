"""Student self-service (/me) and the institution correction-request queue."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db, utcnow
from ..models import CorrectionRequest, Credential, Enrolment, Notification, Student
from ..security import INST_ROLES, Actor, ApiError, require_roles
from . import credentials as creds
from .api_credentials import qr_svg
from .views import enrolment_view, student_view

router = APIRouter(prefix="/api/v1", tags=["students"])
student_only = require_roles("STUDENT")
CORRECTABLE = {"full_name", "date_of_birth", "gender", "citizenship_country", "email", "institution_student_id",
               "programme_code", "seat_category", "admission_date", "nationality_status", "apaar_id"}


@router.get("/me/record")
def my_record(actor: Actor = Depends(student_only), db: Session = Depends(get_db)):
    st = db.get(Student, actor.student_id)
    if st is None:
        raise ApiError(404, "No student record is linked to this account.")
    ens = db.execute(select(Enrolment).where(Enrolment.student_id == st.id).order_by(Enrolment.academic_year)).scalars().all()
    cred_rows = db.execute(select(Credential).where(Credential.student_id == st.id)
                           .order_by(Credential.issued_at.desc())).scalars().all()
    crs = db.execute(select(CorrectionRequest).where(CorrectionRequest.student_id == st.id)
                     .order_by(CorrectionRequest.created_at.desc())).scalars().all()
    audit.record(db, actor, "record.view", "student", st.id, detail={"self": True})
    db.commit()
    return {
        "student": student_view(st, actor, set()),
        "enrolments": [enrolment_view(e, actor) for e in ens],
        "credentials": [{"id": c.id, "enrolment_id": c.enrolment_id, "status": c.status,
                         "issued_at": c.issued_at.isoformat(), "expires_at": c.expires_at.isoformat(),
                         "revocation_reason": c.revocation_reason,
                         "claims": creds.holder_claims(c) if c.status == "ACTIVE" else []} for c in cred_rows],
        "correction_requests": [_cr_view(c) for c in crs],
    }


class PresentIn(BaseModel):
    claims: list[str] = Field(min_length=1)


@router.post("/me/credentials/{cred_id}/present")
def present(cred_id: str, body: PresentIn, actor: Actor = Depends(student_only), db: Session = Depends(get_db)):
    c = db.get(Credential, cred_id)
    if c is None or c.student_id != actor.student_id:
        raise ApiError(404, "Not found.")
    unknown = [x for x in body.claims if x not in creds.CLAIMS]
    if unknown:
        raise ApiError(422, "Unknown claim(s): " + ", ".join(unknown))
    token = creds.present(c, body.claims)
    from .api_credentials import verify_url  # noqa: PLC0415

    url = verify_url(c.id).replace(f"?cid={c.id}", "?t=" + token)
    audit.record(db, actor, "credential.present", "credential", c.id, detail={"claims": sorted(body.claims)})
    db.commit()
    try:
        qr = qr_svg(url)
    except Exception:  # noqa: BLE001  (token too long for a single QR code)
        qr = None
    return {"token": token, "verify_url": url, "qr_svg": qr, "claims": sorted(body.claims)}


def _cr_view(c: CorrectionRequest, with_record: Enrolment | None = None, actor: Actor | None = None) -> dict:
    out = {"id": c.id, "enrolment_id": c.enrolment_id, "field": c.field, "requested_value": c.requested_value,
           "explanation": c.explanation, "status": c.status, "due_at": c.due_at.isoformat(),
           "overdue": c.status == "OPEN" and c.due_at < utcnow(), "resolution_note": c.resolution_note,
           "created_at": c.created_at.isoformat()}
    if with_record is not None and actor is not None:
        out["record"] = enrolment_view(with_record, actor)
    return out


class CorrectionIn(BaseModel):
    enrolment_id: str
    field: str
    requested_value: str = Field(min_length=1, max_length=300)
    explanation: str = Field(min_length=10, max_length=2000)


@router.get("/me/correction-requests")
def my_corrections(actor: Actor = Depends(student_only), db: Session = Depends(get_db)):
    rows = db.execute(select(CorrectionRequest).where(CorrectionRequest.student_id == actor.student_id)
                      .order_by(CorrectionRequest.created_at.desc())).scalars()
    return [_cr_view(c) for c in rows]


@router.post("/me/correction-requests")
def raise_correction(body: CorrectionIn, actor: Actor = Depends(student_only), db: Session = Depends(get_db)):
    en = db.get(Enrolment, body.enrolment_id)
    if en is None or en.student_id != actor.student_id:
        raise ApiError(404, "Not found.")
    if body.field not in CORRECTABLE:
        raise ApiError(422, "You can ask to correct: " + ", ".join(sorted(CORRECTABLE)), field="field")
    c = CorrectionRequest(student_id=actor.student_id, enrolment_id=en.id, institution_id=en.institution_id,
                          field=body.field, requested_value=body.requested_value, explanation=body.explanation,
                          status="OPEN", due_at=utcnow() + timedelta(days=14))
    db.add(c)
    db.flush()
    db.add(Notification(institution_id=en.institution_id, kind="correction",
                        message=f"Student correction request for {en.institution_student_id}: {body.field}",
                        link="/corrections"))
    audit.record(db, actor, "correction.request", "correction_request", c.id, detail={"field": body.field},
                 institution_id=en.institution_id)
    db.commit()
    return _cr_view(c)


@router.get("/correction-requests")
def queue(status: str | None = "OPEN", actor: Actor = Depends(require_roles(*INST_ROLES)), db: Session = Depends(get_db)):
    q = select(CorrectionRequest).where(CorrectionRequest.institution_id == actor.institution_id)
    if status:
        q = q.where(CorrectionRequest.status.in_(status.split(",")))
    rows = db.execute(q.order_by(CorrectionRequest.due_at)).scalars().all()
    return [_cr_view(c, db.get(Enrolment, c.enrolment_id), actor) for c in rows]


class CorrectionAction(BaseModel):
    action: str
    note: str = Field(default="", max_length=1000)


@router.post("/correction-requests/{cr_id}/actions")
def act(cr_id: str, body: CorrectionAction, actor: Actor = Depends(require_roles(*INST_ROLES)),
        db: Session = Depends(get_db)):
    c = db.get(CorrectionRequest, cr_id)
    if c is None or c.institution_id != actor.institution_id:
        raise ApiError(404, "Not found.")
    if c.status != "OPEN":
        raise ApiError(409, f"This request is already {c.status.lower()}.")
    if body.action == "REJECT":
        if len(body.note.strip()) < 5:
            raise ApiError(422, "Explain to the student why the request is rejected.", field="note")
        c.status, c.resolution_note = "REJECTED", body.note
    elif body.action == "ACCEPT":
        c.status, c.resolution_note = "ACCEPTED", body.note or "Accepted; correction to be applied."
    else:
        raise ApiError(422, "Action must be ACCEPT or REJECT.")
    audit.record(db, actor, f"correction.{body.action.lower()}", "correction_request", c.id)
    db.commit()
    return dict(_cr_view(c), prefill={"enrolment_id": c.enrolment_id, "field": c.field, "value": c.requested_value,
                                      "correction_request_id": c.id})
