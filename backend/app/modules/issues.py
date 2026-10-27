"""Validation issues ("flags"): open/update with dedupe, review actions, capacity checks, redaction.

A flag means "a person should look". Nothing is auto-resolved except a capacity flag whose
measured condition disappears; that is logged as a SYSTEM event and can be reopened.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..models import Institution, IssueEvent, Notification, Programme, ValidationIssue
from ..security import Actor, ApiError
from . import events, ledger
from .rules import load_config, remediation_for

OPEN_STATES = ("OPEN", "CLARIFICATION_REQUESTED", "RESPONDED")
CLOSED_STATES = ("RESOLVED", "DISMISSED")
WITHHELD = "Another AICTE-approved institution (identity withheld)"


def add_event(db: Session, issue: ValidationIssue, actor_id, actor_role: str, action: str, note: str | None = None):
    db.add(IssueEvent(issue_id=issue.id, actor_id=actor_id, actor_role=actor_role, action=action, note=note))


def _notify(db: Session, issue: ValidationIssue, text: str) -> None:
    link = f"/issues/{issue.id}"
    for inst in [issue.institution_id, *issue.related_institution_ids]:
        if inst:
            db.add(Notification(institution_id=inst, kind="issue", message=text, link=link))
    db.add(Notification(audience_role="AICTE_ADMIN", kind="issue", message=text, link=link))


def _publish(db: Session, issue: ValidationIssue, kind: str) -> None:
    events.publish(
        db,
        kind,
        {"issue_id": issue.id, "rule_id": issue.rule_id, "status": issue.status},
        [issue.institution_id, *issue.related_institution_ids],
    )


def open_or_update(
    db: Session,
    *,
    rule_id: str,
    entity_type: str,
    entity_id: str,
    dedupe_key: str,
    institution_id: str | None,
    message: str,
    evidence: dict,
    academic_year: str | None = None,
    related_institution_ids: list[str] | None = None,
    severity: str = "REVIEW",
    actor: Actor | None = None,
) -> ValidationIssue:
    """Open a flag, or refresh the evidence of an open one with the same dedupe key (never duplicates)."""
    existing = db.execute(
        select(ValidationIssue)
        .where(ValidationIssue.rule_id == rule_id, ValidationIssue.dedupe_key == dedupe_key)
        .order_by(ValidationIssue.created_at.desc())
    ).scalars().first()
    if existing is not None:
        if existing.status in OPEN_STATES:
            existing.evidence = evidence
            existing.message = message
            db.flush()
            _publish(db, existing, "issue.updated")
        return existing
    issue = ValidationIssue(
        rule_id=rule_id,
        severity=severity,
        entity_type=entity_type,
        entity_id=entity_id,
        dedupe_key=dedupe_key,
        institution_id=institution_id,
        related_institution_ids=related_institution_ids or [],
        academic_year=academic_year,
        message=message,
        evidence=evidence,
        remediation=remediation_for(rule_id),
        status="OPEN",
    )
    db.add(issue)
    db.flush()
    add_event(db, issue, getattr(actor, "id", None), getattr(actor, "role", "SYSTEM") or "SYSTEM", "OPENED")
    _notify(db, issue, f"New flag {rule_id}: {message}")
    audit.record(db, actor, "issue.open", "issue", issue.id, detail={"rule_id": rule_id}, institution_id=institution_id)
    _publish(db, issue, "issue.opened")
    return issue


# ---------------------------------------------------------------- capacity (C001 / C002)


def _strip(pos: dict) -> dict:
    return {k: v for k, v in pos.items() if k not in ("programme_id",)}


def run_capacity_checks(db: Session, programme_id: str, academic_year: str, actor: Actor | None = None) -> dict:
    """Re-measure a programme-year; open/refresh C001/C002, auto-close them when the condition disappears."""
    db.flush()
    cfg = load_config(db)
    prog = db.get(Programme, programme_id)
    pos = ledger.position(db, programme_id, academic_year)
    base_ev = {
        "programme_code": prog.code,
        "programme_name": prog.name,
        "academic_year": academic_year,
        "position": _strip(pos),
    }
    checks = [
        (
            "C001_EXCESS_INTAKE",
            f"{programme_id}:{academic_year}",
            pos["excess_over_intake"],
            lambda n: f"{prog.code} {academic_year}: {pos['within_intake_enrolled']} within-intake enrolments "
            f"against approved intake {pos['approved_intake']} (+{n}).",
        )
    ]
    for cat, sn in pos["supernumerary"].items():
        checks.append(
            (
                "C002_SUPERNUMERARY_CAP",
                f"{programme_id}:{academic_year}:{cat}",
                sn["excess"],
                lambda n, cat=cat, sn=sn: f"{prog.code} {academic_year}: supernumerary {cat} {sn['enrolled']}/{sn['cap']} "
                f"(+{n} over cap).",
            )
        )
    for rule_id, key, excess, msg in checks:
        rc = cfg[rule_id]
        existing = db.execute(
            select(ValidationIssue)
            .where(ValidationIssue.rule_id == rule_id, ValidationIssue.dedupe_key == key)
            .order_by(ValidationIssue.created_at.desc())
        ).scalars().first()
        ev = dict(base_ev, excess=excess)
        if rule_id == "C002_SUPERNUMERARY_CAP":
            ev["seat_category"] = key.rsplit(":", 1)[1]
        if excess > 0 and rc.enabled:
            if existing is not None and existing.status in CLOSED_STATES:
                prev = (existing.evidence or {}).get("excess", 0)
                if excess > prev:
                    existing.status = "OPEN"
                    existing.evidence = ev
                    existing.message = msg(excess)
                    add_event(db, existing, None, "SYSTEM", "SYSTEM_REOPENED",
                              f"Excess rose from {prev} to {excess} after the flag was closed.")
                    _publish(db, existing, "issue.updated")
                continue
            open_or_update(
                db,
                rule_id=rule_id,
                entity_type="PROGRAMME_YEAR",
                entity_id=key,
                dedupe_key=key,
                institution_id=prog.institution_id,
                message=msg(excess),
                evidence=ev,
                academic_year=academic_year,
                severity=rc.severity,
                actor=actor,
            )
        elif existing is not None and existing.status in OPEN_STATES:
            existing.status = "RESOLVED"
            existing.resolved_by = None
            existing.resolution_note = "Condition no longer measured: the seat position is within the rules."
            existing.evidence = ev
            add_event(db, existing, None, "SYSTEM", "SYSTEM_AUTO_RESOLVED", existing.resolution_note)
            audit.record(db, None, "issue.auto_resolve", "issue", existing.id,
                         detail={"rule_id": rule_id}, institution_id=prog.institution_id)
            _publish(db, existing, "issue.updated")
    events.publish(
        db,
        "seat.changed",
        {"programme_id": programme_id, "academic_year": academic_year, "position": _strip(pos)},
        [prog.institution_id],
    )
    return pos


# ---------------------------------------------------------------- visibility & actions


def visible(actor: Actor, issue: ValidationIssue) -> bool:
    if actor.role in ("AICTE_ADMIN", "AICTE_ANALYST", "AUDITOR"):
        return True
    if actor.is_institution:
        return actor.institution_id == issue.institution_id or actor.institution_id in issue.related_institution_ids
    return False


def allowed_actions(actor: Actor, issue: ValidationIssue) -> list[str]:
    acts: list[str] = []
    if actor.role == "AICTE_ADMIN":
        if issue.status in OPEN_STATES:
            if issue.status != "CLARIFICATION_REQUESTED":
                acts.append("REQUEST_CLARIFICATION")
            acts += ["RESOLVE", "DISMISS"]
        else:
            acts.append("REOPEN")
    elif actor.role in ("INST_ADMIN", "INST_STAFF") and visible(actor, issue):
        if issue.status in OPEN_STATES:
            acts.append("RESPOND")
            if (
                issue.rule_id[0] in "RFD"
                and issue.rule_id != "D003_XINST_ACTIVE"
                and issue.institution_id == actor.institution_id
                and not issue.related_institution_ids
            ):
                acts.append("RESOLVE")
    return acts


NEXT_STATE = {
    "REQUEST_CLARIFICATION": "CLARIFICATION_REQUESTED",
    "RESPOND": "RESPONDED",
    "RESOLVE": "RESOLVED",
    "DISMISS": "DISMISSED",
    "REOPEN": "OPEN",
}


def apply_action(db: Session, issue: ValidationIssue, actor: Actor, action: str, note: str | None) -> ValidationIssue:
    if not visible(actor, issue):
        raise ApiError(404, "Not found.")
    if action not in NEXT_STATE:
        raise ApiError(422, f"Unknown action {action}.")
    if action not in allowed_actions(actor, issue):
        raise ApiError(403, f"You cannot {action.replace('_', ' ').lower()} this flag in its current state.")
    if not (note or "").strip():
        raise ApiError(422, "Add a note explaining the action.", field="note")
    issue.status = NEXT_STATE[action]
    if action in ("RESOLVE", "DISMISS"):
        issue.resolution_note = note
        issue.resolved_by = actor.id
    if action == "REOPEN":
        issue.resolution_note = None
        issue.resolved_by = None
    add_event(db, issue, actor.id, actor.role, action, note)
    audit.record(db, actor, f"issue.{action.lower()}", "issue", issue.id, detail={"rule_id": issue.rule_id})
    _notify(db, issue, f"Flag {issue.rule_id} {NEXT_STATE[action].replace('_', ' ').lower()}: {note}")
    _publish(db, issue, "issue.updated")
    db.flush()
    return issue


def redact(db: Session, issue: ValidationIssue, actor: Actor) -> dict:
    """Issue as the viewer may see it. Institution viewers never see another institution's identity."""
    ev = dict(issue.evidence or {})
    sides = ev.get("sides")
    if sides is not None and actor.is_institution:
        red = []
        for side in sides:
            if side.get("institution_id") == actor.institution_id:
                red.append(dict(side, own=True))
            else:
                red.append(
                    {
                        "own": False,
                        "institution": WITHHELD,
                        "status": side.get("status"),
                        "academic_year": side.get("academic_year"),
                    }
                )
        ev["sides"] = red
    elif sides is not None:
        ev["sides"] = [dict(s, own=False) for s in sides]
    inst_name = None
    if issue.institution_id:
        inst = db.get(Institution, issue.institution_id)
        if inst and (not actor.is_institution or actor.institution_id == issue.institution_id):
            inst_name = inst.name
    related = issue.related_institution_ids if not actor.is_institution else []
    return {
        "id": issue.id,
        "rule_id": issue.rule_id,
        "severity": issue.severity,
        "entity_type": issue.entity_type,
        "entity_id": issue.entity_id,
        "institution_id": issue.institution_id if not actor.is_institution or actor.institution_id == issue.institution_id else None,
        "institution_name": inst_name if inst_name else (WITHHELD if issue.institution_id else None),
        "related_institution_ids": related,
        "academic_year": issue.academic_year,
        "message": issue.message,
        "evidence": ev,
        "remediation": issue.remediation,
        "status": issue.status,
        "resolution_note": issue.resolution_note,
        "created_at": issue.created_at.isoformat(),
        "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
        "allowed_actions": allowed_actions(actor, issue),
    }
