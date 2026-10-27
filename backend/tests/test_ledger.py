"""Seat-counting rules (BUILD_PROMPT §3) and seat-check advice."""

import pytest
from sqlalchemy import select

from app.models import Enrolment, Institution, Programme
from app.modules import ledger
from app.modules.ledger import default_caps, position_from_counts, seat_check

CAPS = {"SN_FN_OCI": 6, "SN_CIWG": 3, "SN_TFW": 3, "SN_OTHER": 0}


def pos(**counts):
    return position_from_counts(60, CAPS, counts)


def test_zero_enrolled():
    p = pos()
    assert p["within_intake_enrolled"] == 0 and p["excess_over_intake"] == 0
    assert p["vacant_within_intake"] == 60 and p["utilisation_pct"] == 0.0 and not p["any_excess"]


def test_exactly_intake_is_not_excess():
    p = pos(REGULAR=60)
    assert p["excess_over_intake"] == 0 and p["vacant_within_intake"] == 0 and not p["any_excess"]


def test_intake_plus_one_is_excess():
    p = pos(REGULAR=61)
    assert p["excess_over_intake"] == 1 and p["any_excess"]


def test_nri_counts_against_intake():
    p = pos(REGULAR=58, NRI=3)
    assert p["within_intake_enrolled"] == 61 and p["excess_over_intake"] == 1 and p["nri"] == 3


def test_supernumerary_not_counted_against_intake():
    p = pos(REGULAR=60, SN_FN_OCI=6, SN_TFW=3)
    assert p["excess_over_intake"] == 0 and p["supernumerary_enrolled"] == 9 and p["total_enrolled"] == 69
    assert not p["any_excess"]


@pytest.mark.parametrize("cat,cap", [("SN_FN_OCI", 6), ("SN_CIWG", 3), ("SN_TFW", 3), ("SN_OTHER", 0)])
def test_cap_and_cap_plus_one(cat, cap):
    at = pos(**{cat: cap})
    assert at["supernumerary"][cat]["excess"] == 0 and not at["any_excess"]
    over = pos(**{cat: cap + 1})
    assert over["supernumerary"][cat]["excess"] == 1 and over["any_excess"]


def test_unused_supernumerary_not_transferable():
    # TFW over cap by 2 while FN/OCI has 6 unused seats: still excess, nothing transferred
    p = pos(SN_TFW=5)
    assert p["supernumerary"]["SN_TFW"]["excess"] == 2
    assert p["supernumerary"]["SN_FN_OCI"]["excess"] == 0 and p["any_excess"]
    # supernumerary vacancies never absorb within-intake excess either
    assert pos(REGULAR=61)["excess_over_intake"] == 1


def test_utilisation_none_when_intake_zero():
    assert position_from_counts(0, {}, {})["utilisation_pct"] is None


@pytest.mark.parametrize("intake,disc,level,fn,ciwg,tfw", [
    (60, "ENGINEERING", "UG", 6, 3, 3),
    (60, "MANAGEMENT", "PG", 10, 5, 3),
    (10, "ENGINEERING", "UG", 1, 0, 0),
    (60, "ENGINEERING", "PG", 10, 5, 3),
    (60, "ENGINEERING", "DIPLOMA", 6, 3, 3),
])
def test_default_caps_rounding(intake, disc, level, fn, ciwg, tfw):
    c = default_caps(intake, disc, level)
    assert (c["SN_FN_OCI"]["cap_seats"], c["SN_CIWG"]["cap_seats"], c["SN_TFW"]["cap_seats"]) == (fn, ciwg, tfw)
    assert c["SN_OTHER"]["cap_seats"] == 0
    assert all(v["rule_source"] for v in c.values())


def test_seeded_versioned_rules_use_integer_caps(db):
    from app.models import CapacityRuleSet
    from app.modules.capacity_rules import caps_from_rule_set, resolve_rule_set

    rules = resolve_rule_set(db, "2026-27")
    assert rules is not None and rules.verification_status == "UNVERIFIED"
    assert rules.source_type == "SECONDARY"
    assert len(db.execute(select(CapacityRuleSet)).scalars().all()) == 2
    engineering = caps_from_rule_set(db, rules, 60, "ENGINEERING", "UG")
    management = caps_from_rule_set(db, rules, 60, "MANAGEMENT", "PG")
    small = caps_from_rule_set(db, rules, 10, "ENGINEERING", "UG")
    assert [engineering[k]["cap_seats"] for k in ("SN_FN_OCI", "SN_CIWG", "SN_TFW")] == [6, 3, 3]
    assert [management[k]["cap_seats"] for k in ("SN_FN_OCI", "SN_CIWG", "SN_TFW")] == [10, 5, 3]
    assert [small[k]["cap_seats"] for k in ("SN_FN_OCI", "SN_CIWG", "SN_TFW")] == [1, 0, 0]


