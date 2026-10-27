"""Dashboards and CSV reports (all figures computed from the database)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..csvout import csv_response
from ..db import get_db
from ..models import Institution
from ..security import AICTE_ROLES, INST_ROLES, Actor, ApiError, current_actor, require_roles
from . import analytics

router = APIRouter(prefix="/api/v1", tags=["dashboards"])


@router.get("/dashboard/national")
def national(academic_year: str = settings.current_year, state: str | None = None, discipline: str | None = None,
             actor: Actor = Depends(require_roles(*AICTE_ROLES)), db: Session = Depends(get_db)):
    return analytics.national(db, academic_year, state or None, discipline or None)


@router.get("/dashboard/institution")
def institution(academic_year: str = settings.current_year, institution_id: str | None = None,
                actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    if actor.is_institution:
        if institution_id and institution_id != actor.institution_id:
            raise ApiError(403, "You can only view your own institution's dashboard.")
        institution_id = actor.institution_id
    elif actor.role not in AICTE_ROLES or not institution_id:
        raise ApiError(403, "Your role does not allow this action.")
    inst = db.get(Institution, institution_id)
    if inst is None:
        raise ApiError(404, "Not found.")
    return analytics.institution(db, inst, academic_year)


@router.get("/dashboard/review-priority")
def review_priority(academic_year: str = settings.current_year, actor: Actor = Depends(require_roles(*AICTE_ROLES)),
                    db: Session = Depends(get_db)):
    return analytics.review_priority(db, academic_year)


def _scope(actor: Actor) -> list[str] | None:
    if actor.is_institution:
        return [actor.institution_id]
    if actor.role in AICTE_ROLES:
        return None
    raise ApiError(403, "Your role does not allow this action.")


@router.get("/reports/intake-utilisation.csv")
def intake_report(academic_year: str = settings.current_year, actor: Actor = Depends(current_actor),
                  db: Session = Depends(get_db)):
    rows = analytics.intake_rows(db, academic_year, _scope(actor))
    audit.record(db, actor, "report.export", "report", "intake-utilisation", detail={"year": academic_year, "rows": len(rows)})
    db.commit()
    return csv_response(f"intake_utilisation_{academic_year}.csv", analytics.INTAKE_HEADERS, rows)


@router.get("/reports/nationality.csv")
def nationality_report(academic_year: str = settings.current_year, actor: Actor = Depends(current_actor),
                       db: Session = Depends(get_db)):
    rows = analytics.nationality_rows(db, academic_year, _scope(actor))
    audit.record(db, actor, "report.export", "report", "nationality", detail={"year": academic_year, "rows": len(rows)})
    db.commit()
    return csv_response(f"nationality_{academic_year}.csv",
                        ["aicte_code", "institution", "programme_code", "academic_year", "nationality_status",
                         "seat_category", "enrolled"], rows)


@router.get("/reports/review-priority.csv")
def priority_report(academic_year: str = settings.current_year, actor: Actor = Depends(require_roles(*AICTE_ROLES)),
                    db: Session = Depends(get_db)):
    data = analytics.review_priority(db, academic_year)
    rows = [[r["aicte_code"], r["institution_name"], r["academic_year"], r["score"], r["band"],
             " | ".join(f"{s['points']}: {s['sentence']}" for s in r["signals"]), data["disclaimer"]]
            for r in data["items"]]
    audit.record(db, actor, "report.export", "report", "review-priority", detail={"year": academic_year})
    db.commit()
    return csv_response(f"review_priority_{academic_year}.csv",
                        ["aicte_code", "institution", "academic_year", "score", "band", "signals", "note"], rows)


__all__ = ["router", "INST_ROLES"]
