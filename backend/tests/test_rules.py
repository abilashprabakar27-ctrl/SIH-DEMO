"""Every validation rule: one positive and one negative case (engine.validate_rows)."""

import pytest
from sqlalchemy import select

from app.models import Enrolment, Institution, Student, ValidationRule
from app.modules import engine
from app.modules.apaar_adapter import SimulatedRegistryAdapter, near_variants, set_adapter
from app.modules.rules import CATALOGUE

# Meenakshi Sundaram is in the synthetic registry but not yet in the register.
BASE = {
    "apaar_id": "911100000001", "institution_student_id": "KIT26T001", "full_name": "Meenakshi Sundaram",
    "date_of_birth": "2008-05-12", "gender": "F", "nationality_status": "INDIAN", "citizenship_country": "India",
    "programme_code": "BTECH-CSE", "academic_year": "2026-27", "seat_category": "REGULAR",
    "admission_date": "2026-08-03",
}


@pytest.fixture
def kaveri(db):
    return db.execute(select(Institution).where(Institution.short_name == "kaveri")).scalar_one()


def check(db, inst, *rows, year="2026-27"):
    return engine.validate_rows(db, inst, year, list(enumerate(rows)))


def rules(plan):
    return {f["rule_id"] for f in plan.findings}


def test_catalogue_has_25_rules(db):
    assert len(CATALOGUE) == 25
    assert db.execute(select(ValidationRule)).scalars().all().__len__() == 25


def test_base_row_is_valid(db, kaveri):
    p = check(db, kaveri, BASE)[0]
    assert p.status == "VALID" and p.findings == [] and p.adapter_status == "OK"


def test_r001_required(db, kaveri):
    p = check(db, kaveri, dict(BASE, full_name=""))[0]
    assert "R001_REQUIRED" in rules(p) and p.status == "ERROR"
    assert "R001_REQUIRED" not in rules(check(db, kaveri, dict(BASE, email=""))[0])  # optional column


@pytest.mark.parametrize("field,value", [("date_of_birth", "31-31-2008"), ("gender", "X"),
                                         ("email", "not-an-email"), ("academic_year", "2026-28"),
                                         ("seat_category", "GENERAL")])
def test_r002_format(db, kaveri, field, value):
    assert "R002_FORMAT" in rules(check(db, kaveri, dict(BASE, **{field: value}))[0])


def test_r002_accepts_alternate_date_formats_and_aliases(db, kaveri):
    row = dict(BASE)
    row.pop("date_of_birth")
    row.pop("institution_student_id")
    row["dob"] = "12/05/2008"
    row["roll_no"] = "KIT26T001"
    p = check(db, kaveri, row)[0]
    assert p.status == "VALID", p.findings
    assert check(db, kaveri, dict(BASE, date_of_birth="12-05-2008"))[0].status == "VALID"


def test_r003_missing_apaar(db, kaveri):
    assert "R003_APAAR_MISSING" in rules(check(db, kaveri, dict(BASE, apaar_id=""))[0])
    assert "R003_APAAR_MISSING" not in rules(check(db, kaveri, BASE)[0])


def test_r004_pending_and_foreign_national_only_for_fn_oci(db, kaveri):
    p = check(db, kaveri, dict(BASE, apaar_id="", apaar_pending_reason="APPLIED_AWAITING_ID"))[0]
    assert rules(p) == {"R004_APAAR_PENDING"} and p.status == "REVIEW"
    p = check(db, kaveri, dict(BASE, apaar_id="", apaar_pending_reason="FOREIGN_NATIONAL"))[0]
    assert "R013_CATEGORY_CONSISTENCY" in rules(p)
    assert "R004_APAAR_PENDING" not in rules(check(db, kaveri, BASE)[0])


@pytest.mark.parametrize("value", ["91110000007", "9111000000011", "999999999999", "91110000000A"])
def test_r005_format(db, kaveri, value):
    p = check(db, kaveri, dict(BASE, apaar_id=value))[0]
    assert "R005_APAAR_FORMAT" in rules(p)
    assert p.adapter_status is None  # adapter not called for malformed IDs


def test_r005_accepts_spaced_id(db, kaveri):
    assert check(db, kaveri, dict(BASE, apaar_id="9111 0000 0001"))[0].status == "VALID"


def test_r006_not_found_and_did_you_mean(db, kaveri):
    row = dict(BASE, apaar_id="911100000098", full_name="Sanjana Balaji", date_of_birth="2008-06-05")
    p = check(db, kaveri, row)[0]
    f = next(f for f in p.findings if f["rule_id"] == "R006_APAAR_NOT_FOUND")
    assert f["suggestion"] == {"field": "apaar_id", "value": "911100000008", "reason": "matches name and date of birth"}
    assert f["evidence"]["mode"] == "SIMULATED" and "SIMULATED" in f["message"]
    assert "R006_APAAR_NOT_FOUND" not in rules(check(db, kaveri, BASE)[0])


