"""Selective-disclosure enrolment records (SD-JWT style, W3C VC 2.0-shaped payload, Ed25519).

Token = <header>.<payload>.<signature>~<disclosure>~<disclosure>~...~
Each disclosure = base64url(JSON([salt, claim, value])); the payload carries only
credentialSubject._sd = [base64url(sha256(disclosure))]. The holder chooses which
disclosures to present; the verifier can check each against the signed digests.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Credential, Enrolment, Institution, Programme, Student
from ..security import mask_apaar

CLAIMS = (
    "apaarId",
    "name",
    "institutionStudentId",
    "institution",
    "aicteInstitutionCode",
    "programme",
    "admissionYear",
    "enrolmentStatus",
)
CLAIM_LABELS = {
    "apaarId": "APAAR ID",
    "name": "Name",
    "institutionStudentId": "Institution student ID",
    "institution": "Institution",
    "aicteInstitutionCode": "AICTE institution code",
    "programme": "Programme",
    "admissionYear": "Admission year",
    "enrolmentStatus": "Enrolment status",
}
VALIDITY_DAYS = 365


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ---------------------------------------------------------------- keys


class IssuerKey:
    def __init__(self, private: Ed25519PrivateKey):
        self.private = private
        self.public = private.public_key()
        raw = self.public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.raw_public = raw
        self.kid = "ed25519-" + hashlib.sha256(raw).hexdigest()[:16]

    def jwk(self) -> dict:
        return {"kty": "OKP", "crv": "Ed25519", "x": b64u(self.raw_public), "kid": self.kid, "use": "sig", "alg": "EdDSA"}


_key: IssuerKey | None = None


def issuer_key() -> IssuerKey:
    """Load the Ed25519 issuer key from var/, generating it (mode 0600) on first start."""
    global _key
    if _key is None and os.environ.get("ISSUER_PRIVATE_KEY_PEM"):
        pem = os.environ["ISSUER_PRIVATE_KEY_PEM"].replace("\\n", "\n").encode()
        _key = IssuerKey(serialization.load_pem_private_key(pem, password=None))
    if _key is None and settings.database_url.startswith("postgresql"):
        from ..secret_store import db_secret

        def _new_pem() -> str:
            return Ed25519PrivateKey.generate().private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()

        _key = IssuerKey(serialization.load_pem_private_key(db_secret("issuer_ed25519_pem", _new_pem).encode(), password=None))
    if _key is None:
        path = settings.var_dir / "issuer_ed25519.pem"
        if not path.exists():
            pk = Ed25519PrivateKey.generate()
            pem = pk.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                   serialization.NoEncryption())
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(pem)
        pk = serialization.load_pem_private_key(path.read_bytes(), password=None)
        _key = IssuerKey(pk)
    return _key


def jwks() -> dict:
    return {"keys": [issuer_key().jwk()]}


def known_public_key(kid: str) -> Ed25519PublicKey | None:
    k = issuer_key()
    return k.public if kid == k.kid else None


# ---------------------------------------------------------------- issuance


def _disclosure(claim: str, value) -> str:
    return b64u(json.dumps([b64u(secrets.token_bytes(16)), claim, value], separators=(",", ":")).encode())


def digest(disclosure: str) -> str:
    return b64u(hashlib.sha256(disclosure.encode()).digest())


def sign_jws(header: dict, payload: dict, key: Ed25519PrivateKey) -> str:
    h = b64u(json.dumps(header, separators=(",", ":")).encode())
    p = b64u(json.dumps(payload, separators=(",", ":")).encode())
    sig = key.sign(f"{h}.{p}".encode())
    return f"{h}.{p}.{b64u(sig)}"


def claim_values(db: Session, en: Enrolment) -> dict:
    st = db.get(Student, en.student_id)
    inst = db.get(Institution, en.institution_id)
    prog = db.get(Programme, en.programme_id)
    return {
        "apaarId": st.apaar_id,
        "name": st.full_name,
        "institutionStudentId": en.institution_student_id,
        "institution": inst.name,
        "aicteInstitutionCode": inst.aicte_code,
        "programme": f"{prog.code} — {prog.name}",
        "admissionYear": en.academic_year,
        "enrolmentStatus": en.status,
    }


def build_token(cred_id: str, values: dict, issued: datetime, expires: datetime,
                key: IssuerKey | None = None) -> str:
    key = key or issuer_key()
    disclosures = [_disclosure(c, values[c]) for c in CLAIMS]
    payload = {
        "@context": ["https://www.w3.org/ns/credentials/v2"],
        "type": ["VerifiableCredential", "StudentEnrolmentRecord"],
        "id": f"urn:uuid:{cred_id}",
        "issuer": settings.issuer_id,
        "validFrom": issued.isoformat(timespec="seconds"),
        "validUntil": expires.isoformat(timespec="seconds"),
        "credentialStatus": {
            "id": f"{settings.public_base_url}/api/v1/verification/credentials/{cred_id}",
            "type": "RegisterStatusEndpoint",
        },
        "credentialSubject": {"_sd": sorted(digest(d) for d in disclosures)},
        "_sd_alg": "sha-256",
        "iss": settings.issuer_id,
        "jti": cred_id,
        "iat": int(issued.timestamp()),
        "nbf": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
    }
    header = {"alg": "EdDSA", "typ": "vc+sd-jwt", "kid": key.kid}
    return sign_jws(header, payload, key.private) + "~" + "~".join(disclosures) + "~"


def issue(db: Session, en: Enrolment, issued_by: str, now: datetime | None = None) -> Credential:
    now = (now or datetime.now(UTC)).replace(microsecond=0)
    cred_id = str(uuid.uuid4())
    expires = now + timedelta(days=VALIDITY_DAYS)
    for old in db.execute(
        select(Credential).where(Credential.enrolment_id == en.id, Credential.status == "ACTIVE")
    ).scalars():
        old.status = "SUPERSEDED"
    token = build_token(cred_id, claim_values(db, en), now, expires)
    cred = Credential(id=cred_id, enrolment_id=en.id, student_id=en.student_id, key_id=issuer_key().kid,
                      token=token, issued_by=issued_by, issued_at=now, expires_at=expires, status="ACTIVE")
    db.add(cred)
    db.flush()
    return cred


def split(token: str) -> tuple[str, list[str]]:
    parts = token.strip().split("~")
    return parts[0], [p for p in parts[1:] if p]


def decode_disclosure(d: str) -> tuple[str, str, object]:
    arr = json.loads(b64u_decode(d))
    if not (isinstance(arr, list) and len(arr) == 3 and isinstance(arr[1], str)):
        raise ValueError("bad disclosure")
    return arr[0], arr[1], arr[2]


def holder_claims(cred: Credential) -> list[dict]:
    """Claims with their disclosures, for the holder's selective-disclosure picker."""
    _, discs = split(cred.token)
    out = []
    for d in discs:
        _salt, claim, value = decode_disclosure(d)
        out.append({"claim": claim, "label": CLAIM_LABELS.get(claim, claim), "value": value, "disclosure": d})
    out.sort(key=lambda c: CLAIMS.index(c["claim"]) if c["claim"] in CLAIMS else 99)
    return out


