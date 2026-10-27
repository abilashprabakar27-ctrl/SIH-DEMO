"""Record corrections: optimistic locking, revisions, re-validation, status transitions, pending-APAAR."""

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Enrolment, RecordRevision, SimApaarRegistry, Student

from .conftest import upload

STAFF = "kaveri.staff@demo.local"


def _enrol(name):
    with SessionLocal() as s:
        en = s.execute(select(Enrolment).join(Student).where(Student.full_name == name)).scalars().first()
        return en.id, en.version


def test_optimistic_lock_and_revision(client, as_):
    h = as_(STAFF)
    eid, v = _enrol("Ananya Iyer")
    r = client.patch(f"/api/v1/enrolments/{eid}", headers=h,
                     json={"version": v + 5, "reason": "Fix email", "changes": {"email": "ananya@example.org"}})
    assert r.status_code == 409
    r = client.patch(f"/api/v1/enrolments/{eid}", headers=h,
                     json={"version": v, "reason": "Student supplied new email", "changes": {"email": "ananya@example.org"}})
    assert r.status_code == 200, r.text
    with SessionLocal() as s:
        revs = s.execute(select(RecordRevision).where(RecordRevision.reason == "Student supplied new email")).scalars().all()
        assert revs and revs[0].changes["email"]["new"] == "ananya@example.org"
    d = client.get(f"/api/v1/enrolments/{eid}", headers=h).json()
    assert any(h_["reason"] == "Student supplied new email" for h_ in d["history"])


def test_revalidation_rejects_invalid_seat(client, as_):
    h = as_(STAFF)
    eid, v = _enrol("Ananya Iyer")
    v = client.get(f"/api/v1/enrolments/{eid}", headers=h).json()["enrolment"]["version"]
    r = client.patch(f"/api/v1/enrolments/{eid}", headers=h,
                     json={"version": v, "reason": "wrong seat", "changes": {"seat_category": "SN_FN_OCI"}})
    assert r.status_code == 422
    assert any(f["rule_id"] == "R013_CATEGORY_CONSISTENCY" for f in r.json()["error"]["findings"])


def test_status_transitions(client, as_):
    h = as_(STAFF)
    eid, _ = _enrol("Ananya Iyer")
    v = client.get(f"/api/v1/enrolments/{eid}", headers=h).json()["enrolment"]["version"]
    r = client.post(f"/api/v1/enrolments/{eid}/status", headers=h,
                    json={"status": "PROVISIONAL", "reason": "not allowed", "version": v})
    assert r.status_code == 422 and "cannot become" in r.json()["error"]["message"]
    r = client.post(f"/api/v1/enrolments/{eid}/status", headers=h,
                    json={"status": "WITHDRAWN", "reason": "Student withdrew", "version": v})
    assert r.status_code == 200 and r.json()["enrolment"]["status"] == "WITHDRAWN"
    v2 = r.json()["enrolment"]["version"]
    r = client.post(f"/api/v1/enrolments/{eid}/status", headers=h,
                    json={"status": "ACTIVE", "reason": "Student rejoined", "version": v2})
    assert r.status_code == 200 and r.json()["enrolment"]["status"] == "ACTIVE"


def test_pending_apaar_student_later_gets_id_same_record(client, as_):
    h = as_("brahmaputra.staff@demo.local")
    head = ("institution_student_id,full_name,date_of_birth,gender,nationality_status,programme_code,academic_year,"
            "seat_category,admission_date,apaar_id,apaar_pending_reason\n")
    first = head + "BPE26PEND1,Gowri Shankar,2008-02-02,F,INDIAN,BTECH-CIVIL,2026-27,REGULAR,2026-08-10,,APPLIED_AWAITING_ID\n"
    j = upload(client, h, None, name="p1.csv", content=first.encode()).json()
    assert client.post(f"/api/v1/imports/{j['id']}/commit", headers=h).json()["committed_now"] == 1
    with SessionLocal() as s:
        s.add(SimApaarRegistry(apaar_id="955500000001", full_name="Gowri Shankar",
                               date_of_birth=__import__("datetime").date(2008, 2, 2)))
        s.commit()
        before = s.execute(select(Student).where(Student.full_name == "Gowri Shankar")).scalars().all()
        assert len(before) == 1 and before[0].apaar_id is None and before[0].apaar_status == "PENDING_EXEMPT"
    second = head + "BPE26PEND1,Gowri Shankar,2008-02-02,F,INDIAN,BTECH-CIVIL,2026-27,REGULAR,2026-08-10,955500000001,\n"
    j2 = upload(client, h, None, name="p2.csv", content=second.encode()).json()
    assert j2["summary"]["counts"]["ERROR"] == 0, j2
    assert client.post(f"/api/v1/imports/{j2['id']}/commit", headers=h).json()["committed_now"] == 1
    with SessionLocal() as s:
        after = s.execute(select(Student).where(Student.full_name == "Gowri Shankar")).scalars().all()
        assert len(after) == 1 and after[0].apaar_id == "955500000001" and after[0].apaar_status == "VERIFIED"
        assert after[0].id == before[0].id
        assert s.execute(select(RecordRevision).where(RecordRevision.entity_id == after[0].id,
                                                      RecordRevision.version == 2)).scalar_one()


def test_manual_entry_requires_acknowledgement_for_review(client, as_):
    h = as_("brahmaputra.staff@demo.local")
    rec = {"institution_student_id": "BPE26MAN1", "full_name": "Selvi Arumugam", "date_of_birth": "2008-03-03",
           "gender": "F", "nationality_status": "INDIAN", "programme_code": "BTECH-CIVIL", "academic_year": "2026-27",
           "seat_category": "REGULAR", "admission_date": "2026-08-12", "apaar_pending_reason": "APPLIED_AWAITING_ID"}
    r = client.post("/api/v1/enrolments", headers=h, json={"record": rec})
    assert r.status_code == 422 and r.json()["error"]["needs_acknowledgement"] is True
    r = client.post("/api/v1/enrolments", headers=h, json={"record": rec, "acknowledge_review": True})
    assert r.status_code == 200 and r.json()["enrolment"]["source"] == "MANUAL"
    r = client.post("/api/v1/enrolments", headers=h, json={"record": dict(rec, gender="Q")})
    assert r.status_code == 422 and r.json()["error"]["row_status"] == "ERROR"
