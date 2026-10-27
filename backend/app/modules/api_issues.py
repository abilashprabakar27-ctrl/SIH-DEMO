"""Flags (validation issues): list, detail with history, review actions, CSV export."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..csvout import csv_response
from ..db import get_db
from ..models import IssueEvent, ValidationIssue
from ..security import AICTE_ROLES, INST_ROLES, Actor, ApiError, current_actor
from . import issues

router = APIRouter(prefix="/api/v1/issues", tags=["issues"])
ISSUE_ROLES = (*AICTE_ROLES, *INST_ROLES, "AUDITOR")


def _issue_actor(actor: Actor = Depends(current_actor)) -> Actor:
    if actor.role not in ISSUE_ROLES:
        raise ApiError(403, "Your role cannot view flags.")
    return actor


def _query(db: Session, actor: Actor, status: str | None, rule_id: str | None, academic_year: str | None,
           institution_id: str | None) -> list[ValidationIssue]:
    if actor.is_institution and institution_id and institution_id != actor.institution_id:
        raise ApiError(403, "You can only list flags for your own institution.")
    q = select(ValidationIssue).order_by(ValidationIssue.created_at.desc())
    if status:
        q = q.where(ValidationIssue.status.in_(status.split(",")))
    if rule_id:
        q = q.where(ValidationIssue.rule_id.in_(rule_id.split(",")))
    if academic_year:
        q = q.where(ValidationIssue.academic_year == academic_year)
    rows = [i for i in db.execute(q).scalars() if issues.visible(actor, i)]
    if institution_id:
        rows = [i for i in rows if i.institution_id == institution_id or institution_id in i.related_institution_ids]
    return rows


@router.get("")
def list_issues(status: str | None = None, rule_id: str | None = None, academic_year: str | None = None,
                institution_id: str | None = None, page: int = 1, page_size: int = 50,
                actor: Actor = Depends(_issue_actor), db: Session = Depends(get_db)):
    rows = _query(db, actor, status, rule_id, academic_year, institution_id)
    page_size = max(1, min(page_size, 200))
    start = (max(page, 1) - 1) * page_size
    return {"items": [issues.redact(db, i, actor) for i in rows[start:start + page_size]], "total": len(rows),
            "page": page, "page_size": page_size}


@router.get("/export.csv")
def export(status: str | None = None, rule_id: str | None = None, academic_year: str | None = None,
           actor: Actor = Depends(_issue_actor), db: Session = Depends(get_db)):
    rows = _query(db, actor, status, rule_id, academic_year, None)
    out = []
    for i in rows:
        v = issues.redact(db, i, actor)
        out.append([v["id"], v["rule_id"], v["severity"], v["status"], v["academic_year"], v["institution_name"],
                    v["message"], v["resolution_note"], v["created_at"]])
    audit.record(db, actor, "report.export", "issues", None, detail={"report": "issues", "rows": len(out)})
    db.commit()
    return csv_response("flags.csv", ["id", "rule_id", "severity", "status", "academic_year", "institution",
                                      "message", "resolution_note", "created_at"], out)


def _load(db: Session, issue_id: str, actor: Actor) -> ValidationIssue:
    issue = db.get(ValidationIssue, issue_id)
    if issue is None or not issues.visible(actor, issue):
        raise ApiError(404, "Not found.")
    return issue


@router.get("/{issue_id}")
def get_issue(issue_id: str, actor: Actor = Depends(_issue_actor), db: Session = Depends(get_db)):
    issue = _load(db, issue_id, actor)
    evs = db.execute(select(IssueEvent).where(IssueEvent.issue_id == issue.id).order_by(IssueEvent.at)).scalars()
    view = issues.redact(db, issue, actor)
    view["history"] = [{"action": e.action, "actor_role": e.actor_role, "note": e.note, "at": e.at.isoformat(),
                        "by_you": e.actor_id == actor.id} for e in evs]
    return view


class ActionIn(BaseModel):
    action: str
    note: str = ""


@router.post("/{issue_id}/actions")
def act(issue_id: str, body: ActionIn, actor: Actor = Depends(_issue_actor), db: Session = Depends(get_db)):
    issue = _load(db, issue_id, actor)
    issues.apply_action(db, issue, actor, body.action, body.note)
    db.commit()
    return get_issue(issue_id, actor, db)