def present(cred: Credential, claims: list[str]) -> str:
    jws, discs = split(cred.token)
    chosen = [d for d in discs if decode_disclosure(d)[1] in set(claims)]
    return jws + "~" + "".join(d + "~" for d in chosen)


def tamper(token: str, mode: str) -> str:
    """Demo helper: alter a disclosed value or the payload without re-signing."""
    jws, discs = split(token)
    if mode == "disclosure" and discs:
        salt, claim, value = decode_disclosure(discs[-1])
        changed = "GRADUATED" if claim == "enrolmentStatus" and value != "GRADUATED" else f"{value} (edited)"
        discs[-1] = b64u(json.dumps([salt, claim, changed], separators=(",", ":")).encode())
    else:
        h, p, s = jws.split(".")
        payload = json.loads(b64u_decode(p))
        payload["validUntil"] = "2099-12-31T00:00:00+00:00"
        jws = f"{h}.{b64u(json.dumps(payload, separators=(',', ':')).encode())}.{s}"
    return jws + "~" + "".join(d + "~" for d in discs)


# ---------------------------------------------------------------- verification


def verify(db: Session, token: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    checks: list[dict] = []

    def add(key, label, ok, sentence):
        checks.append({"check": key, "label": label, "result": "pass" if ok else "fail", "sentence": sentence})
        return ok

    def skip(key, label):
        checks.append({"check": key, "label": label, "result": "skipped",
                       "sentence": "Not checked because an earlier check failed."})

    order = [("structure", "Structure"), ("key", "Known issuer key"), ("signature", "Signature"),
             ("disclosures", "Disclosed values match the signed record"), ("validity", "Validity period"),
             ("status", "Revocation status")]
    result = {"valid": False, "checks": checks, "claims": {}, "apaar_display": None, "credential_id": None,
              "status": None, "notes": [], "registry_mode": "SIMULATED"}

    # 1 structure
    try:
        jws, discs = split(token or "")
        h64, p64, s64 = jws.split(".")
        header = json.loads(b64u_decode(h64))
        payload = json.loads(b64u_decode(p64))
        sig = b64u_decode(s64)
        decoded = [decode_disclosure(d) for d in discs]
        sd = payload["credentialSubject"]["_sd"]
        assert isinstance(sd, list)
        structure_ok = True
    except Exception:  # noqa: BLE001
        structure_ok = False
    if not add("structure", "Structure", structure_ok,
               "The record is a well-formed signed token with readable disclosures." if structure_ok
               else "This is not a readable signed record. Check that the whole token was copied."):
        for k, lbl in order[1:]:
            skip(k, lbl)
        return result

    # 2 key
    pub = known_public_key(header.get("kid", ""))
    if not add("key", "Known issuer key", pub is not None and header.get("alg") == "EdDSA",
               f"Signed with the register's published key {header.get('kid')}." if pub
               else "The signing key is not one the register publishes at /.well-known/issuer-keys."):
        for k, lbl in order[2:]:
            skip(k, lbl)
        return result

    # 3 signature
    try:
        pub.verify(sig, f"{h64}.{p64}".encode())
        sig_ok = True
    except InvalidSignature:
        sig_ok = False
    if not add("signature", "Signature", sig_ok,
               "The signature is valid: the signed part has not been changed since issue." if sig_ok
               else "The signature does not match. The record was altered after it was issued."):
        for k, lbl in order[3:]:
            skip(k, lbl)
        return result

    # 4 disclosures
    sd_set = set(sd)
    bad = [c for d, (_s, c, _v) in zip(discs, decoded, strict=True) if digest(d) not in sd_set]
    add("disclosures", "Disclosed values match the signed record", not bad,
        f"All {len(discs)} disclosed value(s) match digests in the signed record." if not bad
        else f"Disclosed value(s) for {', '.join(bad)} do not match the signed record (altered).")

    # 5 validity
    try:
        vf = datetime.fromisoformat(payload["validFrom"])
        vu = datetime.fromisoformat(payload["validUntil"])
        in_period = vf <= now <= vu
        add("validity", "Validity period", in_period,
            f"Valid from {vf:%d %b %Y} until {vu:%d %b %Y}." if in_period
            else f"Outside its validity period ({vf:%d %b %Y} to {vu:%d %b %Y}).")
    except Exception:  # noqa: BLE001
        in_period = False
        add("validity", "Validity period", False, "The validity dates are missing or unreadable.")

    # 6 status
    cred_id = str(payload.get("id", "")).removeprefix("urn:uuid:")
    result["credential_id"] = cred_id
    cred = db.get(Credential, cred_id)
    status_ok = cred is not None and cred.status == "ACTIVE"
    if cred is None:
        sentence = "The register has no record with this ID."
    elif cred.status == "ACTIVE":
        sentence = "The register lists this record as active (not revoked)."
    elif cred.status == "REVOKED":
        sentence = f"Revoked on {cred.revoked_at:%d %b %Y}: {cred.revocation_reason}"
    else:
        sentence = "Superseded: the institution issued a newer record for this enrolment."
    add("status", "Revocation status", status_ok, sentence)
    result["status"] = cred.status if cred else None
    if cred is not None and cred.status == "REVOKED":
        result["revoked_at"] = cred.revoked_at.isoformat()
        result["revocation_reason"] = cred.revocation_reason

    # disclosed claims only (never the undisclosed ones)
    disclosed = {c: v for d, (_s, c, v) in zip(discs, decoded, strict=True) if digest(d) in sd_set}
    result["claims"] = {c: disclosed[c] for c in CLAIMS if c in disclosed}
    result["claim_labels"] = {c: CLAIM_LABELS[c] for c in result["claims"]}
    if "apaarId" in disclosed:
        result["apaar_display"] = disclosed["apaarId"]
        result["apaar_disclosed"] = True
    elif cred is not None:
        st = db.get(Student, cred.student_id)
        result["apaar_display"] = mask_apaar(st.apaar_id) if st else None
        result["apaar_disclosed"] = False

    # currency note: enrolment changed after issuance
    if cred is not None:
        en = db.get(Enrolment, cred.enrolment_id)
        issued_status = next((v for (_s, c, v) in (decode_disclosure(d) for d in split(cred.token)[1])
                              if c == "enrolmentStatus"), None)
        if en is not None and issued_status and en.status != issued_status:
            result["notes"].append("The enrolment status has changed since this record was issued. "
                                   "Ask the student for a current record.")
    result["valid"] = all(c["result"] == "pass" for c in checks)
    return result


def public_status(cred: Credential) -> dict:
    out = {"id": cred.id, "status": cred.status, "issued_at": cred.issued_at.isoformat(),
           "valid_until": cred.expires_at.isoformat(), "issuer": settings.issuer_id, "key_id": cred.key_id}
    if cred.status == "REVOKED":
        out["revoked_at"] = cred.revoked_at.isoformat()
        out["revocation_reason"] = cred.revocation_reason
    return out
