"""Bulk import API: templates, upload/preview, row corrections, exclusions, bulk fix, commit, report."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..db import get_db
from ..models import ImportJob, ImportRow, Institution, Programme
from ..security import INST_ROLES, Actor, ApiError, require_roles
from . import intake
from .normalize import valid_academic_year

router = APIRouter(prefix="/api/v1/imports", tags=["imports"])
inst_user = require_roles(*INST_ROLES)


def job_view(job: ImportJob) -> dict:
    return {
        "id": job.id, "institution_id": job.institution_id, "academic_year": job.academic_year,
        "filename": job.filename, "file_sha256": job.file_sha256, "status": job.status,
        "total_rows": job.total_rows, "committed_rows": job.committed_rows, "summary": job.summary,
        "created_at": job.created_at.isoformat(), "updated_at": job.updated_at.isoformat(),
    }


def row_view(r: ImportRow) -> dict:
    return {"row_no": r.row_no, "spreadsheet_row": r.row_no + 2, "status": r.status, "data": r.data,
            "original": r.original, "findings": r.findings, "corrected": r.corrected, "enrolment_id": r.enrolment_id}


@router.get("/template.csv")
def template_csv(actor: Actor = Depends(inst_user)):
    return Response(intake.template_csv(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="student_template.csv"'})


@router.get("/template.xlsx")
def template_xlsx(academic_year: str = settings.current_year, actor: Actor = Depends(inst_user),
                  db: Session = Depends(get_db)):
    codes = sorted(db.execute(select(Programme.code).where(Programme.institution_id == actor.institution_id)).scalars())
    return Response(intake.template_xlsx(codes, academic_year),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="student_template.xlsx"'})


@router.post("")
async def upload(file: UploadFile = File(...), academic_year: str = Form(settings.current_year),
                 actor: Actor = Depends(inst_user), db: Session = Depends(get_db)):
    if not valid_academic_year(academic_year):
        raise ApiError(422, "Academic year must look like 2026-27.", field="academic_year")
    content = await file.read(settings.max_upload_bytes + 1)
    inst = db.get(Institution, actor.institution_id)
    job = intake.create_job(db, actor, inst, academic_year, file.filename or "upload", content)
    db.commit()
    return job_view(job)


@router.get("")
def list_jobs(actor: Actor = Depends(inst_user), db: Session = Depends(get_db)):
    jobs = db.execute(select(ImportJob).where(ImportJob.institution_id == actor.institution_id)
                      .order_by(ImportJob.created_at.desc()).limit(50)).scalars()
    return [job_view(j) for j in jobs]


@router.get("/{job_id}")
def get_job(job_id: str, status: str | None = None, page: int = 1, page_size: int = 50,
            actor: Actor = Depends(inst_user), db: Session = Depends(get_db)):
    job = intake.get_job(db, job_id, actor)
    page_size = max(1, min(page_size, 200))
    q = select(ImportRow).where(ImportRow.job_id == job.id)
    if status:
        q = q.where(ImportRow.status.in_(status.split(",")))
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar()
    rows = db.execute(q.order_by(ImportRow.row_no).offset((max(page, 1) - 1) * page_size).limit(page_size)).scalars()
    return dict(job_view(job), rows=[row_view(r) for r in rows], page=page, page_size=page_size, total=total)


class RowPatch(BaseModel):
    changes: dict[str, str]


@router.patch("/{job_id}/rows/{row_no}")
def patch_row(job_id: str, row_no: int, body: RowPatch, actor: Actor = Depends(inst_user),
              db: Session = Depends(get_db)):
    job = intake.get_job(db, job_id, actor)
    row = intake.update_row(db, job, row_no, body.changes, actor)
    db.commit()
    return {"row": row_view(row), "job": job_view(job)}


class ExcludeIn(BaseModel):
    excluded: bool = True


@router.post("/{job_id}/rows/{row_no}/exclude")
def exclude(job_id: str, row_no: int, body: ExcludeIn, actor: Actor = Depends(inst_user),
            db: Session = Depends(get_db)):
    job = intake.get_job(db, job_id, actor)
    row = intake.exclude_row(db, job, row_no, body.excluded, actor)
    db.commit()
    return {"row": row_view(row), "job": job_view(job)}


class BulkFixIn(BaseModel):
    field: str
    from_value: str = ""
    to_value: str

    model_config = {"populate_by_name": True}


@router.post("/{job_id}/bulk-fix")
def bulk_fix(job_id: str, body: dict, actor: Actor = Depends(inst_user), db: Session = Depends(get_db)):
    field = body.get("field")
    to = body.get("to", body.get("to_value"))
    frm = body.get("from", body.get("from_value", ""))
    if not field or to is None:
        raise ApiError(422, "Send field, from and to.")
    job = intake.get_job(db, job_id, actor)
    n = intake.bulk_fix(db, job, field, str(frm), str(to), actor)
    db.commit()
    return {"updated_rows": n, "job": job_view(job)}


@router.post("/{job_id}/commit")
def commit(job_id: str, actor: Actor = Depends(inst_user), db: Session = Depends(get_db)):
    job = intake.get_job(db, job_id, actor)
    result = intake.commit_job(db, job, actor)
    return dict(result, job=job_view(job))


@router.post("/{job_id}/discard")
def discard(job_id: str, actor: Actor = Depends(inst_user), db: Session = Depends(get_db)):
    job = intake.get_job(db, job_id, actor)
    intake.discard_job(db, job, actor)
    db.commit()
    return job_view(job)


@router.get("/{job_id}/report.csv")
def report(job_id: str, actor: Actor = Depends(inst_user), db: Session = Depends(get_db)):
    job = intake.get_job(db, job_id, actor)
    audit.record(db, actor, "report.export", "import_job", job.id, detail={"report": "import_check"})
    return Response(intake.report_csv(db, job), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="check_report_{job.id[:8]}.csv"'})
