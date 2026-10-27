"""Dashboards and review priority. Every number comes from the database.

Review priority ranks institutions for review attention. A high score is not evidence of wrongdoing.
Rule signals (points):
  seats over intake             min(35, 10 + 100 * excess / intake)   (institution totals)
  supernumerary over cap        min(15, 5 + 2 * excess)
  open cross-institution flags  min(20, 4 * n)
  unverified APAAR share > 5%   min(15, round(30 * share))
  uncorrected upload errors>10% min(10, round(20 * share))
  enrolment jump > 30% with intake change <= 10%      10
  changes after submission declared                    min(10, 2 * n)
  overdue student correction requests                  min(10, 3 * n)
Peer statistics: robust z = (x - median) / (1.4826 * MAD) on utilisation, supernumerary share, NRI share,
out-of-window admission share and max same-DOB share; |z| > 3.5 adds 8 points. Peers are institutions of
the same type; with fewer than 8 such peers, all institutions are used (stated in the output).
Score capped at 100. Bands: LOW < 25, MEDIUM 25-49, HIGH >= 50.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings, today
from ..db import utcnow
from ..models import (
    CorrectionRequest,
    Enrolment,
    ImportJob,
    ImportRow,
    Institution,
    Programme,
    RecordRevision,
    Student,
    ValidationIssue,
)
from . import ledger
from .issues import OPEN_STATES

DISCLAIMER = "Ranks institutions for review attention. A high score is not evidence of wrongdoing."


def _prev_year(year: str) -> str:
    y = int(year[:4]) - 1
    return f"{y}-{(y + 1) % 100:02d}"


def _institutions(db: Session, state: str | None = None) -> dict[str, Institution]:
    q = select(Institution)
    if state:
        q = q.where(Institution.state == state)
    return {i.id: i for i in db.execute(q).scalars()}


def _figures(positions: list[dict]) -> dict:
    intake = sum(p["approved_intake"] for p in positions)
    within = sum(p["within_intake_enrolled"] for p in positions)
    sn = sum(p["supernumerary_enrolled"] for p in positions)
    return {
        "programmes": len(positions),
        "approved_intake": intake,
        "within_intake_enrolled": within,
        "supernumerary_enrolled": sn,
        "total_enrolled": within + sn,
        "vacant_within_intake": sum(p["vacant_within_intake"] for p in positions),
        "excess_over_intake": sum(p["excess_over_intake"] for p in positions),
        "programmes_over_intake": sum(1 for p in positions if p["excess_over_intake"] > 0),
        "programmes_over_cap": sum(1 for p in positions if any(v["excess"] for v in p["supernumerary"].values())),
        "utilisation_pct": round(100.0 * within / intake, 1) if intake else None,
    }


def _student_breakdowns(db: Session, year: str, programme_ids: list[str]) -> tuple[dict, dict]:
    nat, apaar = Counter(), Counter()
    if not programme_ids:
        return {}, {}
    for n, a, cnt in db.execute(
        select(Student.nationality_status, Student.apaar_status, func.count())
        .join(Enrolment, Enrolment.student_id == Student.id)
        .where(Enrolment.academic_year == year, Enrolment.status.in_(ledger.OCCUPYING),
               Enrolment.programme_id.in_(programme_ids))
        .group_by(Student.nationality_status, Student.apaar_status)
    ):
        nat[n] += cnt
        apaar[a] += cnt
    return dict(nat), dict(apaar)


def national(db: Session, year: str, state: str | None = None, discipline: str | None = None) -> dict:
    insts = _institutions(db, state)
    positions = [p for p in ledger.all_positions(db, year, list(insts)) if not discipline or p["discipline"] == discipline]
    for p in positions:
        i = insts[p["institution_id"]]
        p["institution_name"], p["aicte_code"], p["state"] = i.name, i.aicte_code, i.state
    prog_ids = [p["programme_id"] for p in positions]
    nat, apaar = _student_breakdowns(db, year, prog_ids)
    by_state: dict[str, dict] = defaultdict(lambda: {"approved_intake": 0, "within_intake_enrolled": 0,
                                                     "total_enrolled": 0, "excess_over_intake": 0})
    for p in positions:
        s = by_state[p["state"]]
        s["approved_intake"] += p["approved_intake"]
        s["within_intake_enrolled"] += p["within_intake_enrolled"]
        s["total_enrolled"] += p["total_enrolled"]
        s["excess_over_intake"] += p["excess_over_intake"]
    flags = Counter()
    q = select(ValidationIssue.rule_id, func.count()).where(ValidationIssue.status.in_(OPEN_STATES))
    q = q.where(ValidationIssue.academic_year == year)
    if state:
        q = q.where(ValidationIssue.institution_id.in_(list(insts)))
    for rid, cnt in db.execute(q.group_by(ValidationIssue.rule_id)):
        flags[rid] = cnt
    submission = []
    by_inst = defaultdict(list)
    for p in positions:
        by_inst[p["institution_id"]].append(p)
    for iid, ps in sorted(by_inst.items(), key=lambda kv: insts[kv[0]].aicte_code):
        done = sum(1 for p in ps if p["submitted_at"])
        submission.append({"institution_id": iid, "institution_name": insts[iid].name, "aicte_code": insts[iid].aicte_code,
                           "programmes": len(ps), "submitted": done, "complete": done == len(ps)})
    total_students = sum(apaar.values())
    return {
        "academic_year": year,
        "filters": {"state": state, "discipline": discipline},
        "figures": dict(_figures(positions), institutions=len(by_inst),
                        nri_enrolled=sum(p["nri"] for p in positions)),
        "excess_alerts": [p for p in positions if p["any_excess"]],
        "by_state": [dict(state=k, **v) for k, v in sorted(by_state.items())],
        "nationality": nat,
        "apaar_coverage": {
            "by_status": apaar,
            "verified_pct": round(100.0 * apaar.get("VERIFIED", 0) / total_students, 1) if total_students else None,
            "mode": "SIMULATED",
        },
        "open_flags_by_rule": dict(sorted(flags.items())),
        "submission_status": submission,
        "programmes": sorted(positions, key=lambda p: (p["aicte_code"], p["programme_code"])),
        "states": sorted({i.state for i in _institutions(db).values()}),
        "generated_at": utcnow().isoformat(),
    }


def institution(db: Session, inst: Institution, year: str) -> dict:
    positions = ledger.all_positions(db, year, [inst.id])
    jobs = db.execute(select(ImportJob).where(ImportJob.institution_id == inst.id)
                      .order_by(ImportJob.created_at.desc()).limit(6)).scalars().all()
    issue_q = select(ValidationIssue).where(ValidationIssue.status.in_(OPEN_STATES))
    open_issues = [i for i in db.execute(issue_q).scalars()
                   if i.institution_id == inst.id or inst.id in (i.related_institution_ids or [])]
    crs = db.execute(select(CorrectionRequest).where(CorrectionRequest.institution_id == inst.id,
                                                     CorrectionRequest.status == "OPEN")
                     .order_by(CorrectionRequest.due_at)).scalars().all()
    nat, apaar = _student_breakdowns(db, year, [p["programme_id"] for p in positions])
    now = utcnow()
    return {
        "institution": {"id": inst.id, "name": inst.name, "aicte_code": inst.aicte_code, "state": inst.state,
                        "institution_type": inst.institution_type},
        "academic_year": year,
        "figures": _figures(positions),
        "programmes": sorted(positions, key=lambda p: p["programme_code"]),
        "recent_uploads": [{"id": j.id, "filename": j.filename, "status": j.status, "academic_year": j.academic_year,
                            "total_rows": j.total_rows, "committed_rows": j.committed_rows,
                            "counts": (j.summary or {}).get("counts", {}), "created_at": j.created_at.isoformat()}
                           for j in jobs],
        "open_flags": {"total": len(open_issues), "by_rule": dict(Counter(i.rule_id for i in open_issues))},
        "correction_requests": {"open": len(crs), "overdue": sum(1 for c in crs if c.due_at < now),
                                "items": [{"id": c.id, "field": c.field, "due_at": c.due_at.isoformat(),
                                           "overdue": c.due_at < now} for c in crs[:5]]},
        "nationality": nat,
        "apaar_coverage": apaar,
        "submission": {"programmes": len(positions), "submitted": sum(1 for p in positions if p["submitted_at"]),
                       "deadline": settings.submission_deadline},
        "generated_at": now.isoformat(),
    }


# ---------------------------------------------------------------- review priority


def _metrics(db: Session, year: str, insts: dict[str, Institution]) -> dict[str, dict]:
    """Per-institution peer metrics and raw inputs for rule signals."""
    positions = ledger.all_positions(db, year, list(insts))
    prev_positions = ledger.all_positions(db, _prev_year(year), list(insts))
    out: dict[str, dict] = {iid: {"positions": [], "prev_positions": []} for iid in insts}
    for p in positions:
        out[p["institution_id"]]["positions"].append(p)
    for p in prev_positions:
        out[p["institution_id"]]["prev_positions"].append(p)
    start = int(year[:4])
    win_lo, win_hi = date(start, 5, 1), date(start + 1, 3, 31)
    rows = db.execute(
        select(Enrolment.institution_id, Enrolment.admission_date, Student.date_of_birth, Student.apaar_status)
        .join(Student, Student.id == Enrolment.student_id)
        .where(Enrolment.academic_year == year, Enrolment.status.in_(ledger.OCCUPYING),
               Enrolment.institution_id.in_(list(insts)))
    ).all()
    per = defaultdict(list)
    for iid, adm, dob, ast in rows:
        per[iid].append((adm, dob, ast))
    for iid, m in out.items():
        f = _figures(m["positions"])
        pf = _figures(m["prev_positions"])
        recs = per.get(iid, [])
        n = len(recs)
        dob_counts = Counter(dob for _a, dob, _s in recs)
        m.update(
            figures=f,
            prev_figures=pf,
            n=n,
            utilisation=(f["within_intake_enrolled"] / f["approved_intake"]) if f["approved_intake"] else 0.0,
            supernumerary_share=(f["supernumerary_enrolled"] / f["total_enrolled"]) if f["total_enrolled"] else 0.0,
            nri_share=(sum(p["nri"] for p in m["positions"]) / f["total_enrolled"]) if f["total_enrolled"] else 0.0,
            out_of_window_share=(sum(1 for a, _d, _s in recs if not (win_lo <= a <= win_hi)) / n) if n else 0.0,
            max_same_dob_share=(max(dob_counts.values()) / n) if n else 0.0,
            unverified_share=(sum(1 for _a, _d, s in recs if s in ("UNVERIFIED", "MISMATCH", "NOT_FOUND")) / n) if n else 0.0,
        )
    return out


PEER_METRICS = [
    ("utilisation", "utilisation"),
    ("supernumerary_share", "supernumerary share"),
    ("nri_share", "NRI share"),
    ("out_of_window_share", "admissions outside the admission window"),
    ("max_same_dob_share", "largest same-date-of-birth share"),
]


def robust_z(x: float, values: list[float]) -> float | None:
    med = statistics.median(values)
    mad = statistics.median([abs(v - med) for v in values])
    if mad == 0:
        return None
    return (x - med) / (1.4826 * mad)


def review_priority(db: Session, year: str, institution_ids: list[str] | None = None) -> dict:
    insts = _institutions(db)
    metrics = _metrics(db, year, insts)
    now = utcnow()
    results = []
    for iid, inst in insts.items():
        m = metrics[iid]
        if not m["positions"]:
            continue
        signals = []

        def sig(key, label, points, sentence, evidence=None):
            signals.append({"key": key, "label": label, "points": int(points), "sentence": sentence,
                            "evidence": evidence or {}})

        f = m["figures"]
        if f["excess_over_intake"] > 0 and f["approved_intake"]:
            pts = min(35, round(10 + 100 * f["excess_over_intake"] / f["approved_intake"]))
            progs = [f"{p['programme_code']} +{p['excess_over_intake']}" for p in m["positions"] if p["excess_over_intake"]]
            sig("seats_over_intake", "Seats over approved intake", pts,
                f"{f['excess_over_intake']} seat(s) over approved intake ({', '.join(progs)}).",
                {"excess": f["excess_over_intake"], "intake": f["approved_intake"]})
        sn_excess = sum(v["excess"] for p in m["positions"] for v in p["supernumerary"].values())
        if sn_excess:
            cats = [f"{p['programme_code']} {c} {v['enrolled']}/{v['cap']}" for p in m["positions"]
                    for c, v in p["supernumerary"].items() if v["excess"]]
            sig("supernumerary_over_cap", "Supernumerary over cap", min(15, 5 + 2 * sn_excess),
                f"{sn_excess} supernumerary seat(s) over cap ({', '.join(cats)}).", {"excess": sn_excess})
        xinst = [i for i in db.execute(select(ValidationIssue).where(
            ValidationIssue.rule_id == "D003_XINST_ACTIVE", ValidationIssue.status.in_(OPEN_STATES))).scalars()
            if i.institution_id == iid or iid in (i.related_institution_ids or [])]
        if xinst:
            sig("cross_institution", "Open cross-institution conflicts", min(20, 4 * len(xinst)),
                f"{len(xinst)} open cross-institution enrolment conflict(s).", {"open": len(xinst)})
        if m["unverified_share"] > 0.05:
            sig("unverified_apaar", "Unverified APAAR IDs", min(15, round(30 * m["unverified_share"])),
                f"{m['unverified_share']:.0%} of enrolled students have an unverified or mismatched APAAR ID (registry SIMULATED).",
                {"share": round(m["unverified_share"], 3)})
        rows = db.execute(
            select(ImportRow.status, func.count()).join(ImportJob, ImportJob.id == ImportRow.job_id)
            .where(ImportJob.institution_id == iid, ImportJob.academic_year == year, ImportJob.status != "DISCARDED")
            .group_by(ImportRow.status)
        ).all()
        total_rows = sum(c for _s, c in rows)
        err_rows = sum(c for s, c in rows if s == "ERROR")
        if total_rows and err_rows / total_rows > 0.10:
            share = err_rows / total_rows
            sig("upload_errors", "Uncorrected upload errors", min(10, round(20 * share)),
                f"{err_rows} of {total_rows} uploaded rows ({share:.0%}) still have errors.", {"share": round(share, 3)})
        pf = m["prev_figures"]
        if pf["total_enrolled"]:
            jump = (f["total_enrolled"] - pf["total_enrolled"]) / pf["total_enrolled"]
            intake_change = abs(f["approved_intake"] - pf["approved_intake"]) / pf["approved_intake"] if pf["approved_intake"] else 1
            if jump > 0.30 and intake_change <= 0.10:
                sig("enrolment_jump", "Enrolment jump", 10,
                    f"Enrolment rose {jump:.0%} on last year ({pf['total_enrolled']} to {f['total_enrolled']}) "
                    f"while approved intake changed {intake_change:.0%}.", {"jump": round(jump, 3)})
        late = 0
        for p in m["positions"]:
            if p["submitted_at"]:
                from datetime import datetime as _dt
                sub = _dt.fromisoformat(p["submitted_at"])
                enrol_ids = select(Enrolment.id).where(Enrolment.programme_id == p["programme_id"],
                                                       Enrolment.academic_year == year)
                late += db.execute(select(func.count()).select_from(RecordRevision).where(
                    RecordRevision.entity_type == "enrolment", RecordRevision.entity_id.in_(enrol_ids),
                    RecordRevision.at > sub)).scalar()
        if late:
            sig("late_changes", "Changes after submission declared", min(10, 2 * late),
                f"{late} record change(s) after the institution declared its submission complete.", {"changes": late})
        overdue = db.execute(select(func.count()).select_from(CorrectionRequest).where(
            CorrectionRequest.institution_id == iid, CorrectionRequest.status == "OPEN",
            CorrectionRequest.due_at < now)).scalar()
        if overdue:
            sig("overdue_corrections", "Overdue student correction requests", min(10, 3 * overdue),
                f"{overdue} student correction request(s) past their 14-day due date.", {"overdue": overdue})

        # peer statistics
        same_type = [j for j in insts if insts[j].institution_type == inst.institution_type and metrics[j]["positions"]]
        if len(same_type) >= 8:
            peers, basis = same_type, f"peers of type {inst.institution_type} ({len(same_type)})"
        else:
            peers = [j for j in insts if metrics[j]["positions"]]
            basis = (f"all institutions ({len(peers)}): fewer than 8 {inst.institution_type.lower()} peers "
                     "in this register")
        peer_stats = []
        for key, label in PEER_METRICS:
            vals = [metrics[j][key] for j in peers]
            z = robust_z(m[key], vals)
            med = statistics.median(vals)
            peer_stats.append({"metric": key, "label": label, "value": round(m[key], 4), "peer_median": round(med, 4),
                               "z": None if z is None else round(z, 2)})
            if z is not None and abs(z) > 3.5:
                sig(f"peer_{key}", f"Unusual {label}", 8,
                    f"{label.capitalize()} {m[key]:.0%} vs peer median {med:.0%} (robust z {z:+.1f}).",
                    {"z": round(z, 2)})
        score = min(100, sum(s["points"] for s in signals))
        band = "HIGH" if score >= 50 else "MEDIUM" if score >= 25 else "LOW"
        results.append({
            "institution_id": iid, "institution_name": inst.name, "aicte_code": inst.aicte_code, "state": inst.state,
            "institution_type": inst.institution_type, "academic_year": year, "score": score, "band": band,
            "signals": sorted(signals, key=lambda s: -s["points"]), "peer_basis": basis, "peer_stats": peer_stats,
            "figures": f,
        })
    results.sort(key=lambda r: (-r["score"], r["aicte_code"]))
    if institution_ids is not None:
        results = [r for r in results if r["institution_id"] in institution_ids]
    return {"academic_year": year, "disclaimer": DISCLAIMER, "items": results, "generated_at": now.isoformat(),
            "as_of": today().isoformat()}


def intake_rows(db: Session, year: str, institution_ids: list[str] | None = None) -> list[list]:
    insts = _institutions(db)
    out = []
    for p in sorted(ledger.all_positions(db, year, institution_ids), key=lambda p: (insts[p["institution_id"]].aicte_code, p["programme_code"])):
        i = insts[p["institution_id"]]
        sn = p["supernumerary"]
        out.append([i.aicte_code, i.name, i.state, p["programme_code"], p["programme_name"], year, p["approved_intake"],
                    p["regular"], p["nri"], p["within_intake_enrolled"], p["excess_over_intake"], p["utilisation_pct"],
                    *[f"{sn[c]['enrolled']}/{sn[c]['cap']}" for c in ("SN_FN_OCI", "SN_CIWG", "SN_TFW", "SN_OTHER")],
                    p["total_enrolled"], "yes" if p["submitted_at"] else "no"])
    return out


INTAKE_HEADERS = ["aicte_code", "institution", "state", "programme_code", "programme", "academic_year",
                  "approved_intake", "regular", "nri", "within_intake", "excess_over_intake", "utilisation_pct",
                  "sn_fn_oci", "sn_ciwg", "sn_tfw", "sn_other", "total_enrolled", "submission_declared"]


def nationality_rows(db: Session, year: str, institution_ids: list[str] | None = None) -> list[list]:
    insts = _institutions(db)
    q = (select(Enrolment.institution_id, Programme.code, Student.nationality_status, Enrolment.seat_category, func.count())
         .join(Student, Student.id == Enrolment.student_id).join(Programme, Programme.id == Enrolment.programme_id)
         .where(Enrolment.academic_year == year, Enrolment.status.in_(ledger.OCCUPYING)))
    if institution_ids is not None:
        q = q.where(Enrolment.institution_id.in_(institution_ids))
    q = q.group_by(Enrolment.institution_id, Programme.code, Student.nationality_status, Enrolment.seat_category)
    rows = [[insts[i].aicte_code, insts[i].name, code, year, nat, seat, n] for i, code, nat, seat, n in db.execute(q)]
    return sorted(rows)
