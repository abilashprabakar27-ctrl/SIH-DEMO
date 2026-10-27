"""Public token verification, credential status, and consent-based verification requests."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..db import get_db, utcnow
from ..models import Credential, Enrolment, Student, VerificationRequest
from ..security import ANONYMOUS, Actor, ApiError, client_ip, current_actor, limiter, mask_apaar, require_roles
from . import credentials as creds
from .normalize import parse_date

router = APIRouter(prefix="/api/v1/verification", tags=["verification"])
SAME_RESPONSE = "If the details match, the student will be asked for consent."
SHARED_FIELDS = ["Name", "APAAR ID (masked)", "Institutions", "Programmes", "Admission years", "Enrolment statuses",
                 "APAAR registry check result (SIMULATED)"]


class TokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=20000)


def _rate(request: Request, bucket: str) -> None:
    if not limiter.hit(f"{bucket}:{client_ip(request)}", settings.verify_rate_per_minute, 60):
        raise ApiError(429, "Too many verification attempts. Wait a minute and try again.")


@router.post("/verify-token")
def verify_token(body: TokenIn, request: Request, db: Session = Depends(get_db)):
    """Public. Presenting a token is the holder's consent to disclose the claims inside it."""
    _rate(request, "verify")
    result = creds.verify(db, body.token)
    audit.record(db, ANONYMOUS, "credential.verify", "credential", result.get("credential_id"),
                 outcome="SUCCESS" if result["valid"] else "FAILED",
                 detail={"valid": result["valid"], "failed": [c["check"] for c in result["checks"] if c["result"] == "fail"],
                         "claims_disclosed": sorted(result["claims"]), "ip": client_ip(request)})
    db.commit()
    return result


class TamperIn(BaseModel):
    token: str = Field(min_length=1, max_length=20000)
    mode: str = "disclosure"


@router.post("/tamper-demo")
def tamper_demo(body: TamperIn, request: Request):
    """Demo only: returns the token with one disclosed value (or the payload) edited, without re-signing."""
    _rate(request, "tamper")
    try:
        return {"token": creds.tamper(body.token, body.mode), "mode": body.mode}
    except Exception as exc:  # noqa: BLE001
        raise ApiError(422, "That token could not be edited; paste a complete record token.") from exc


@router.get("/credentials/{cred_id}")
def credential_status(cred_id: str, request: Request, db: Session = Depends(get_db)):
    _rate(request, "status")
    c = db.get(Credential, cred_id)
    if c is None:
        raise ApiError(404, "No record with this ID.")
    return creds.public_status(c)


# ---------------------------------------------------------------- consent-based requests


class RequestIn(BaseModel):
    apaar_id: str
    date_of_birth: str
    purpose: str = Field(min_length=10, max_length=500)


def _req_view(r: VerificationRequest, for_verifier: bool) -> dict:
    status = r.status
    if for_verifier and status == "NO_MATCH":
        status = "PENDING_CONSENT"  # indistinguishable from a real pending request
    expired = utcnow() > r.expires_at
    return {"id": r.id, "requester_org": r.requester_org, "purpose": r.purpose, "status": status,
            "expired": expired and status == "PENDING_CONSENT", "created_at": r.created_at.isoformat(),
            "expires_at": r.expires_at.isoformat(),
            "consent_decided_at": None if for_verifier and r.status == "NO_MATCH" else
            (r.consent_decided_at.isoformat() if r.consent_decided_at else None)}


@router.post("/requests")
def create_request(body: RequestIn, actor: Actor = Depends(require_roles("VERIFIER")), db: Session = Depends(get_db)):
    if not limiter.hit(f"vreq:{actor.id}", settings.verifier_requests_per_hour, 3600):
        raise ApiError(429, "Request limit reached for this hour.")
    aid = "".join(ch for ch in body.apaar_id if ch.isdigit())
    dob = parse_date(body.date_of_birth)
    if len(aid) != 12 or dob is None:
        raise ApiError(422, "Enter the full 12-digit APAAR ID and the date of birth (YYYY-MM-DD).")
    st = db.execute(select(Student).where(Student.apaar_id == aid)).scalar_one_or_none()
    matched = st is not None and st.date_of_birth == dob
    now = utcnow()
    r = VerificationRequest(requester_id=actor.id, requester_org=actor.user.organisation or actor.user.full_name,
                            student_id=st.id if matched else None, purpose=body.purpose,
                            status="PENDING_CONSENT" if matched else "NO_MATCH", expires_at=now + timedelta(days=7))
    db.add(r)
    db.flush()
    audit.record(db, actor, "verification.request", "verification_request", r.id,
                 detail={"purpose": body.purpose[:120]})  # match outcome deliberately not logged in detail
    db.commit()
    return dict(_req_view(r, True), message=SAME_RESPONSE)


@router.get("/requests")
def list_requests(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    if actor.role == "VERIFIER":
        rows = db.execute(select(VerificationRequest).where(VerificationRequest.requester_id == actor.id)
                          .order_by(VerificationRequest.created_at.desc())).scalars()
        return [_req_view(r, True) for r in rows]
    if actor.role == "STUDENT":
        rows = db.execute(select(VerificationRequest).where(VerificationRequest.student_id == actor.student_id)
                          .order_by(VerificationRequest.created_at.desc())).scalars()
        return [dict(_req_view(r, False), fields_shared=SHARED_FIELDS) for r in rows]
    raise ApiError(403, "Your role does not allow this action.")


class ConsentIn(BaseModel):
    decision: str


@router.post("/requests/{req_id}/consent")
def consent(req_id: str, body: ConsentIn, actor: Actor = Depends(require_roles("STUDENT")), db: Session = Depends(get_db)):
    r = db.get(VerificationRequest, req_id)
    if r is None or r.student_id is None or r.student_id != actor.student_id:
        raise ApiError(404, "Not found.")
    if body.decision not in ("APPROVE", "DENY"):
        raise ApiError(422, "Decision must be APPROVE or DENY.")
    if r.status != "PENDING_CONSENT":
        raise ApiError(409, f"You already decided this request ({r.status.lower()}).")
    if utcnow() > r.expires_at:
        raise ApiError(409, "This request has expired.")
    r.status = "APPROVED" if body.decision == "APPROVE" else "DENIED"
    r.consent_decided_at = utcnow()
    audit.record(db, actor, "consent.decision", "verification_request", r.id, detail={"decision": r.status})
    db.commit()
    return _req_view(r, False)


@router.get("/requests/{req_id}/result")
def result(req_id: str, actor: Actor = Depends(require_roles("VERIFIER")), db: Session = Depends(get_db)):
    r = db.get(VerificationRequest, req_id)
    if r is None or r.requester_id != actor.id:
        raise ApiError(404, "Not found.")
    if r.status != "APPROVED" or utcnow() > r.expires_at:
        raise ApiError(403, "The student has not given consent for this request.")
    st = db.get(Student, r.student_id)
    ens = db.execute(select(Enrolment).where(Enrolment.student_id == st.id).order_by(Enrolment.academic_year)).scalars()
    audit.record(db, actor, "verification.result_view", "verification_request", r.id)
    db.commit()
    return {
        "request_id": r.id,
        "name": st.full_name,
        "apaar_id_masked": mask_apaar(st.apaar_id),
        "registry_status": {"status": st.apaar_status, "mode": "SIMULATED"},
        "enrolments": [{"institution": e.institution.name, "programme": f"{e.programme.code} — {e.programme.name}",
                        "academic_year": e.academic_year, "status": e.status} for e in ens],
        "fields_shared": SHARED_FIELDS,
    }
