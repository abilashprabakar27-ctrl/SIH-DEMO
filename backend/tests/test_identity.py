"""Indian-name-aware identity resolution."""

from datetime import date

from sqlalchemy import select

from app.models import IdentityCandidate, Institution, Student
from app.modules import engine, identity
from app.modules.identity import jaro_winkler, phonetic_fold, score_pair
from app.modules.normalize import name_key


def test_name_key_and_fold():
    assert name_key("  Sanjana  BALAJI ") == "balaji sanjana"
    assert name_key("Balaji, Sanjana") == "balaji sanjana"
    assert name_key("श्री राम")
    assert phonetic_fold("mohammed") == phonetic_fold("mohamed")
    assert phonetic_fold("karthik") == phonetic_fold("kartik")
    assert phonetic_fold("deepa") == phonetic_fold("dipa")
    assert jaro_winkler("subramaniam", "subramanian") >= 0.92


def test_vignesh_spelling_variant_scores_review():
    s, w = score_pair(
        {"full_name": "Vignesh Subramaniam", "date_of_birth": date(2008, 3, 27), "gender": "M", "apaar_id": None},
        {"full_name": "Vignesh Subramanian", "date_of_birth": date(2008, 3, 27), "gender": "M", "apaar_id": "911100000009"},
    )
    assert s >= 9 and s == 9.5
    assert {x["factor"] for x in w} >= {"Same date of birth", "Same gender"}


def test_initials_listed_band():
    s, _ = score_pair({"full_name": "K. Anil Rao", "date_of_birth": date(2008, 7, 11), "gender": "M"},
                      {"full_name": "Anil Kumar Rao", "date_of_birth": date(2008, 7, 11), "gender": "M"})
    assert 6 <= s < 9


def test_gender_disagree_and_swapped_dob():
    s, w = score_pair({"full_name": "Riya Sharma", "date_of_birth": date(2008, 3, 4), "gender": "F"},
                      {"full_name": "Riya Sharma", "date_of_birth": date(2008, 4, 3), "gender": "M"})
    assert s == 6 + 1.5 - 3
    assert any("swapped" in x["factor"] for x in w)


def test_d005_flag_with_weights_and_different_dob_no_candidate(db):
    kaveri = db.execute(select(Institution).where(Institution.short_name == "kaveri")).scalar_one()
    db.add(Student(apaar_id="911100000009", apaar_ref="x", apaar_status="VERIFIED", full_name="Vignesh Subramanian",
                   name_key=name_key("Vignesh Subramanian"), date_of_birth=date(2008, 3, 27), gender="M",
                   nationality_status="INDIAN"))
    db.flush()
    row = {"apaar_id": "", "apaar_pending_reason": "APPLIED_AWAITING_ID", "institution_student_id": "KIT26ID1",
           "full_name": "Vignesh Subramaniam", "date_of_birth": "2008-03-27", "gender": "M",
           "nationality_status": "INDIAN", "programme_code": "BTECH-ECE", "academic_year": "2026-27",
           "seat_category": "REGULAR", "admission_date": "2026-08-03"}
    p = engine.validate_rows(db, kaveri, "2026-27", [(0, row)])[0]
    f = next(f for f in p.findings if f["rule_id"] == "D005_POSSIBLE_DUP_IDENTITY")
    assert f["evidence"]["score"] >= 9 and f["evidence"]["weights"]
    p2 = engine.validate_rows(db, kaveri, "2026-27", [(0, dict(row, date_of_birth="2008-09-15"))])[0]
    assert "D005_POSSIBLE_DUP_IDENTITY" not in {x["rule_id"] for x in p2.findings}
    assert not identity.find_candidates(db, "Vignesh Subramaniam", date(2008, 9, 15), "M", None)


def test_seeded_candidates(client, as_, db):
    pairs = db.execute(select(IdentityCandidate)).scalars().all()
    assert pairs, "seed plants identity candidates"
    r = client.get("/api/v1/identity/candidates", headers=as_("aicte.admin@demo.local"))
    assert r.status_code == 200
    items = r.json()
    names = {(i["a"]["student"]["full_name"], i["b"]["student"]["full_name"]) for i in items}
    flat = {n for pair in names for n in pair}
    assert {"K. Anil Rao", "Anil Kumar Rao", "Mohammed Farook", "Mohamed Farooq"} <= flat
    farook = next(i for i in items if {"Mohammed Farook", "Mohamed Farooq"} == {i["a"]["student"]["full_name"],
                                                                                  i["b"]["student"]["full_name"]})
    assert farook["band"] == "REVIEW" and farook["weights"]
    anil = next(i for i in items if "K. Anil Rao" in (i["a"]["student"]["full_name"], i["b"]["student"]["full_name"]))
    assert anil["band"] == "LISTED"
    # decision: never auto-merged; DIFFERENT_PEOPLE dismisses the D005 flag
    r = client.post(f"/api/v1/identity/candidates/{farook['id']}/decision", headers=as_("aicte.admin@demo.local"),
                    json={"decision": "DIFFERENT_PEOPLE", "note": "Different fathers' names on file"})
    assert r.status_code == 200
    flags = client.get("/api/v1/issues?rule_id=D005_POSSIBLE_DUP_IDENTITY",
                       headers=as_("aicte.admin@demo.local")).json()["items"]
    assert all(f["status"] == "DISMISSED" for f in flags)
    # analysts can view but not decide
    r = client.post(f"/api/v1/identity/candidates/{anil['id']}/decision", headers=as_("aicte.analyst@demo.local"),
                    json={"decision": "SAME_PERSON", "note": "x" * 5})
    assert r.status_code == 403