def test_did_you_mean_none_when_two_variants_match(db, kaveri):
    from datetime import date

    from app.models import SimApaarRegistry
    # Two near-variants registered with the same name and DOB -> ambiguous -> no suggestion
    db.add(SimApaarRegistry(apaar_id="911100000088", full_name="Sanjana Balaji", date_of_birth=date(2008, 6, 5)))
    db.flush()
    row = dict(BASE, apaar_id="911100000098", full_name="Sanjana Balaji", date_of_birth="2008-06-05")
    f = next(f for f in check(db, kaveri, row)[0].findings if f["rule_id"] == "R006_APAAR_NOT_FOUND")
    assert "suggestion" not in f


def test_near_variants_count():
    v = near_variants("911100000098")
    assert len([x for x in v]) == 108 + sum(1 for i in range(11) if "911100000098"[i] != "911100000098"[i + 1])
    assert len(near_variants("123456789012")) == 108 + 11


def test_r007_mismatch(db, kaveri):
    p = check(db, kaveri, dict(BASE, full_name="Meenakshi Sundharam"))[0]
    assert "R007_APAAR_MISMATCH" in rules(p) and p.status == "REVIEW"
    p = check(db, kaveri, dict(BASE, date_of_birth="2008-05-13"))[0]
    assert "R007_APAAR_MISMATCH" in rules(p)
    assert "R007_APAAR_MISMATCH" not in rules(check(db, kaveri, BASE)[0])


def test_r008_adapter_unavailable_is_warning(db, kaveri):
    set_adapter(SimulatedRegistryAdapter(available=False))
    try:
        p = check(db, kaveri, BASE)[0]
    finally:
        set_adapter(None)
    f = next(f for f in p.findings if f["rule_id"] == "R008_APAAR_UNVERIFIED")
    assert p.status == "WARNING" and f["severity"] == "WARNING" and f["evidence"]["mode"] == "SIMULATED"
    assert engine._apaar_status(p) == "UNVERIFIED"


def test_r009_duplicate_enrolment(db, kaveri):
    st = db.execute(select(Student).where(Student.full_name == "Ananya Iyer")).scalar_one()
    row = dict(BASE, apaar_id=st.apaar_id, full_name=st.full_name, date_of_birth=st.date_of_birth.isoformat(),
               institution_student_id="KIT26NEWROLL")
    assert "R009_DUPLICATE_ENROLMENT" in rules(check(db, kaveri, row)[0])
    assert "R009_DUPLICATE_ENROLMENT" not in rules(check(db, kaveri, BASE)[0])


def test_r010_date_logic(db, kaveri):
    assert "R010_DATE_LOGIC" in rules(check(db, kaveri, dict(BASE, date_of_birth="2028-06-18"))[0])
    assert "R010_DATE_LOGIC" in rules(check(db, kaveri, dict(BASE, admission_date="2026-12-01"))[0])
    assert "R010_DATE_LOGIC" in rules(check(db, kaveri, dict(BASE, date_of_birth="2013-01-01"))[0])  # age 13
    assert "R010_DATE_LOGIC" not in rules(check(db, kaveri, BASE)[0])


def test_r011_unusual(db, kaveri):
    p = check(db, kaveri, dict(BASE, admission_date="2026-04-20"))[0]
    assert "R011_DATE_UNUSUAL" in rules(p)
    assert "R011_DATE_UNUSUAL" in rules(check(db, kaveri, dict(BASE, date_of_birth="1975-01-01"))[0])
    assert "R011_DATE_UNUSUAL" not in rules(check(db, kaveri, BASE)[0])


def test_r012_programme(db, kaveri):
    assert "R012_PROGRAMME" in rules(check(db, kaveri, dict(BASE, programme_code="MTECH-AI"))[0])
    assert "R012_PROGRAMME" in rules(check(db, kaveri, dict(BASE, programme_code="MCA"))[0])  # Narmada's
    p = check(db, kaveri, dict(BASE, academic_year="2027-28"), year="2027-28")[0]
    assert "R012_PROGRAMME" in rules(p)  # no approved intake for that year
    assert "R012_PROGRAMME" not in rules(check(db, kaveri, BASE)[0])


@pytest.mark.parametrize("over", [
    {"seat_category": "SN_FN_OCI"},
    {"seat_category": "NRI"},
    {"seat_category": "SN_CIWG", "nationality_status": "OCI", "citizenship_country": "France"},
    {"nationality_status": "FN", "citizenship_country": "India"},
    {"citizenship_country": "France"},
])
def test_r013_consistency(db, kaveri, over):
    assert "R013_CATEGORY_CONSISTENCY" in rules(check(db, kaveri, dict(BASE, **over))[0])


