"""Demo B: cross-institution conflict with privacy redaction, excess intake, review workflow, auto-resolve."""

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Enrolment, IssueEvent, Student, ValidationIssue

from .conftest import SAMPLES, rows_by_roll, upload

AICTE = "aicte.admin@demo.local"


def test_demo_b(client, as_):
    g = as_("godavari.admin@demo.local")
    r = client.post("/api/v1/seat-check", headers=g,
                    json={"programme_code": "BTECH-CSE", "seat_category": "REGULAR", "count": 1})
    assert "exceed approved intake by 1" in r.json()["message"]
    job = upload(client, g, SAMPLES / "demo_B_godavari_upload_2026-27.csv").json()
    proj = job["summary"]["projection"][0]
    assert proj["change_within_intake"] == 4 and proj["exceeds"]
    assert "exceed approved capacity" in proj["message"]
    rows = rows_by_roll(client, g, job["id"])
    assert {f["rule_id"] for f in rows["GEC26CSE904"]["findings"]} >= {"D003_XINST_ACTIVE", "D004_ATTR_CONFLICT"}
    r = client.post(f"/api/v1/imports/{job['id']}/commit", headers=g).json()
    assert r["committed_now"] == 5

    a = as_(AICTE)
    flags = client.get("/api/v1/issues?status=OPEN", headers=a).json()["items"]
    c001 = [f for f in flags if f["rule_id"] == "C001_EXCESS_INTAKE" and f["evidence"]["programme_code"] == "BTECH-CSE"
            and "Godavari" in (f["institution_name"] or "")]
    assert c001 and c001[0]["evidence"]["excess"] == 4
    c002 = [f for f in flags if f["rule_id"] == "C002_SUPERNUMERARY_CAP" and "Godavari" in (f["institution_name"] or "")]
    assert c002 and c002[0]["evidence"]["position"]["supernumerary"]["SN_TFW"] == {"enrolled": 7, "cap": 6, "excess": 1}
    d003 = next(f for f in flags if f["rule_id"] == "D003_XINST_ACTIVE" and "Godavari" in (f["institution_name"] or ""))
    assert {s["institution_name"] for s in d003["evidence"]["sides"]} >= {"Godavari Engineering College (Synthetic)",
                                                                         "Kaveri Institute of Technology (Synthetic)"}
    # Godavari sees the other side withheld
    gv = client.get(f"/api/v1/issues/{d003['id']}", headers=g).json()
    other = [s for s in gv["evidence"]["sides"] if not s["own"]]
    assert other and other[0]["institution"] == "Another AICTE-approved institution (identity withheld)"
    assert "Kaveri" not in str(gv)
    # Kaveri sees it too, with Godavari withheld
    k = as_("kaveri.admin@demo.local")
    kv = client.get(f"/api/v1/issues/{d003['id']}", headers=k).json()
    assert "Godavari" not in str(kv)
    # Brahmaputra cannot see it at all
    assert client.get(f"/api/v1/issues/{d003['id']}", headers=as_("brahmaputra.admin@demo.local")).status_code == 404

    # workflow: clarification -> Kaveri transfers out -> Godavari responds -> AICTE resolves
    assert client.post(f"/api/v1/issues/{d003['id']}/actions", headers=a,
                       json={"action": "REQUEST_CLARIFICATION", "note": "Which institution is the student attending?"}
                       ).json()["status"] == "CLARIFICATION_REQUESTED"
    # institutions cannot resolve cross-institution flags
    assert client.post(f"/api/v1/issues/{d003['id']}/actions", headers=g,
                       json={"action": "RESOLVE", "note": "trying"}).status_code == 403
    kaveri_side = next(s for s in kv["evidence"]["sides"] if s["own"])
    det = client.get(f"/api/v1/enrolments/{kaveri_side['enrolment_id']}", headers=k).json()["enrolment"]
    r = client.post(f"/api/v1/enrolments/{det['id']}/status", headers=k,
                    json={"status": "TRANSFERRED_OUT", "reason": "Student moved to another institution", "version": det["version"]})
    assert r.status_code == 200
    assert client.post(f"/api/v1/issues/{d003['id']}/actions", headers=g,
                       json={"action": "RESPOND", "note": "Student joined us on 1 Sep; previous institution recorded transfer."}
                       ).json()["status"] == "RESPONDED"
    res = client.post(f"/api/v1/issues/{d003['id']}/actions", headers=a,
                      json={"action": "RESOLVE", "note": "Transfer confirmed by both sides."}).json()
    assert res["status"] == "RESOLVED" and [h["action"] for h in res["history"]][-1] == "RESOLVE"

    # Godavari cancels 4 admissions -> C001 clears with a logged system event
    new = ["GEC26CSE901", "GEC26CSE902", "GEC26CSE903"]
    with SessionLocal() as s:
        extra = s.execute(select(Enrolment).where(Enrolment.institution_student_id.like("GEC26BTECHCSE%"),
                                                  Enrolment.seat_category == "REGULAR")).scalars().first()
        ids = [s.execute(select(Enrolment.id).where(Enrolment.institution_student_id == r_)).scalar() for r_ in new]
        ids.append(extra.id)
    for eid in ids:
        v = client.get(f"/api/v1/enrolments/{eid}", headers=g).json()["enrolment"]["version"]
        assert client.post(f"/api/v1/enrolments/{eid}/status", headers=g,
                           json={"status": "CANCELLED", "reason": "Duplicate provisional admission", "version": v}
                           ).status_code == 200
    with SessionLocal() as s:
        issue = s.get(ValidationIssue, c001[0]["id"])
        assert issue.status == "RESOLVED" and issue.resolved_by is None
        evs = [e.action for e in s.execute(select(IssueEvent).where(IssueEvent.issue_id == issue.id)).scalars()]
        assert "SYSTEM_AUTO_RESOLVED" in evs
    # reopenable by AICTE
    r = client.post(f"/api/v1/issues/{c001[0]['id']}/actions", headers=a, json={"action": "REOPEN", "note": "Re-check"})
    assert r.json()["status"] == "OPEN"
    # no "fraud" anywhere in flags
    assert "fraud" not in client.get("/api/v1/issues?page_size=200", headers=a).text.lower()
    _ = Student
