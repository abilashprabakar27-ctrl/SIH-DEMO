"""Signed enrolment records: issue, list, revoke, printable certificate, QR, issuer keys."""

from __future__ import annotations

import html

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..db import get_db, utcnow
from ..models import Credential, Enrolment, Institution, Programme, Student
from ..security import Actor, ApiError, current_actor, ensure_institution, mask_apaar, require_roles
from . import credentials as creds

router = APIRouter(prefix="/api/v1", tags=["credentials"])
wellknown = APIRouter(tags=["credentials"])


@wellknown.get("/.well-known/issuer-keys")
def issuer_keys():
    return creds.jwks()


def cred_view(c: Credential) -> dict:
    return {"id": c.id, "enrolment_id": c.enrolment_id, "status": c.status, "key_id": c.key_id,
            "issued_at": c.issued_at.isoformat(), "expires_at": c.expires_at.isoformat(),
            "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None, "revocation_reason": c.revocation_reason}


@router.post("/enrolments/{enrolment_id}/credentials")
def issue(enrolment_id: str, actor: Actor = Depends(require_roles("INST_ADMIN")), db: Session = Depends(get_db)):
    en = db.get(Enrolment, enrolment_id)
    if en is None:
        raise ApiError(404, "Not found.")
    ensure_institution(actor, en.institution_id)
    if en.status not in ("ACTIVE", "GRADUATED"):
        raise ApiError(422, f"Signed records are issued for ACTIVE or GRADUATED enrolments (this one is {en.status}).")
    st = db.get(Student, en.student_id)
    if not st.apaar_id:
        raise ApiError(422, "The student has no APAAR ID yet; a signed record needs one.")
    if st.apaar_status != "VERIFIED":
        raise ApiError(422, "The student's APAAR ID has not matched the registry (SIMULATED); "
                            "resolve the APAAR flag before issuing a signed record.")
    c = creds.issue(db, en, actor.id)
    audit.record(db, actor, "credential.issue", "credential", c.id, detail={"enrolment_id": en.id})
    db.commit()
    return cred_view(c)


@router.get("/enrolments/{enrolment_id}/credentials")
def list_for_enrolment(enrolment_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    en = db.get(Enrolment, enrolment_id)
    if en is None or not (actor.role == "AICTE_ADMIN" or (actor.is_institution and actor.institution_id == en.institution_id)
                          or actor.student_id == en.student_id):
        raise ApiError(404, "Not found.")
    rows = db.execute(select(Credential).where(Credential.enrolment_id == en.id)
                      .order_by(Credential.issued_at.desc())).scalars()
    return [cred_view(c) for c in rows]


class RevokeIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


@router.post("/credentials/{cred_id}/revoke")
def revoke(cred_id: str, body: RevokeIn, actor: Actor = Depends(require_roles("INST_ADMIN", "AICTE_ADMIN")),
           db: Session = Depends(get_db)):
    c = db.get(Credential, cred_id)
    if c is None:
        raise ApiError(404, "Not found.")
    en = db.get(Enrolment, c.enrolment_id)
    ensure_institution(actor, en.institution_id)
    if c.status != "ACTIVE":
        raise ApiError(409, f"This record is already {c.status.lower()}.")
    c.status, c.revoked_at, c.revocation_reason = "REVOKED", utcnow(), body.reason
    audit.record(db, actor, "credential.revoke", "credential", c.id, detail={"reason": body.reason},
                 institution_id=en.institution_id)
    db.commit()
    return cred_view(c)


def _viewable(db: Session, cred_id: str, actor: Actor) -> tuple[Credential, Enrolment]:
    c = db.get(Credential, cred_id)
    if c is None:
        raise ApiError(404, "Not found.")
    en = db.get(Enrolment, c.enrolment_id)
    if not (actor.role == "AICTE_ADMIN" or (actor.is_institution and actor.institution_id == en.institution_id)
            or actor.student_id == c.student_id):
        raise ApiError(404, "Not found.")
    return c, en


def verify_url(cred_id: str) -> str:
    return f"{settings.public_base_url}/#/verify?cid={cred_id}"


def qr_svg(data: str) -> str:
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2,
                      error_correction=qrcode.constants.ERROR_CORRECT_L)
    return img.to_string(encoding="unicode")


@router.get("/credentials/{cred_id}/qr.svg")
def qr(cred_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    c, _ = _viewable(db, cred_id, actor)
    return Response(qr_svg(verify_url(c.id)), media_type="image/svg+xml")


@router.get("/credentials/{cred_id}/certificate", response_class=HTMLResponse)
def certificate(cred_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    c, en = _viewable(db, cred_id, actor)
    st = db.get(Student, en.student_id)
    inst = db.get(Institution, en.institution_id)
    prog = db.get(Programme, en.programme_id)
    e = html.escape
    apaar = st.apaar_id if st.apaar_id else "—"
    apaar_fmt = f"{apaar[:4]} {apaar[4:8]} {apaar[8:]}" if len(apaar) == 12 else apaar
    status_line = {"ACTIVE": "Active", "REVOKED": f"Revoked on {c.revoked_at:%d %b %Y}: {c.revocation_reason}" if c.revoked_at else "Revoked",
                   "SUPERSEDED": "Superseded by a newer record"}[c.status]
    audit.record(db, actor, "credential.certificate_view", "credential", c.id)
    db.commit()
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Enrolment record {e(c.id[:8])}</title>
<style>
@page {{ size: A4; margin: 18mm; }}
body {{ font-family: 'Atkinson Hyperlegible', system-ui, sans-serif; color:#1b2a41; background:#f3f6f5; margin:0; }}
.sheet {{ position:relative; max-width:760px; margin:24px auto; background:#fff; border:1px solid #c9d4d1; padding:40px 48px; overflow:hidden; }}
.wm {{ position:absolute; inset:0; display:flex; align-items:center; justify-content:center; pointer-events:none;
       font-size:54px; font-weight:700; color:rgba(180,35,24,.09); transform:rotate(-24deg); white-space:nowrap; }}
h1 {{ font-size:22px; margin:0 0 4px; }} .sub {{ color:#4a5a70; margin:0 0 24px; }}
.ids {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin:20px 0; }}
.id {{ border:1px solid #c9d4d1; border-radius:6px; padding:10px 14px; }}
.id small {{ display:block; color:#4a5a70; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
.id b {{ font-family:'IBM Plex Mono', ui-monospace, monospace; font-size:20px; }}
table {{ border-collapse:collapse; width:100%; }} td {{ padding:6px 0; border-bottom:1px solid #e3e9e7; vertical-align:top; }}
td:first-child {{ color:#4a5a70; width:40%; }} .foot {{ display:flex; gap:20px; align-items:center; margin-top:24px; }}
.qr svg {{ width:140px; height:140px; }} .note {{ font-size:12px; color:#4a5a70; }}
.pill {{ display:inline-block; background:#fdf1e1; color:#a8650f; border-radius:99px; padding:2px 10px; font-size:12px; }}
</style></head><body><div class="sheet"><div class="wm">SAMPLE · SYNTHETIC DATA</div>
<p class="pill">APAAR checks simulated · synthetic data</p>
<h1>Student enrolment record</h1><p class="sub">{e(inst.name)} · AICTE code {e(inst.aicte_code)}</p>
<div class="ids"><div class="id"><small>APAAR ID</small><b>{e(apaar_fmt)}</b><div class="note">Registry check: {e(st.apaar_status)} (SIMULATED)</div></div>
<div class="id"><small>Institution student ID</small><b>{e(en.institution_student_id)}</b></div></div>
<table><tr><td>Name</td><td>{e(st.full_name)}</td></tr>
<tr><td>Programme</td><td>{e(prog.code)} — {e(prog.name)}</td></tr>
<tr><td>Admission year</td><td>{e(en.academic_year)}</td></tr>
<tr><td>Enrolment status</td><td>{e(en.status)}</td></tr>
<tr><td>Record ID</td><td>{e(c.id)}</td></tr>
<tr><td>Issued / valid until</td><td>{c.issued_at:%d %b %Y} / {c.expires_at:%d %b %Y}</td></tr>
<tr><td>Record status</td><td>{e(status_line)}</td></tr></table>
<div class="foot"><div class="qr">{qr_svg(verify_url(c.id))}</div>
<p class="note">Scan to check this record's status in the register, or ask the student for a selective-disclosure
token. Signed with Ed25519 key {e(c.key_id)} published at /.well-known/issuer-keys.
This is a prototype document built on synthetic data; it is not an official certificate.</p></div>
</div></body></html>"""
    return HTMLResponse(page, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'"})


def _unused() -> str:
    return mask_apaar("")