def test_rule_set_impact_and_activation_are_audited(client, as_, db):
    from sqlalchemy import select

    from app.models import AuditEvent, CapacityRuleSet, SupernumeraryQuota

    h = as_("aicte.admin@demo.local")
    draft = db.execute(select(CapacityRuleSet).where(CapacityRuleSet.status == "DRAFT")).scalar_one()
    impact = client.post(f"/api/v1/rule-sets/{draft.id}/impact", headers=h)
    assert impact.status_code == 200, impact.text
    assert impact.json()["programmes"]
    response = client.post(f"/api/v1/rule-sets/{draft.id}/activate", headers=h,
                           json={"reason": "Exercise the documented draft rule set in a test."})
    assert response.status_code == 200, response.text
    db.refresh(draft)
    assert draft.status == "ACTIVE"
    assert db.execute(select(SupernumeraryQuota).where(SupernumeraryQuota.rule_set_id == draft.id)).first()
    assert db.execute(select(AuditEvent).where(AuditEvent.action == "capacity_rules.activated")).first()


def test_withdrawn_not_counted_db(db):
    inst = db.execute(select(Institution).where(Institution.short_name == "kaveri")).scalar_one()
    prog = db.execute(select(Programme).where(Programme.institution_id == inst.id,
                                              Programme.code == "BTECH-CSE")).scalar_one()
    before = ledger.position(db, prog.id, "2026-27")
    en = db.execute(select(Enrolment).where(Enrolment.programme_id == prog.id, Enrolment.academic_year == "2026-27",
                                            Enrolment.seat_category == "REGULAR")).scalars().first()
    en.status = "WITHDRAWN"
    db.flush()
    after = ledger.position(db, prog.id, "2026-27")
    assert after["regular"] == before["regular"] - 1
    assert before["regular"] == 50 and before["nri"] == 3  # seeded Kaveri CSE


# ---------------------------------------------------------------- seat-check advice


def test_seat_check_pure_boundaries():
    assert seat_check(pos(REGULAR=58), "REGULAR", 1)["allowed_within_rules"]          # intake-2 -> intake-1
    assert seat_check(pos(REGULAR=59), "REGULAR", 1)["allowed_within_rules"]          # -> exactly intake
    r = seat_check(pos(REGULAR=60), "REGULAR", 1)                                      # -> intake+1
    assert not r["allowed_within_rules"] and "exceed approved intake by 1" in r["message"]
    assert r["counts_against"] == "approved intake"
    c = seat_check(pos(SN_TFW=3), "SN_TFW", 1)
    assert not c["allowed_within_rules"] and c["counts_against"] == "SN_TFW cap" and c["category"]["after"] == 4
    assert seat_check(pos(SN_TFW=2), "SN_TFW", 1)["allowed_within_rules"]
    # supernumerary admission never touches within-intake
    assert seat_check(pos(REGULAR=60), "SN_FN_OCI", 1)["allowed_within_rules"]


def test_seat_check_api(client, as_):
    h = as_("godavari.admin@demo.local")
    r = client.post("/api/v1/seat-check", headers=h,
                    json={"programme_code": "BTECH-CSE", "academic_year": "2026-27", "seat_category": "REGULAR", "count": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["allowed_within_rules"] is False
    assert body["within_intake"] == {"approved": 120, "occupied": 120, "after": 121}
    assert "exceed approved intake by 1" in body["message"]
    r = client.post("/api/v1/seat-check", headers=h,
                    json={"programme_code": "BTECH-CSE", "seat_category": "SN_TFW", "count": 1})
    assert r.json()["category"] == {"cap": 6, "occupied": 6, "after": 7}
    r = client.post("/api/v1/seat-check", headers=h,
                    json={"programme_code": "BTECH-ME", "seat_category": "REGULAR", "count": 22})
    assert r.json()["allowed_within_rules"] is True  # 38 regular + 22 = 60
    r = client.post("/api/v1/seat-check", headers=h,
                    json={"programme_code": "BTECH-ME", "seat_category": "REGULAR", "count": 23})
    assert r.json()["allowed_within_rules"] is False
    # other institution's programme code is not visible
    r = client.post("/api/v1/seat-check", headers=h, json={"programme_code": "MBA", "seat_category": "REGULAR"})
    assert r.status_code == 404
    # AICTE is not an institution user
    r = client.post("/api/v1/seat-check", headers=as_("aicte.admin@demo.local"),
                    json={"programme_code": "MBA", "seat_category": "REGULAR"})
    assert r.status_code == 403


def test_status_transitions():
    assert ledger.TRANSITIONS["PROVISIONAL"] == {"ACTIVE", "CANCELLED", "WITHDRAWN"}
    assert ledger.TRANSITIONS["WITHDRAWN"] == {"ACTIVE"}
    assert ledger.TRANSITIONS["GRADUATED"] == set()
