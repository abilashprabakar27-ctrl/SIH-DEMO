"""Validation engine. The only module that writes students and enrolments.

Upload, manual entry, corrections and the integration API all call validate_rows() and
commit_values(). Pipeline: normalise -> row rules -> adapter -> file rules -> repository rules
(skipped when R001/R002/R005/R006/R012 errors) -> projection (seat position, computed by callers).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import today
from ..models import (
    ApprovedIntake,
    Enrolment,
    Institution,
    Programme,
    RecordRevision,
    Student,
)
from ..security import Actor, apaar_ref
from . import identity, issues
from .apaar_adapter import did_you_mean, get_adapter
from .ledger import OCCUPYING
from .normalize import finding, is_india, name_key, normalise_row
from .rules import load_config

SEVERITY_ORDER = {"ERROR": 3, "REVIEW": 2, "WARNING": 1}
GATING = {"R001_REQUIRED", "R002_FORMAT", "R005_APAAR_FORMAT", "R006_APAAR_NOT_FOUND", "R012_PROGRAMME"}
STUDENT_FIELDS = (
    "full_name",
    "date_of_birth",
    "gender",
    "nationality_status",
    "citizenship_country",
    "social_category",
    "email",
)


@dataclass
class RowPlan:
    row_no: int
    data: dict
    parsed: dict
    findings: list[dict]
    status: str = "VALID"
    programme_id: str | None = None
    student_id: str | None = None  # existing student this row resolves to
    enrolment_id: str | None = None  # existing enrolment this row updates
    adapter_status: str | None = None
    candidates: list[dict] = field(default_factory=list)
    xinst: list[dict] = field(default_factory=list)

    def has(self, *rule_ids: str) -> bool:
        return any(f["rule_id"] in rule_ids for f in self.findings)


def _age(dob: date, on: date) -> int:
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def _row_rules(p: dict, f: list, programmes: dict, intake_keys: set, upload_year: str) -> str | None:
    """Row-level rules. Returns programme_id if the programme resolves."""
    apaar, reason, nat, seat = p["apaar_id"], p["apaar_pending_reason"], p["nationality_status"], p["seat_category"]
    if not apaar:
        if reason:
            f.append(finding("R004_APAAR_PENDING", None, "apaar_id",
                             f"No APAAR ID yet ({reason.replace('_', ' ').lower()}). Accepted and flagged for follow-up.",
                             {"pending_reason": reason}))
            if reason == "FOREIGN_NATIONAL" and nat and nat not in ("FN", "OCI"):
                f.append(finding("R013_CATEGORY_CONSISTENCY", None, "apaar_pending_reason",
                                 "Pending reason FOREIGN_NATIONAL is only valid for FN or OCI students.",
                                 {"nationality_status": nat}))
        else:
            f.append(finding("R003_APAAR_MISSING", None, "apaar_id",
                             "APAAR ID is missing. Enter it, or give a pending reason."))
    elif not (len(apaar) == 12 and apaar.isdigit()) or len(set(apaar)) == 1:
        f.append(finding("R005_APAAR_FORMAT", None, "apaar_id",
                         f"APAAR ID must be exactly 12 digits (this one has {sum(c.isdigit() for c in apaar)} "
                         f"digit(s){' and other characters' if not apaar.isdigit() else ''}).",
                         {"length": len(apaar)}))

    now = today()
    dob, adm = p["date_of_birth"], p["admission_date"]
    if dob and dob > now:
        f.append(finding("R010_DATE_LOGIC", None, "date_of_birth", "Date of birth is in the future.",
                         {"date_of_birth": dob.isoformat()}))
    if adm and adm > now:
        f.append(finding("R010_DATE_LOGIC", None, "admission_date", "Admission date is in the future.",
                         {"admission_date": adm.isoformat()}))
    if dob and adm and dob <= now:
        age = _age(dob, adm)
        if age < 15:
            f.append(finding("R010_DATE_LOGIC", None, "date_of_birth",
                             f"Age at admission would be {age}; the minimum is 15. Check the year of birth.",
                             {"age_at_admission": age}))
        elif age > 45:
            f.append(finding("R011_DATE_UNUSUAL", None, "date_of_birth",
                             f"Age at admission is {age}. Please confirm.", {"age_at_admission": age}))
    year = p["academic_year"] or upload_year
    if adm and year:
        start = int(year[:4])
        if not (date(start, 5, 1) <= adm <= date(start + 1, 3, 31)):
            f.append(finding("R011_DATE_UNUSUAL", None, "admission_date",
                             f"Admission date is outside the usual window 1 May {start} to 31 March {start + 1}.",
                             {"admission_date": adm.isoformat()}))

    programme_id = None
    code = p["programme_code"]
    if code:
        prog = programmes.get(code)
        if prog is None:
            f.append(finding("R012_PROGRAMME", None, "programme_code",
                             f"Programme {code} is not one of this institution's programmes.",
                             {"programme_code": code, "known_codes": sorted(programmes)}))
        elif (prog.id, year) not in intake_keys:
            f.append(finding("R012_PROGRAMME", None, "programme_code",
                             f"Programme {code} has no approved intake for {year}.", {"programme_code": code}))
        else:
            programme_id = prog.id

    country = p["citizenship_country"]
    if seat and nat:
        if seat == "SN_FN_OCI" and nat not in ("FN", "OCI"):
            f.append(finding("R013_CATEGORY_CONSISTENCY", None, "seat_category",
                             f"A {nat} student cannot hold a supernumerary FN/OCI seat. Use REGULAR (or NRI for NRI students).",
                             {"seat_category": seat, "nationality_status": nat}))
        if seat == "NRI" and nat != "NRI":
            f.append(finding("R013_CATEGORY_CONSISTENCY", None, "seat_category",
                             f"An NRI seat needs nationality status NRI (this row says {nat}).",
                             {"seat_category": seat, "nationality_status": nat}))
        if seat == "SN_CIWG" and nat not in ("INDIAN", "NRI"):
            f.append(finding("R013_CATEGORY_CONSISTENCY", None, "seat_category",
                             "CIWG seats are for children of Indian workers in Gulf countries (INDIAN or NRI).",
                             {"seat_category": seat, "nationality_status": nat}))
    if nat == "FN" and (not country or is_india(country)):
        f.append(finding("R013_CATEGORY_CONSISTENCY", None, "citizenship_country",
                         "A foreign national needs a citizenship country other than India.",
                         {"citizenship_country": country}))
    if nat in ("INDIAN", "NRI") and country and not is_india(country):
        f.append(finding("R013_CATEGORY_CONSISTENCY", None, "citizenship_country",
                         f"{nat} students are Indian citizens; citizenship '{country}' contradicts this. "
                         "Use OCI or FN if the student holds another citizenship.",
                         {"citizenship_country": country}))
    if p["academic_year"] and upload_year and p["academic_year"] != upload_year:
        f.append(finding("R014_YEAR_MISMATCH", None, "academic_year",
                         f"Row year {p['academic_year']} differs from the upload year {upload_year}.",
                         {"row_year": p["academic_year"], "upload_year": upload_year}))
    return programme_id


def validate_rows(
    db: Session,
    institution: Institution,
    academic_year: str,
    rows: list[tuple[int, dict]],
    *,
    self_enrolment_id: str | None = None,
) -> list[RowPlan]:
    cfg = load_config(db)
    programmes = {
        p.code: p for p in db.execute(select(Programme).where(Programme.institution_id == institution.id)).scalars()
    }
    intake_keys = {
        (i.programme_id, i.academic_year)
        for i in db.execute(
            select(ApprovedIntake).where(ApprovedIntake.programme_id.in_([p.id for p in programmes.values()]))
        ).scalars()
    }
    self_enrol = db.get(Enrolment, self_enrolment_id) if self_enrolment_id else None

    plans: list[RowPlan] = []
    for row_no, raw in rows:
        data, parsed, fnd = normalise_row(raw)
        plan = RowPlan(row_no=row_no, data=data, parsed=parsed, findings=fnd)
        plan.programme_id = _row_rules(parsed, fnd, programmes, intake_keys, academic_year)
        plans.append(plan)

    # ---- adapter (SIMULATED registry)
    adapter = get_adapter()
    to_check = [p for p in plans if p.parsed["apaar_id"] and not p.has("R005_APAAR_FORMAT")]
    registry = adapter.lookup_many(db, [p.parsed["apaar_id"] for p in to_check])
    for p in to_check:
        aid = p.parsed["apaar_id"]
        res = adapter.check(registry.get(aid), p.parsed["full_name"], p.parsed["date_of_birth"])
        p.adapter_status = res.status
        if res.status in ("NOT_FOUND", "INACTIVE"):
            sugg = did_you_mean(db, aid, p.parsed["full_name"], p.parsed["date_of_birth"]) if res.status == "NOT_FOUND" else None
            p.findings.append(finding(
                "R006_APAAR_NOT_FOUND", None, "apaar_id",
                f"APAAR ID is {'not found in' if res.status == 'NOT_FOUND' else 'inactive in'} the registry (SIMULATED)."
                + (" A near match exists for this name and date of birth." if sugg else ""),
                {"adapter": res.status, "mode": res.mode},
                {"field": "apaar_id", "value": sugg, "reason": "matches name and date of birth"} if sugg else None,
            ))
        elif res.status in ("NAME_MISMATCH", "DOB_MISMATCH"):
            if res.status == "NAME_MISMATCH":
                msg = f"Registry (SIMULATED) spells the name '{res.registry_name}'."
                fld = "full_name"
            else:
                msg = f"Registry (SIMULATED) has date of birth {res.registry_dob.isoformat()}."
                fld = "date_of_birth"
            p.findings.append(finding("R007_APAAR_MISMATCH", None, fld, msg,
                                      {"adapter": res.status, "mode": res.mode,
                                       "registry_name": res.registry_name,
                                       "registry_dob": res.registry_dob.isoformat() if res.registry_dob else None}))
        elif res.status == "UNAVAILABLE":
            p.findings.append(finding("R008_APAAR_UNVERIFIED", None, "apaar_id",
                                      "APAAR registry (SIMULATED) unavailable; stored as UNVERIFIED and re-checked later.",
                                      {"adapter": res.status, "mode": res.mode}))

    # ---- file rules (rows passed in are the non-excluded rows of the file)
    by_apaar, by_roll, by_person = defaultdict(list), defaultdict(list), defaultdict(list)
    for p in plans:
        if p.parsed["apaar_id"] and not p.has("R005_APAAR_FORMAT"):
            by_apaar[p.parsed["apaar_id"]].append(p)
        if p.parsed["institution_student_id"]:
            by_roll[p.parsed["institution_student_id"].upper()].append(p)
        if p.parsed["name_key"] and p.parsed["date_of_birth"]:
            by_person[(p.parsed["name_key"], p.parsed["date_of_birth"])].append(p)
    for group in by_apaar.values():
        if len(group) > 1:
            for p in group:
                others = [o.row_no + 2 for o in group if o is not p]
                p.findings.append(finding("F001_DUP_APAAR_IN_FILE", None, "apaar_id",
                                          f"Same APAAR ID also on spreadsheet row(s) {', '.join(map(str, others))}.",
                                          {"other_rows": others}))
    for group in by_roll.values():
        if len(group) > 1:
            for p in group:
                others = [o.row_no + 2 for o in group if o is not p]
                p.findings.append(finding("F002_DUP_ROLL_IN_FILE", None, "institution_student_id",
                                          f"Same roll number also on spreadsheet row(s) {', '.join(map(str, others))}.",
                                          {"other_rows": others}))
    for group in by_person.values():
        ids = {p.parsed["apaar_id"] for p in group if p.parsed["apaar_id"]}
        if len(group) > 1 and len(ids) > 1:
            for p in group:
                others = [o.row_no + 2 for o in group if o is not p]
                p.findings.append(finding("F003_POSSIBLE_DUP_IN_FILE", None, "full_name",
                                          f"Same name and date of birth as row(s) {', '.join(map(str, others))} "
                                          "but a different APAAR ID.", {"other_rows": others}))

    # ---- repository rules
    apaars = [p.parsed["apaar_id"] for p in plans if p.parsed["apaar_id"]]
    students_by_apaar = {}
    for i in range(0, len(apaars), 500):
        for st in db.execute(select(Student).where(Student.apaar_id.in_(apaars[i : i + 500]))).scalars():
            students_by_apaar[st.apaar_id] = st
    rolls = [p.parsed["institution_student_id"] for p in plans if p.parsed["institution_student_id"]]
    enrol_by_roll = {}
    for i in range(0, len(rolls), 500):
        for e in db.execute(
            select(Enrolment).where(
                Enrolment.institution_id == institution.id,
                Enrolment.institution_student_id.in_(rolls[i : i + 500]),
            )
        ).scalars():
            enrol_by_roll[e.institution_student_id] = e

    for p in plans:
        if any(f["rule_id"] in GATING for f in p.findings):
            continue
        _repository_rules(db, p, institution, academic_year, students_by_apaar, enrol_by_roll, self_enrol)

    # ---- severity from catalogue, drop disabled rules, compute row status
    for p in plans:
        kept = []
        for f in p.findings:
            rc = cfg.get(f["rule_id"])
            if rc is None or not rc.enabled:
                continue
            f["severity"] = rc.severity
            kept.append(f)
        p.findings = kept
        worst = max((SEVERITY_ORDER[f["severity"]] for f in kept), default=0)
        p.status = {3: "ERROR", 2: "REVIEW", 1: "WARNING", 0: "VALID"}[worst]
    return plans


def _repository_rules(db, p: RowPlan, institution, academic_year, students_by_apaar, enrol_by_roll, self_enrol):
    q = p.parsed
    aid, roll = q["apaar_id"], q["institution_student_id"]
    year = q["academic_year"] or academic_year
    by_apaar = students_by_apaar.get(aid) if aid else None
    owner = self_enrol if self_enrol is not None else enrol_by_roll.get(roll)
    student = by_apaar
    target = None

    if self_enrol is not None:
        target = self_enrol
        student = self_enrol.student
        if by_apaar is not None and by_apaar.id != student.id:
            p.findings.append(finding("D002_ROLL_CONFLICT", None, "apaar_id",
                                      "This APAAR ID already belongs to another student record. Identity merges "
                                      "are a reviewed manual step.", {"enrolment_id": self_enrol.id}))
            return
        if roll and roll != self_enrol.institution_student_id:
            clash = enrol_by_roll.get(roll)
            if clash is not None and clash.id != self_enrol.id:
                p.findings.append(finding("D002_ROLL_CONFLICT", None, "institution_student_id",
                                          f"Roll number {roll} already belongs to another student here.",
                                          {"enrolment_id": clash.id}))
                return
    elif owner is not None:
        os_ = owner.student
        same_person = os_.name_key == q["name_key"] and os_.date_of_birth == q["date_of_birth"]
        if by_apaar is not None and by_apaar.id == os_.id:
            target = owner
        elif by_apaar is None and same_person and (os_.apaar_id is None or not aid):
            # pending-APAAR student re-submitted (possibly now with an APAAR ID): same student
            target, student = owner, os_
        else:
            p.findings.append(finding("D002_ROLL_CONFLICT", None, "institution_student_id",
                                      f"Roll number {roll} already belongs to a different student here.",
                                      {"enrolment_id": owner.id}))
            return

    p.student_id = student.id if student is not None else None
    p.enrolment_id = target.id if target is not None else None

    if target is not None and self_enrol is None:
        p.findings.append(finding("D001_EXISTING_RECORD", None, None,
                                  "Updates an existing enrolment; the previous values are kept in its history.",
                                  {"enrolment_id": target.id}))

    if student is not None and p.programme_id:
        dup = db.execute(
            select(Enrolment).where(
                Enrolment.student_id == student.id,
                Enrolment.programme_id == p.programme_id,
                Enrolment.academic_year == year,
            )
        ).scalar_one_or_none()
        if dup is not None and (target is None or dup.id != target.id):
            p.findings.append(finding("R009_DUPLICATE_ENROLMENT", None, "institution_student_id",
                                      f"This student is already enrolled in {q['programme_code']} {year} "
                                      f"under roll number {dup.institution_student_id}.",
                                      {"enrolment_id": dup.id}))

    if by_apaar is not None:
        if self_enrol is None and (by_apaar.name_key != q["name_key"] or by_apaar.date_of_birth != q["date_of_birth"]):
            diffs = []
            if by_apaar.name_key != q["name_key"]:
                diffs.append("name")
            if by_apaar.date_of_birth != q["date_of_birth"]:
                diffs.append("date of birth")
            p.findings.append(finding("D004_ATTR_CONFLICT", None, "full_name" if "name" in diffs else "date_of_birth",
                                      f"The register holds this APAAR ID with a different {' and '.join(diffs)}. "
                                      "The master record is not overwritten.",
                                      {"differs": diffs, "student_id": by_apaar.id}))
        others = db.execute(
            select(Enrolment).where(
                Enrolment.student_id == by_apaar.id,
                Enrolment.institution_id != institution.id,
                Enrolment.status.in_(OCCUPYING),
            )
        ).scalars().all()
        if others:
            p.xinst = [{"enrolment_id": e.id, "institution_id": e.institution_id} for e in others]
            p.findings.append(finding("D003_XINST_ACTIVE", None, "apaar_id",
                                      "This student has an active enrolment at another AICTE-approved institution.",
                                      {"count": len(others)}))

    if q["full_name"] and q["date_of_birth"]:
        exclude = {student.id} if student is not None else set()
        cands = identity.find_candidates(db, q["full_name"], q["date_of_birth"], q["gender"], aid,
                                         exclude_student_ids=exclude, institution_id=institution.id)
        if student is not None:
            cands = [c for c in cands if not identity.decided_different(db, student.id, c["student_id"])]
        p.candidates = cands
        strong = [c for c in cands if c["score"] >= identity.REVIEW_THRESHOLD]
        if strong:
            best = strong[0]
            p.findings.append(finding("D005_POSSIBLE_DUP_IDENTITY", None, "full_name",
                                      f"May be the same person as an existing student record (match score {best['score']}).",
                                      {"score": best["score"], "weights": best["weights"], "candidates": len(strong)}))


# ---------------------------------------------------------------- commit


def add_revision(db: Session, entity_type: str, entity_id: str, version: int, changes: dict, reason: str, actor_id):
    db.add(RecordRevision(entity_type=entity_type, entity_id=entity_id, version=version, changes=changes,
                          reason=reason, actor_id=actor_id))


def _jsonable(v):
    return v.isoformat() if isinstance(v, date) else v


def _apaar_status(plan: RowPlan) -> str:
    if not plan.parsed["apaar_id"]:
        return "PENDING_EXEMPT"
    return {"OK": "VERIFIED", "NAME_MISMATCH": "MISMATCH", "DOB_MISMATCH": "MISMATCH",
            "NOT_FOUND": "NOT_FOUND", "INACTIVE": "NOT_FOUND"}.get(plan.adapter_status or "", "UNVERIFIED")


def _set_fields(obj, values: dict) -> dict:
    changes = {}
    for k, v in values.items():
        old = getattr(obj, k)
        if old != v:
            changes[k] = {"old": _jsonable(old), "new": _jsonable(v)}
            setattr(obj, k, v)
    return changes


def commit_values(
    db: Session,
    plan: RowPlan,
    *,
    institution: Institution,
    academic_year: str,
    actor: Actor | None,
    source: str,
    reason: str,
    import_job_id: str | None = None,
    status: str | None = None,
    allow_master_update: bool = False,
) -> Enrolment:
    """Write one validated row (must not have ERROR findings). Returns the enrolment."""
    assert plan.status != "ERROR", "rows with ERROR findings are never committed"
    q = plan.parsed
    actor_id = getattr(actor, "id", None)
    year = q["academic_year"] or academic_year
    new_student = plan.student_id is None
    attrs = {k: q[k] for k in STUDENT_FIELDS}
    attrs["name_key"] = name_key(q["full_name"])

    if new_student:
        st = Student(
            apaar_id=q["apaar_id"],
            apaar_ref=apaar_ref(q["apaar_id"]),
            apaar_status=_apaar_status(plan),
            apaar_pending_reason=None if q["apaar_id"] else q["apaar_pending_reason"],
            version=1,
            **attrs,
        )
        db.add(st)
        db.flush()
        add_revision(db, "student", st.id, 1, {k: {"old": None, "new": _jsonable(v)} for k, v in attrs.items()
                                                 if k != "name_key" and v is not None}, reason, actor_id)
    else:
        st = db.get(Student, plan.student_id)
        changes = {}
        if q["apaar_id"] and st.apaar_id != q["apaar_id"]:
            changes.update(_set_fields(st, {"apaar_id": q["apaar_id"], "apaar_ref": apaar_ref(q["apaar_id"]),
                                            "apaar_status": _apaar_status(plan), "apaar_pending_reason": None}))
            changes.pop("apaar_ref", None)
            if "apaar_id" in changes:
                changes["apaar_id"] = {"old": "(none)" if not changes["apaar_id"]["old"] else "(previous ID)",
                                       "new": "(APAAR ID attached)"}
        # Master attributes: only the owning institution may update them, and never over a D004 conflict.
        elsewhere = db.execute(
            select(Enrolment.id).where(Enrolment.student_id == st.id, Enrolment.institution_id != institution.id)
        ).first()
        if allow_master_update or (elsewhere is None and not plan.has("D004_ATTR_CONFLICT")):
            changes.update(_set_fields(st, attrs))
            changes.pop("name_key", None)
        if changes:
            st.version += 1
            add_revision(db, "student", st.id, st.version, changes, reason, actor_id)

    enrol_values = {
        "programme_id": plan.programme_id,
        "academic_year": year,
        "institution_student_id": q["institution_student_id"],
        "seat_category": q["seat_category"],
        "admission_date": q["admission_date"],
    }
    if plan.enrolment_id:
        en = db.get(Enrolment, plan.enrolment_id)
        changes = _set_fields(en, enrol_values)
        if changes:
            en.version += 1
            changes = {k: v for k, v in changes.items()}
            add_revision(db, "enrolment", en.id, en.version, changes, reason, actor_id)
        action = "enrolment.update"
    else:
        en = Enrolment(
            student_id=st.id,
            institution_id=institution.id,
            source=source,
            import_job_id=import_job_id,
            status=status or "ACTIVE",
            version=1,
            **enrol_values,
        )
        db.add(en)
        db.flush()
        add_revision(db, "enrolment", en.id, 1,
                     {k: {"old": None, "new": _jsonable(v)} for k, v in dict(enrol_values, status=en.status).items()},
                     reason, actor_id)
        action = "enrolment.create"
    db.flush()
    audit.record(db, actor, action, "enrolment", en.id,
                 detail={"source": source, "apaar_ref": st.apaar_ref, "row_status": plan.status},
                 institution_id=institution.id)

    _open_review_issues(db, plan, st, en, institution, year, actor)
    if new_student and plan.candidates:
        identity.record_candidates(db, st, plan.candidates)
    return en


def _open_review_issues(db, plan: RowPlan, st: Student, en: Enrolment, institution, year, actor):
    prog = db.get(Programme, en.programme_id)
    own_side = {
        "institution_id": institution.id,
        "institution_name": institution.name,
        "enrolment_id": en.id,
        "institution_student_id": en.institution_student_id,
        "programme_code": prog.code,
        "status": en.status,
        "academic_year": en.academic_year,
    }
    for f in plan.findings:
        if f["severity"] != "REVIEW":
            continue
        rid = f["rule_id"]
        common = dict(rule_id=rid, institution_id=institution.id, academic_year=year, actor=actor, severity="REVIEW")
        if rid in ("R004_APAAR_PENDING", "R007_APAAR_MISMATCH", "D004_ATTR_CONFLICT", "R011_DATE_UNUSUAL",
                   "R008_APAAR_UNVERIFIED", "F003_POSSIBLE_DUP_IN_FILE", "D001_EXISTING_RECORD"):
            issues.open_or_update(
                db, entity_type="ENROLMENT", entity_id=en.id, dedupe_key=f"{en.id}",
                message=f"{en.institution_student_id} ({st.full_name}): {f['message']}",
                evidence={"finding": f, "student_id": st.id, "student_name": st.full_name, "sides": [own_side]},
                **common,
            )
        elif rid == "D003_XINST_ACTIVE":
            for other in plan.xinst:
                oe = db.get(Enrolment, other["enrolment_id"])
                oi = db.get(Institution, oe.institution_id)
                op = db.get(Programme, oe.programme_id)
                issues.open_or_update(
                    db, entity_type="STUDENT", entity_id=st.id,
                    dedupe_key=":".join(sorted([en.id, oe.id])),
                    related_institution_ids=[oe.institution_id],
                    message="This student holds an active enrolment at two AICTE-approved institutions.",
                    evidence={
                        "student_id": st.id,
                        "student_name": st.full_name,
                        "apaar_ref": st.apaar_ref,
                        "sides": [
                            own_side,
                            {"institution_id": oi.id, "institution_name": oi.name, "enrolment_id": oe.id,
                             "institution_student_id": oe.institution_student_id, "programme_code": op.code,
                             "status": oe.status, "academic_year": oe.academic_year},
                        ],
                    },
                    **common,
                )
        elif rid == "D005_POSSIBLE_DUP_IDENTITY":
            for c in plan.candidates:
                if c["score"] < identity.REVIEW_THRESHOLD:
                    continue
                other = db.get(Student, c["student_id"])
                oe = db.execute(select(Enrolment).where(Enrolment.student_id == other.id)
                                .order_by(Enrolment.created_at.desc())).scalars().first()
                other_side = {"institution_id": oe.institution_id if oe else None, "student_id": other.id,
                              "student_name": other.full_name, "status": oe.status if oe else None,
                              "academic_year": oe.academic_year if oe else None,
                              "apaar_status": other.apaar_status}
                if oe:
                    oi = db.get(Institution, oe.institution_id)
                    other_side.update(institution_name=oi.name, enrolment_id=oe.id,
                                      institution_student_id=oe.institution_student_id)
                a, b = identity.ordered_pair(st.id, other.id)
                issues.open_or_update(
                    db, entity_type="IDENTITY_PAIR", entity_id=f"{a}:{b}", dedupe_key=f"{a}:{b}",
                    message=f"{st.full_name} may be the same person as another student record (score {c['score']}).",
                    evidence={"score": c["score"], "weights": c["weights"], "student_a": a, "student_b": b,
                              "sides": [dict(own_side, student_id=st.id, student_name=st.full_name,
                                             apaar_status=st.apaar_status), other_side]},
                    **common,
                )
