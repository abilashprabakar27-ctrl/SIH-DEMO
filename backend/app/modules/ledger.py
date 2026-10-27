"""Seat ledger: the definition of "excess".

1. Only ACTIVE or PROVISIONAL enrolments occupy a seat.
2. REGULAR and NRI count against approved intake.
3. Each supernumerary category counts only against its own cap.
4. Unused supernumerary seats are not transferable between categories.
5. Default caps are rounded down and stored with their rule source.
6. excess_over_intake = max(0, REGULAR+NRI - intake); category excess = max(0, enrolled - cap).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import ApprovedIntake, Enrolment, Programme, SupernumeraryQuota
from .normalize import SUPERNUMERARY

OCCUPYING = ("ACTIVE", "PROVISIONAL")
WITHIN_INTAKE = ("REGULAR", "NRI")

TRANSITIONS = {
    "PROVISIONAL": {"ACTIVE", "CANCELLED", "WITHDRAWN"},
    "ACTIVE": {"WITHDRAWN", "TRANSFERRED_OUT", "GRADUATED", "CANCELLED"},
    "WITHDRAWN": {"ACTIVE"},
    "TRANSFERRED_OUT": set(),
    "GRADUATED": set(),
    "CANCELLED": set(),
}


def occupies_seat(status: str) -> bool:
    return status in OCCUPYING


def pool_percent(discipline: str, level: str) -> int:
    if discipline == "ENGINEERING" and level in ("DIPLOMA", "UG"):
        return 15
    return 25


def default_caps(intake: int, discipline: str, level: str) -> dict[str, dict]:
    """Default supernumerary caps with their rule source (all rounded down)."""
    pct = pool_percent(discipline, level)
    pool = intake * pct // 100
    ciwg = pool // 3
    basis = f"{discipline.lower()} {level}"
    return {
        "SN_FN_OCI": {
            "cap_seats": pool - ciwg,
            "percent_basis": float(pct),
            "rule_source": f"DEFAULT: FN/OCI/CIWG pool {pct}% of intake for {basis} (AICTE APH cl. 2.12.1(h) as read; "
            f"2026-27 addendum for PG/other disciplines), pool {pool}, two-thirds for FN/OCI",
        },
        "SN_CIWG": {
            "cap_seats": ciwg,
            "percent_basis": float(pct),
            "rule_source": f"DEFAULT: one-third of the {pct}% FN/OCI/CIWG pool ({pool}) reserved for CIWG",
        },
        "SN_TFW": {
            "cap_seats": intake * 5 // 100,
            "percent_basis": 5.0,
            "rule_source": "DEFAULT: Tuition Fee Waiver up to 5% of sanctioned intake, supernumerary",
        },
        "SN_OTHER": {
            "cap_seats": 0,
            "percent_basis": None,
            "rule_source": "DEFAULT: no other supernumerary category unless configured by AICTE",
        },
    }


def position_from_counts(intake: int, caps: dict[str, int], counts: dict[str, int]) -> dict:
    """Pure seat position. counts: occupying enrolments per seat category."""
    regular = counts.get("REGULAR", 0)
    nri = counts.get("NRI", 0)
    within = regular + nri
    sn = {}
    sn_total = 0
    any_excess = within > intake
    for cat in SUPERNUMERARY:
        enrolled = counts.get(cat, 0)
        cap = caps.get(cat, 0)
        excess = max(0, enrolled - cap)
        any_excess = any_excess or excess > 0
        sn[cat] = {"enrolled": enrolled, "cap": cap, "excess": excess}
        sn_total += enrolled
    return {
        "approved_intake": intake,
        "within_intake_enrolled": within,
        "regular": regular,
        "nri": nri,
        "excess_over_intake": max(0, within - intake),
        "vacant_within_intake": max(0, intake - within),
        "utilisation_pct": None if intake == 0 else round(100.0 * within / intake, 1),
        "supernumerary": sn,
        "supernumerary_enrolled": sn_total,
        "total_enrolled": within + sn_total,
        "any_excess": any_excess,
    }


# ---------------------------------------------------------------- database helpers


def get_intake(db: Session, programme_id: str, academic_year: str) -> ApprovedIntake | None:
    return db.execute(
        select(ApprovedIntake).where(
            ApprovedIntake.programme_id == programme_id, ApprovedIntake.academic_year == academic_year
        )
    ).scalar_one_or_none()


def caps_for(db: Session, intake: ApprovedIntake | None) -> dict[str, int]:
    if intake is None:
        return {}
    rows = db.execute(select(SupernumeraryQuota).where(SupernumeraryQuota.intake_id == intake.id)).scalars()
    return {q.seat_category: q.cap_seats for q in rows}


def counts_for(db: Session, programme_id: str, academic_year: str) -> dict[str, int]:
    rows = db.execute(
        select(Enrolment.seat_category, func.count())
        .where(
            Enrolment.programme_id == programme_id,
            Enrolment.academic_year == academic_year,
            Enrolment.status.in_(OCCUPYING),
        )
        .group_by(Enrolment.seat_category)
    ).all()
    return {cat: n for cat, n in rows}


def position(db: Session, programme_id: str, academic_year: str) -> dict:
    intake = get_intake(db, programme_id, academic_year)
    pos = position_from_counts(
        intake.approved_intake if intake else 0, caps_for(db, intake), counts_for(db, programme_id, academic_year)
    )
    pos["programme_id"] = programme_id
    pos["academic_year"] = academic_year
    pos["has_intake"] = intake is not None
    return pos


def all_positions(db: Session, academic_year: str, institution_ids: list[str] | None = None) -> list[dict]:
    """Seat positions for every programme with an intake in the year (one grouped query)."""
    q = (
        select(ApprovedIntake, Programme)
        .join(Programme, Programme.id == ApprovedIntake.programme_id)
        .where(ApprovedIntake.academic_year == academic_year)
    )
    if institution_ids is not None:
        q = q.where(Programme.institution_id.in_(institution_ids))
    intakes = db.execute(q).all()
    if not intakes:
        return []
    prog_ids = [p.id for _, p in intakes]
    counts: dict[str, dict[str, int]] = {}
    for pid, cat, n in db.execute(
        select(Enrolment.programme_id, Enrolment.seat_category, func.count())
        .where(
            Enrolment.academic_year == academic_year,
            Enrolment.status.in_(OCCUPYING),
            Enrolment.programme_id.in_(prog_ids),
        )
        .group_by(Enrolment.programme_id, Enrolment.seat_category)
    ):
        counts.setdefault(pid, {})[cat] = n
    caps: dict[str, dict[str, int]] = {}
    for q_ in db.execute(
        select(SupernumeraryQuota).where(SupernumeraryQuota.intake_id.in_([i.id for i, _ in intakes]))
    ).scalars():
        caps.setdefault(q_.intake_id, {})[q_.seat_category] = q_.cap_seats
    out = []
    for intake, prog in intakes:
        pos = position_from_counts(intake.approved_intake, caps.get(intake.id, {}), counts.get(prog.id, {}))
        pos.update(
            programme_id=prog.id,
            programme_code=prog.code,
            programme_name=prog.name,
            discipline=prog.discipline,
            level=prog.level,
            institution_id=prog.institution_id,
            academic_year=academic_year,
            intake_id=intake.id,
            submitted_at=intake.submitted_at.isoformat() if intake.submitted_at else None,
        )
        out.append(pos)
    return out


def apply_default_caps(db: Session, intake: ApprovedIntake, programme: Programme) -> None:
    """(Re)derive default caps. Caps configured by AICTE (rule_source not DEFAULT) are kept."""
    existing = {
        q.seat_category: q
        for q in db.execute(select(SupernumeraryQuota).where(SupernumeraryQuota.intake_id == intake.id)).scalars()
    }
    for cat, spec in default_caps(intake.approved_intake, programme.discipline, programme.level).items():
        q = existing.get(cat)
        if q is None:
            db.add(SupernumeraryQuota(intake_id=intake.id, seat_category=cat, **spec))
        elif q.rule_source.startswith("DEFAULT"):
            q.cap_seats = spec["cap_seats"]
            q.percent_basis = spec["percent_basis"]
            q.rule_source = spec["rule_source"]
    db.flush()


def seat_check(position_: dict, seat_category: str, count: int) -> dict:
    """Advisory answer: would admitting `count` more students in `seat_category` stay within the rules?"""
    within = position_["within_intake_enrolled"]
    intake = position_["approved_intake"]
    result: dict = {
        "within_intake": {"approved": intake, "occupied": within, "after": within},
        "category": None,
    }
    if seat_category in WITHIN_INTAKE:
        after = within + count
        result["counts_against"] = "approved intake"
        result["within_intake"]["after"] = after
        allowed = after <= intake
        if allowed:
            msg = (
                f"Within approved intake: {after} of {intake} seats would be occupied "
                f"({intake - after} left after this admission)."
            )
        else:
            msg = (
                f"This would exceed approved intake by {after - intake}: {within} of {intake} seats are "
                f"occupied and {count} more {seat_category} admission(s) would make {after}."
            )
    else:
        sn = position_["supernumerary"].get(seat_category, {"enrolled": 0, "cap": 0})
        after = sn["enrolled"] + count
        label = seat_category.replace("SN_", "").replace("_", "/")
        result["counts_against"] = f"{seat_category} cap"
        result["category"] = {"cap": sn["cap"], "occupied": sn["enrolled"], "after": after}
        allowed = after <= sn["cap"]
        if allowed:
            msg = f"Within the supernumerary {label} cap: {after} of {sn['cap']} seats would be used."
        else:
            msg = (
                f"This would exceed the supernumerary {label} cap by {after - sn['cap']} "
                f"({sn['enrolled']} of {sn['cap']} used). Unused seats in other categories cannot be transferred."
            )
    result["allowed_within_rules"] = allowed
    result["message"] = msg + " Advisory only; the register records what is admitted."
    return result
