"""Authorization, institution isolation, masking, audit of denials, headers, lockout."""

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditEvent, Enrolment, Student, User

from .conftest import PASSWORD


def _ananya_enrolment():
    with SessionLocal() as s:
        en = s.execute(select(Enrolment).join(Student).where(Student.full_name == "Ananya Iyer")).scalar_one()
        return en.id, en.student.apaar_id


def test_unauthenticated(client, seeded):
    r = client.get("/api/v1/enrolments")
    assert r.status_code == 401
    body = r.json()["error"]
    assert set(body) >= {"status", "message", "request_id"} and "Traceback" not in r.text


def test_cross_institution_detail_is_404(client, as_):
    eid, _ = _ananya_enrolment()
    assert client.get(f"/api/v1/enrolments/{eid}", headers=as_("kaveri.staff@demo.local")).status_code == 200
    assert client.get(f"/api/v1/enrolments/{eid}", headers=as_("godavari.staff@demo.local")).status_code == 404
    r = client.patch(f"/api/v1/enrolments/{eid}", headers=as_("godavari.admin@demo.local"),
                     json={"version": 1, "reason": "trying it", "changes": {"gender": "M"}})
    assert r.status_code == 404
    r = client.post(f"/api/v1/enrolments/{eid}/status", headers=as_("godavari.admin@demo.local"),
                    json={"status": "WITHDRAWN", "reason": "trying it", "version": 1})
    assert r.status_code == 404


def test_cross_institution_list_filter_is_403_and_lists_are_scoped(client, as_):
    h = as_("godavari.staff@demo.local")
    with SessionLocal() as s:
        kaveri_id = s.execute(select(User.institution_id).where(User.email == "kaveri.admin@demo.local")).scalar()
    assert client.get(f"/api/v1/enrolments?institution_id={kaveri_id}", headers=h).status_code == 403
    items = client.get("/api/v1/enrolments?page_size=100", headers=h).json()["items"]
    assert items and all("Godavari" in i["institution_name"] for i in items)
    assert client.get(f"/api/v1/issues?institution_id={kaveri_id}", headers=h).status_code == 403
    assert client.get(f"/api/v1/dashboard/institution?institution_id={kaveri_id}", headers=h).status_code == 403
    rep = client.get("/api/v1/reports/intake-utilisation.csv", headers=h)
    assert rep.status_code == 200 and "Kaveri" not in rep.text and "Godavari" in rep.text


def test_verifier_and_student_blocked_from_records(client, as_):
    for who in ("verifier@demo.local", "student.ananya@demo.local"):
        assert client.get("/api/v1/enrolments", headers=as_(who)).status_code == 403
        assert client.get("/api/v1/dashboard/national", headers=as_(who)).status_code == 403


def test_analyst_sees_masked_apaar_and_no_sensitive_fields(client, as_):
    eid, apaar = _ananya_enrolment()
    a = client.get(f"/api/v1/enrolments/{eid}", headers=as_("aicte.analyst@demo.local")).json()["enrolment"]["student"]
    assert a["apaar_id"] == f"XXXX-XXXX-{apaar[-4:]}" and a["apaar_masked"] is True
    assert a["social_category"] is None and a["email"] is None
    adm = client.get(f"/api/v1/enrolments/{eid}", headers=as_("aicte.admin@demo.local")).json()["enrolment"]["student"]
    assert adm["apaar_id"] == apaar
    own = client.get(f"/api/v1/enrolments/{eid}", headers=as_("kaveri.staff@demo.local")).json()["enrolment"]["student"]
    assert own["apaar_id"] == apaar and own["apaar_check_mode"] == "SIMULATED"


def test_apaar_search_exact_only(client, as_):
    _, apaar = _ananya_enrolment()
    h = as_("aicte.admin@demo.local")
    assert client.get(f"/api/v1/enrolments?q={apaar}", headers=h).json()["total"] == 1
    assert client.get(f"/api/v1/enrolments?q={apaar[:8]}", headers=h).json()["total"] == 0
    assert client.get(f"/api/v1/enrolments?q={apaar[-6:]}", headers=h).json()["total"] == 0


def test_every_403_audited_and_no_raw_apaar_in_audit(client, as_):
    with SessionLocal() as s:
        before = s.execute(select(AuditEvent).where(AuditEvent.outcome == "DENIED")).scalars().all().__len__()
    client.get("/api/v1/audit", headers=as_("kaveri.staff@demo.local"))
    with SessionLocal() as s:
        denied = s.execute(select(AuditEvent).where(AuditEvent.outcome == "DENIED")
                           .order_by(AuditEvent.seq.desc())).scalars().all()
        assert len(denied) == before + 1 and denied[0].detail["path"] == "/api/v1/audit"
        apaars = set(s.execute(select(Student.apaar_id).where(Student.apaar_id.is_not(None))).scalars())
        for ev in s.execute(select(AuditEvent)).scalars():
            text = str(ev.detail) + str(ev.entity_id)
            assert not any(a in text for a in apaars), ev.seq


def test_security_headers(client, seeded):
    r = client.get("/api/health")
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer" and r.headers["cache-control"] == "no-store"


def test_login_lockout_after_five_failures(client, seeded):
    for _ in range(5):
        r = client.post("/api/v1/auth/login", json={"email": "auditor@demo.local", "password": "wrong"})
        assert r.status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": "auditor@demo.local", "password": PASSWORD})
    assert r.status_code == 423
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.email == "auditor@demo.local")).scalar_one()
        u.locked_until = None
        s.commit()
        assert s.execute(select(AuditEvent).where(AuditEvent.action == "auth.login",
                                                  AuditEvent.outcome == "DENIED")).first()


def test_login_rate_limit(client, seeded, monkeypatch):
    from app.config import settings
    from app.security import limiter
    limiter.reset()
    monkeypatch.setattr(settings, "login_rate_per_minute", 3)
    codes = [client.post("/api/v1/auth/login", json={"email": "x@demo.local", "password": "x"}).status_code
             for _ in range(4)]
    assert codes[-1] == 429
    limiter.reset()


def test_password_hash_iterations(seeded):
    with SessionLocal() as s:
        h = s.execute(select(User.password_hash)).scalars().first()
    assert h.startswith("pbkdf2_sha256$") and int(h.split("$")[1]) >= 210_000