def test_r013_negative(db, kaveri):
    ok = dict(BASE, seat_category="SN_FN_OCI", nationality_status="OCI", citizenship_country="France")
    assert "R013_CATEGORY_CONSISTENCY" not in rules(check(db, kaveri, ok)[0])
    assert "R013_CATEGORY_CONSISTENCY" not in rules(check(db, kaveri, dict(BASE, nationality_status="PIO",
                                                                           citizenship_country="UK"))[0])


def test_r014_year_mismatch(db, kaveri):
    assert "R014_YEAR_MISMATCH" in rules(check(db, kaveri, dict(BASE, academic_year="2025-26"))[0])
    assert "R014_YEAR_MISMATCH" not in rules(check(db, kaveri, BASE)[0])


def test_f001_f002_f003(db, kaveri):
    a = dict(BASE)
    b = dict(BASE, institution_student_id="KIT26T002")
    p = check(db, kaveri, a, b)
    assert all("F001_DUP_APAAR_IN_FILE" in rules(x) for x in p)
    assert p[0].findings[0]["evidence"]["other_rows"] == [3] and p[1].findings[0]["evidence"]["other_rows"] == [2]
    p = check(db, kaveri, a, dict(BASE, apaar_id="911100000002", full_name="Karthik Narayanan",
                                 date_of_birth="2008-01-23", gender="M"))
    assert all("F002_DUP_ROLL_IN_FILE" in rules(x) for x in p)
    p = check(db, kaveri, a, dict(BASE, apaar_id="911100000002", institution_student_id="KIT26T002"))
    assert all("F003_POSSIBLE_DUP_IN_FILE" in rules(x) for x in p)
    p = check(db, kaveri, a, dict(BASE, apaar_id="911100000002", full_name="Karthik Narayanan",
                                 date_of_birth="2008-01-23", gender="M", institution_student_id="KIT26T002"))
    assert not any(rules(x) for x in p)


def test_d001_existing_and_d002_roll_conflict(db, kaveri):
    en = db.execute(select(Enrolment).join(Student).where(Student.full_name == "Ananya Iyer")).scalar_one()
    st = en.student
    same = dict(BASE, apaar_id=st.apaar_id, full_name=st.full_name, date_of_birth=st.date_of_birth.isoformat(),
                institution_student_id=en.institution_student_id)
    p = check(db, kaveri, same)[0]
    assert rules(p) == {"D001_EXISTING_RECORD"} and p.status == "WARNING"
    p = check(db, kaveri, dict(BASE, institution_student_id=en.institution_student_id))[0]
    f = next(f for f in p.findings if f["rule_id"] == "D002_ROLL_CONFLICT")
    assert f["evidence"]["enrolment_id"] == en.id and p.status == "ERROR"
    assert "D002_ROLL_CONFLICT" not in rules(check(db, kaveri, BASE)[0])


def test_d003_and_d004(db):
    godavari = db.execute(select(Institution).where(Institution.short_name == "godavari")).scalar_one()
    en = db.execute(select(Enrolment).join(Student).where(Student.full_name == "Ananya Iyer")).scalar_one()
    st = en.student
    row = dict(BASE, apaar_id=st.apaar_id, full_name="Ananya Iyar", date_of_birth=st.date_of_birth.isoformat(),
               institution_student_id="GEC26X1")
    p = check(db, godavari, row)[0]
    assert {"D003_XINST_ACTIVE", "D004_ATTR_CONFLICT"} <= rules(p) and p.status == "REVIEW"
    assert "D003_XINST_ACTIVE" not in rules(check(db, godavari, dict(BASE, institution_student_id="GEC26X2"))[0])


def test_repository_rules_skipped_on_gating_errors(db, kaveri):
    en = db.execute(select(Enrolment).join(Student).where(Student.full_name == "Ananya Iyer")).scalar_one()
    p = check(db, kaveri, dict(BASE, institution_student_id=en.institution_student_id, programme_code="NOPE"))[0]
    assert "R012_PROGRAMME" in rules(p) and "D002_ROLL_CONFLICT" not in rules(p)


def test_disabled_rule_and_severity_change(db, kaveri):
    rule = db.get(ValidationRule, "R011_DATE_UNUSUAL")
    rule.enabled = False
    db.flush()
    assert "R011_DATE_UNUSUAL" not in rules(check(db, kaveri, dict(BASE, admission_date="2026-04-20"))[0])
    rule.enabled, rule.severity = True, "REVIEW"
    db.flush()
    assert check(db, kaveri, dict(BASE, admission_date="2026-04-20"))[0].status == "REVIEW"


def test_findings_shape(db, kaveri):
    f = check(db, kaveri, dict(BASE, gender="X"))[0].findings[0]
    assert set(f) >= {"rule_id", "severity", "field", "message", "evidence"}
