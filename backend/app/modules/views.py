"""Role-aware serialisation of records. APAAR IDs are masked unless the viewer may see them."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Enrolment, Student
from ..security import Actor, can_see_full_apaar, mask_apaar


def student_view(st: Student, actor: Actor, owning_institution_ids: set[str]) -> dict:
    full = can_see_full_apaar(actor, owning_institution_ids) or (actor.student_id == st.id)
    sensitive = full and actor.role != "AICTE_ANALYST"
    return {
        "id": st.id,
        "full_name": st.full_name,
        "date_of_birth": st.date_of_birth.isoformat(),
        "gender": st.gender,
        "nationality_status": st.nationality_status,
        "citizenship_country": st.citizenship_country,
        "apaar_id": st.apaar_id if full else mask_apaar(st.apaar_id),
        "apaar_masked": bool(st.apaar_id) and not full,
        "apaar_status": st.apaar_status,
        "apaar_pending_reason": st.apaar_pending_reason,
        "apaar_check_mode": "SIMULATED",
        "social_category": st.social_category if sensitive else None,
        "email": st.email if sensitive else None,
        "version": st.version,
    }


def enrolment_view(en: Enrolment, actor: Actor) -> dict:
    return {
        "id": en.id,
        "institution_id": en.institution_id,
        "institution_name": en.institution.name,
        "aicte_code": en.institution.aicte_code,
        "programme_id": en.programme_id,
        "programme_code": en.programme.code,
        "programme_name": en.programme.name,
        "academic_year": en.academic_year,
        "institution_student_id": en.institution_student_id,
        "seat_category": en.seat_category,
        "admission_date": en.admission_date.isoformat(),
        "status": en.status,
        "source": en.source,
        "version": en.version,
        "created_at": en.created_at.isoformat(),
        "updated_at": en.updated_at.isoformat() if en.updated_at else None,
        "student": student_view(en.student, actor, {en.institution_id}),
    }


def row_from_enrolment(db: Session, en: Enrolment) -> dict:
    """Template-shaped row for re-validation of a committed record."""
    st = en.student
    return {
        "apaar_id": st.apaar_id or "",
        "institution_student_id": en.institution_student_id,
        "full_name": st.full_name,
        "date_of_birth": st.date_of_birth.isoformat(),
        "gender": st.gender,
        "nationality_status": st.nationality_status,
        "citizenship_country": st.citizenship_country or "",
        "programme_code": en.programme.code,
        "academic_year": en.academic_year,
        "seat_category": en.seat_category,
        "admission_date": en.admission_date.isoformat(),
        "social_category": st.social_category or "",
        "email": st.email or "",
        "apaar_pending_reason": st.apaar_pending_reason or "",
    }
