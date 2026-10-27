"""Selective-disclosure credentials, verification checks, revocation; consent-based verification (Demo C)."""

from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Credential, Enrolment, Student
from app.modules import credentials as creds

STUDENT = "student.ananya@demo.local"


def _ananya():
    with SessionLocal() as s:
        en = s.execute(select(Enrolment).join(Student).where(Student.full_name == "Ananya Iyer")).scalar_one()
        return en.id, en.student.apaar_id, en.student.date_of_birth.isoformat()


def _issue(client, as_):
    eid, *_ = _ananya()
    r = client.post(f"/api/v1/enrolments/{eid}/credentials", headers=as_("kaveri.admin@demo.local"))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _present(client, as_, cid, claims):
    r = client.post(f"/api/v1/me/credentials/{cid}/present", headers=as_(STUDENT), json={"claims": claims})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _verify(client, token):
    r = client.post("/api/v1/verification/verify-token", json={"token": token})
    assert r.status_code == 200
    return r.json()


def checks(res):
    return {c["check"]: c["result"] for c in res["checks"]}


def test_issue_permissions(client, as_):
    eid, *_ = _ananya()
    assert client.post(f"/api/v1/enrolments/{eid}/credentials", headers=as_("kaveri.staff@demo.local")).status_code == 403
    assert client.post(f"/api/v1/enrolments/{eid}/credentials", headers=as_("godavari.admin@demo.local")).status_code == 404


def test_valid_selective_disclosure(client, as_):
    cid = _issue(client, as_)
    token = _present(client, as_, cid, ["institution", "programme", "enrolmentStatus"])
    res = _verify(client, token)
    assert res["valid"] is True and set(checks(res).values()) == {"pass"}
    assert any("does not independently confirm" in note for note in res["notes"])
    assert set(res["claims"]) == {"institution", "programme", "enrolmentStatus"}
    assert "name" not in res["claims"] and "apaarId" not in res["claims"]
    _, apaar, _ = _ananya()
    assert res["apaar_display"] == f"XXXX-XXXX-{apaar[-4:]}" and res["apaar_disclosed"] is False
    full = _verify(client, _present(client, as_, cid, ["apaarId", "name"]))
    assert full["claims"]["apaarId"] == apaar and full["apaar_display"] == apaar
    # header and payload shape
    jws = token.split("~")[0]
    header = __import__("json").loads(creds.b64u_decode(jws.split(".")[0]))
    payload = __import__("json").loads(creds.b64u_decode(jws.split(".")[1]))
    assert header == {"alg": "EdDSA", "typ": "vc+sd-jwt", "kid": creds.issuer_key().kid}
    assert payload["type"] == ["VerifiableCredential", "StudentEnrolmentRecord"] and len(payload["credentialSubject"]["_sd"]) == 8
    assert apaar not in creds.b64u_decode(jws.split(".")[1]).decode()


def test_tampered_payload_and_disclosure(client, as_):
    cid = _issue(client, as_)
    token = _present(client, as_, cid, ["institution", "enrolmentStatus"])
    t1 = client.post("/api/v1/verification/tamper-demo", json={"token": token, "mode": "payload"}).json()["token"]
    r1 = _verify(client, t1)
    assert not r1["valid"] and checks(r1)["signature"] == "fail" and checks(r1)["status"] == "skipped"
    t2 = client.post("/api/v1/verification/tamper-demo", json={"token": token, "mode": "disclosure"}).json()["token"]
    r2 = _verify(client, t2)
    assert not r2["valid"] and checks(r2)["signature"] == "pass" and checks(r2)["disclosures"] == "fail"
    assert "enrolmentStatus" not in r2["claims"]  # altered claim never returned


def test_unknown_key_and_garbage(client, as_):
    other = creds.IssuerKey(Ed25519PrivateKey.generate())
    now = datetime.now(UTC)
    vals = {c: "x" for c in creds.CLAIMS}
    forged = creds.build_token("00000000-0000-0000-0000-000000000000", vals, now, now + timedelta(days=1), key=other)
    r = _verify(client, forged)
    assert checks(r)["key"] == "fail" and not r["valid"]
    for junk in ("hello", "a.b.c~", "~~~", "eyJ.eyJ.sig~bad~"):
        g = _verify(client, junk)
        assert checks(g)["structure"] == "fail" and not g["valid"]


def test_expired(client, as_, db):
    eid, *_ = _ananya()
    en = db.get(Enrolment, eid)
    past = datetime.now(UTC) - timedelta(days=800)
    c = creds.issue(db, en, "test", now=past)
    db.commit()
    tok = creds.present(c, ["institution"])
    r = _verify(client, tok)
    assert checks(r)["validity"] == "fail" and checks(r)["signature"] == "pass"


