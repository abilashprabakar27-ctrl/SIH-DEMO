"""Versioned and source-labelled capacity rule sets for supernumerary caps."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AcademicYear, CapacityRuleEntry, CapacityRuleSet


def seed_capacity_rules(db: Session) -> None:
    for year, starts_on, ends_on in (("2025-26", date(2025, 4, 1), date(2026, 3, 31)),
                                     ("2026-27", date(2026, 4, 1), date(2027, 3, 31))):
        if db.get(AcademicYear, year) is None:
            db.add(AcademicYear(year=year, starts_on=starts_on, ends_on=ends_on, is_locked=False))
    db.flush()
    if db.execute(select(CapacityRuleSet.id).limit(1)).first():
        return
    active = CapacityRuleSet(
        code="PROTOTYPE_DEFAULTS", version=1, source_type="SECONDARY",
        source_ref="Prototype assumptions; see docs/PRODUCTION_READINESS.md",
        source_url=None, source_accessed_on=date.today(), verification_status="UNVERIFIED",
        academic_year_from="2025-26", academic_year_to="2035-36",
        effective_from=date(2025, 4, 1), status="ACTIVE",
        reason="Seeded prototype defaults; not an authoritative policy source.",
    )
    draft = CapacityRuleSet(
        code="DEMO_ALL_15_PERCENT", version=1, source_type="SECONDARY",
        source_ref="Demo D scenario; not an authoritative policy source",
        source_url=None, source_accessed_on=date.today(), verification_status="UNVERIFIED",
        academic_year_from="2025-26", academic_year_to="2035-36",
        effective_from=date(2025, 4, 1), status="DRAFT",
        reason="Demonstration draft only.",
    )
    db.add_all([active, draft])
    db.flush()
    for rs, draft_all in ((active, False), (draft, True)):
        scopes = [
            ("DIPLOMA", "ENGINEERING", 1500 if not draft_all else 1500),
            ("UG", "ENGINEERING", 1500 if not draft_all else 1500),
            ("PG", "ENGINEERING", 2500 if not draft_all else 1500),
            ("*", "*", 2500 if not draft_all else 1500),
        ]
        for level, discipline, pool_bp in scopes:
            for category, bp, numerator, denominator in (
                ("SN_FN_OCI", pool_bp, 2, 3),
                ("SN_CIWG", pool_bp, 1, 3),
                ("SN_TFW", 500, 1, 1),
                ("SN_OTHER", 0, 1, 1),
            ):
                db.add(CapacityRuleEntry(rule_set_id=rs.id, seat_category=category, level=level,
                                         discipline=discipline, percent_bp=bp, numerator=numerator,
                                         denominator=denominator, rounding="FLOOR"))


def resolve_rule_set(db: Session, academic_year: str) -> CapacityRuleSet | None:
    candidates = db.execute(select(CapacityRuleSet).where(
        CapacityRuleSet.status == "ACTIVE",
        CapacityRuleSet.academic_year_from <= academic_year,
        CapacityRuleSet.academic_year_to >= academic_year,
    )).scalars().all()
    return candidates[0] if len(candidates) == 1 else None


def _round(numerator: int, denominator: int, method: str) -> int:
    if denominator <= 0:
        raise ValueError("Rule denominator must be positive.")
    if method == "FLOOR":
        return numerator // denominator
    if method == "CEIL":
        return (numerator + denominator - 1) // denominator
    if method == "NEAREST":
        return (2 * numerator + denominator) // (2 * denominator)
    raise ValueError(f"Unsupported integer rounding method: {method}")


def _entry_for(db: Session, rule_set: CapacityRuleSet, category: str, level: str, discipline: str):
    entries = db.execute(select(CapacityRuleEntry).where(
        CapacityRuleEntry.rule_set_id == rule_set.id,
        CapacityRuleEntry.seat_category == category,
        CapacityRuleEntry.level.in_((level, "*")),
        CapacityRuleEntry.discipline.in_((discipline, "*")),
    )).scalars().all()
    if not entries:
        return None
    return max(entries, key=lambda e: (e.level != "*", e.discipline != "*"))


def caps_from_rule_set(db: Session, rule_set: CapacityRuleSet, intake: int,
                       discipline: str, level: str) -> dict[str, dict]:
    ciwg = _entry_for(db, rule_set, "SN_CIWG", level, discipline)
    fn = _entry_for(db, rule_set, "SN_FN_OCI", level, discipline)
    tfw = _entry_for(db, rule_set, "SN_TFW", level, discipline)
    other = _entry_for(db, rule_set, "SN_OTHER", level, discipline)
    if not ciwg or not fn or not tfw or not other:
        raise ValueError(f"Rule set {rule_set.code} v{rule_set.version} lacks a required category entry.")
    pool = _round(intake * ciwg.percent_bp, 10_000, ciwg.rounding)
    ciwg_cap = _round(pool * ciwg.numerator, ciwg.denominator, ciwg.rounding)
    fn_cap = pool - ciwg_cap
    values = {
        "SN_FN_OCI": (fn, fn_cap, pool),
        "SN_CIWG": (ciwg, ciwg_cap, pool),
        "SN_TFW": (tfw, _round(intake * tfw.percent_bp, 10_000, tfw.rounding), intake),
        "SN_OTHER": (other, 0, intake),
    }
    return {cat: {
        "cap_seats": cap,
        "percent_basis": entry.percent_bp / 100,
        "rule_source": f"Rule set {rule_set.code} v{rule_set.version} · {rule_set.verification_status}",
        "rule_set_id": rule_set.id,
        "rule_set_version": rule_set.version,
        "entry_id": entry.id,
        "calc": {"formula": "intake * percent_bp // 10000; pool split with integer ratio",
                 "intake": intake, "percent_bp": entry.percent_bp, "pool": pool_value, "result": cap},
        "computed_at": None,
    } for cat, (entry, cap, pool_value) in values.items()}