def test_superseded_and_revoked(client, as_):
    cid1 = _issue(client, as_)
    tok1 = _present(client, as_, cid1, ["institution"])
    cid2 = _issue(client, as_)
    r = _verify(client, tok1)
    assert checks(r)["status"] == "fail" and r["status"] == "SUPERSEDED"
    # revoke: Kaveri admin; Godavari admin cannot see it
    assert client.post(f"/api/v1/credentials/{cid2}/revoke", headers=as_("godavari.admin@demo.local"),
                       json={"reason": "not mine"}).status_code == 404
    rv = client.post(f"/api/v1/credentials/{cid2}/revoke", headers=as_("kaveri.admin@demo.local"),
                     json={"reason": "Issued with wrong programme"})
    assert rv.status_code == 200
    with SessionLocal() as s:
        tok2 = creds.present(s.get(Credential, cid2), ["institution"])
    r = _verify(client, tok2)
    assert r["status"] == "REVOKED" and "Issued with wrong programme" in next(
        c["sentence"] for c in r["checks"] if c["check"] == "status")
    st = client.get(f"/api/v1/verification/credentials/{cid2}").json()
    assert st["status"] == "REVOKED" and st["revocation_reason"] == "Issued with wrong programme"
    jwks = client.get("/.well-known/issuer-keys").json()
    assert jwks["keys"][0]["kid"].startswith("ed25519-") and jwks["keys"][0]["crv"] == "Ed25519"


def test_certificate_and_qr(client, as_):
    cid = _issue(client, as_)
    _, apaar, _ = _ananya()
    r = client.get(f"/api/v1/credentials/{cid}/certificate", headers=as_("kaveri.admin@demo.local"))
    assert r.status_code == 200
    assert "SAMPLE · SYNTHETIC DATA" in r.text and "Institution student ID" in r.text
    assert f"{apaar[:4]} {apaar[4:8]} {apaar[8:]}" in r.text and "<svg" in r.text
    assert client.get(f"/api/v1/credentials/{cid}/certificate", headers=as_("godavari.admin@demo.local")).status_code == 404
    q = client.get(f"/api/v1/credentials/{cid}/qr.svg", headers=as_(STUDENT))
    assert q.status_code == 200 and q.headers["content-type"].startswith("image/svg")


# ---------------------------------------------------------------- consent (Demo C)


def test_consent_flow(client, as_):
    _, apaar, dob = _ananya()
    v = as_("verifier@demo.local")
    ok = client.post("/api/v1/verification/requests", headers=v,
                     json={"apaar_id": apaar, "date_of_birth": dob, "purpose": "Pre-employment check for internship"})
    nomatch = client.post("/api/v1/verification/requests", headers=v,
                          json={"apaar_id": apaar, "date_of_birth": "2001-01-01", "purpose": "Pre-employment check for internship"})
    a, b = ok.json(), nomatch.json()
    strip = lambda d: {k: v_ for k, v_ in d.items() if k not in ("id", "created_at", "expires_at")}  # noqa: E731
    assert ok.status_code == nomatch.status_code == 200 and strip(a) == strip(b)
    assert a["message"] == "If the details match, the student will be asked for consent."
    assert client.get(f"/api/v1/verification/requests/{a['id']}/result", headers=v).status_code == 403
    assert client.get(f"/api/v1/verification/requests/{b['id']}/result", headers=v).status_code == 403
    listed = {r["id"]: r["status"] for r in client.get("/api/v1/verification/requests", headers=v).json()}
    assert listed[a["id"]] == listed[b["id"]] == "PENDING_CONSENT"
    s = as_(STUDENT)
    mine = client.get("/api/v1/verification/requests", headers=s).json()
    assert [r["id"] for r in mine] == [a["id"]] and mine[0]["fields_shared"]
    assert client.post(f"/api/v1/verification/requests/{b['id']}/consent", headers=s,
                       json={"decision": "APPROVE"}).status_code == 404
    assert client.post(f"/api/v1/verification/requests/{a['id']}/consent", headers=s,
                       json={"decision": "APPROVE"}).json()["status"] == "APPROVED"
    res = client.get(f"/api/v1/verification/requests/{a['id']}/result", headers=v)
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"request_id", "name", "apaar_id_masked", "registry_status", "enrolments", "fields_shared"}
    assert body["apaar_id_masked"] == f"XXXX-XXXX-{apaar[-4:]}" and body["registry_status"]["mode"] == "SIMULATED"
    text = res.text
    assert dob not in text and "INDIAN" not in text and "social" not in text and "@" not in text


def test_correction_request_reaches_institution_queue(client, as_):
    eid, *_ = _ananya()
    r = client.post("/api/v1/me/correction-requests", headers=as_(STUDENT),
                    json={"enrolment_id": eid, "field": "full_name", "requested_value": "Ananya S. Iyer",
                          "explanation": "My name on the Class XII certificate includes my initial."})
    assert r.status_code == 200
    q = client.get("/api/v1/correction-requests", headers=as_("kaveri.staff@demo.local")).json()
    assert any(c["id"] == r.json()["id"] for c in q)
    assert all(c["id"] != r.json()["id"] for c in client.get("/api/v1/correction-requests",
                                                              headers=as_("godavari.staff@demo.local")).json())
    acc = client.post(f"/api/v1/correction-requests/{r.json()['id']}/actions", headers=as_("kaveri.staff@demo.local"),
                      json={"action": "ACCEPT", "note": "Will correct"}).json()
    assert acc["status"] == "ACCEPTED" and acc["prefill"]["field"] == "full_name"
