"""SQLAlchemy models. UUID string primary keys; schema avoids SQLite-only SQL.

Additive columns beyond the build brief (documented in docs/API_DESIGN.md):
created_at/updated_at on mutable tables, users.locked_until, students index on date_of_birth.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, UTCDateTime, utcnow


def _uuid() -> str:
    return str(uuid.uuid4())


def pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=_uuid)


def created() -> Mapped[datetime]:
    return mapped_column(UTCDateTime, default=utcnow, nullable=False)


def updated() -> Mapped[datetime]:
    return mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Institution(Base):
    __tablename__ = "institutions"
    id: Mapped[str] = pk()
    aicte_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    short_name: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(60), nullable=False)
    region: Mapped[str] = mapped_column(String(40), nullable=False)
    institution_type: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = created()
    __table_args__ = (
        CheckConstraint("institution_type IN ('ENGINEERING','MANAGEMENT','PGDM')", name="ck_inst_type"),
    )


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = pk()
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    institution_id: Mapped[str | None] = mapped_column(ForeignKey("institutions.id"))
    student_id: Mapped[str | None] = mapped_column(ForeignKey("students.id"))
    organisation: Mapped[str | None] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = created()
    institution: Mapped[Institution | None] = relationship()


class Programme(Base):
    __tablename__ = "programmes"
    id: Mapped[str] = pk()
    institution_id: Mapped[str] = mapped_column(ForeignKey("institutions.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    discipline: Mapped[str] = mapped_column(String(30), nullable=False)
    institution: Mapped[Institution] = relationship()
    __table_args__ = (
        UniqueConstraint("institution_id", "code"),
        CheckConstraint("level IN ('DIPLOMA','UG','PG')", name="ck_prog_level"),
        CheckConstraint(
            "discipline IN ('ENGINEERING','MANAGEMENT','COMPUTER_APPLICATIONS')", name="ck_prog_discipline"
        ),
    )


class ApprovedIntake(Base):
    __tablename__ = "approved_intakes"
    id: Mapped[str] = pk()
    programme_id: Mapped[str] = mapped_column(ForeignKey("programmes.id"), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(7), nullable=False)
    approved_intake: Mapped[int] = mapped_column(Integer, nullable=False)
    approval_reference: Mapped[str] = mapped_column(String(100), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    submitted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = updated()
    programme: Mapped[Programme] = relationship()
    quotas: Mapped[list[SupernumeraryQuota]] = relationship(back_populates="intake")
    __table_args__ = (
        UniqueConstraint("programme_id", "academic_year"),
        CheckConstraint("approved_intake >= 0", name="ck_intake_nonneg"),
    )


class SupernumeraryQuota(Base):
    __tablename__ = "supernumerary_quotas"
    id: Mapped[str] = pk()
    intake_id: Mapped[str] = mapped_column(ForeignKey("approved_intakes.id"), nullable=False)
    seat_category: Mapped[str] = mapped_column(String(20), nullable=False)
    cap_seats: Mapped[int] = mapped_column(Integer, nullable=False)
    percent_basis: Mapped[float | None] = mapped_column(Float)
    rule_source: Mapped[str] = mapped_column(String(300), nullable=False)
    intake: Mapped[ApprovedIntake] = relationship(back_populates="quotas")
    __table_args__ = (UniqueConstraint("intake_id", "seat_category"),)


class Student(Base):
    __tablename__ = "students"
    id: Mapped[str] = pk()
    apaar_id: Mapped[str | None] = mapped_column(String(12), unique=True)
    apaar_ref: Mapped[str | None] = mapped_column(String(16), index=True)
    apaar_status: Mapped[str] = mapped_column(String(20), nullable=False, default="UNVERIFIED")
    apaar_pending_reason: Mapped[str | None] = mapped_column(String(30))
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_key: Mapped[str] = mapped_column(String(200), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    gender: Mapped[str] = mapped_column(String(1), nullable=False)
    nationality_status: Mapped[str] = mapped_column(String(10), nullable=False)
    citizenship_country: Mapped[str | None] = mapped_column(String(60))
    social_category: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = updated()
    enrolments: Mapped[list[Enrolment]] = relationship(back_populates="student")
    __table_args__ = (
        Index("ix_students_name_dob", "name_key", "date_of_birth"),
        Index("ix_students_dob", "date_of_birth"),
        CheckConstraint(
            "apaar_status IN ('UNVERIFIED','VERIFIED','MISMATCH','NOT_FOUND','PENDING_EXEMPT')",
            name="ck_apaar_status",
        ),
        CheckConstraint("nationality_status IN ('INDIAN','NRI','OCI','FN')", name="ck_nationality"),
    )


class Enrolment(Base):
    __tablename__ = "enrolments"
    id: Mapped[str] = pk()
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), nullable=False)
    institution_id: Mapped[str] = mapped_column(ForeignKey("institutions.id"), nullable=False)
    programme_id: Mapped[str] = mapped_column(ForeignKey("programmes.id"), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(7), nullable=False)
    institution_student_id: Mapped[str] = mapped_column(String(50), nullable=False)
    seat_category: Mapped[str] = mapped_column(String(20), nullable=False)
    admission_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    import_job_id: Mapped[str | None] = mapped_column(ForeignKey("import_jobs.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = updated()
    student: Mapped[Student] = relationship(back_populates="enrolments")
    programme: Mapped[Programme] = relationship()
    institution: Mapped[Institution] = relationship()
    __table_args__ = (
        UniqueConstraint("institution_id", "institution_student_id"),
        UniqueConstraint("student_id", "programme_id", "academic_year"),
        Index("ix_enrol_prog_year_status", "programme_id", "academic_year", "status"),
        CheckConstraint(
            "seat_category IN ('REGULAR','NRI','SN_FN_OCI','SN_CIWG','SN_TFW','SN_OTHER')", name="ck_seat"
        ),
        CheckConstraint(
            "status IN ('PROVISIONAL','ACTIVE','WITHDRAWN','TRANSFERRED_OUT','GRADUATED','CANCELLED')",
            name="ck_enrol_status",
        ),
        CheckConstraint("source IN ('IMPORT','API','MANUAL')", name="ck_enrol_source"),
    )


class ImportJob(Base):
    __tablename__ = "import_jobs"
    id: Mapped[str] = pk()
    institution_id: Mapped[str] = mapped_column(ForeignKey("institutions.id"), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(7), nullable=False)
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(25), nullable=False, default="PREVIEW")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    committed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = updated()
    __table_args__ = (
        CheckConstraint(
            "status IN ('PREVIEW','COMMITTING','PARTIALLY_COMMITTED','COMMITTED','DISCARDED')",
            name="ck_job_status",
        ),
        Index("ix_jobs_inst_sha", "institution_id", "file_sha256"),
    )


class ImportRow(Base):
    __tablename__ = "import_rows"
    id: Mapped[str] = pk()
    job_id: Mapped[str] = mapped_column(ForeignKey("import_jobs.id"), nullable=False)
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    original: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    findings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    corrected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enrolment_id: Mapped[str | None] = mapped_column(ForeignKey("enrolments.id"))
    __table_args__ = (
        UniqueConstraint("job_id", "row_no"),
        CheckConstraint(
            "status IN ('VALID','WARNING','REVIEW','ERROR','COMMITTED','EXCLUDED')", name="ck_row_status"
        ),
    )


class ValidationRule(Base):
    __tablename__ = "validation_rules"
    rule_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    remediation: Mapped[str] = mapped_column(Text, nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ValidationIssue(Base):
    __tablename__ = "validation_issues"
    id: Mapped[str] = pk()
    rule_id: Mapped[str] = mapped_column(ForeignKey("validation_rules.rule_id"), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    institution_id: Mapped[str | None] = mapped_column(ForeignKey("institutions.id"))
    related_institution_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    academic_year: Mapped[str | None] = mapped_column(String(7))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    remediation: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(25), nullable=False, default="OPEN")
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = updated()
    __table_args__ = (
        Index("ix_issue_rule_dedupe", "rule_id", "dedupe_key"),
        CheckConstraint(
            "status IN ('OPEN','CLARIFICATION_REQUESTED','RESPONDED','RESOLVED','DISMISSED')",
            name="ck_issue_status",
        ),
    )


class IssueEvent(Base):
    __tablename__ = "issue_events"
    id: Mapped[str] = pk()
    issue_id: Mapped[str] = mapped_column(ForeignKey("validation_issues.id"), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(36))
    actor_role: Mapped[str] = mapped_column(String(30), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = created()


class RecordRevision(Base):
    __tablename__ = "record_revisions"
    id: Mapped[str] = pk()
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    changes: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36))
    at: Mapped[datetime] = created()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36))
    actor_role: Mapped[str | None] = mapped_column(String(30))
    institution_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(80))
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (
        CheckConstraint("outcome IN ('SUCCESS','DENIED','FAILED')", name="ck_audit_outcome"),
        {"sqlite_autoincrement": True},
    )


class Credential(Base):
    __tablename__ = "credentials"
    id: Mapped[str] = pk()
    enrolment_id: Mapped[str] = mapped_column(ForeignKey("enrolments.id"), nullable=False)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), nullable=False)
    key_id: Mapped[str] = mapped_column(String(40), nullable=False)
    token: Mapped[str] = mapped_column(Text, nullable=False)
    issued_by: Mapped[str] = mapped_column(String(36), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="ACTIVE")
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revocation_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','REVOKED','SUPERSEDED')", name="ck_cred_status"),
    )


class VerificationRequest(Base):
    __tablename__ = "verification_requests"
    id: Mapped[str] = pk()
    requester_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    requester_org: Mapped[str] = mapped_column(String(200), nullable=False)
    student_id: Mapped[str | None] = mapped_column(ForeignKey("students.id"))
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    consent_decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    created_at: Mapped[datetime] = created()
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING_CONSENT','APPROVED','DENIED','NO_MATCH')", name="ck_vr_status"
        ),
    )


class CorrectionRequest(Base):
    __tablename__ = "correction_requests"
    id: Mapped[str] = pk()
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), nullable=False)
    enrolment_id: Mapped[str] = mapped_column(ForeignKey("enrolments.id"), nullable=False)
    institution_id: Mapped[str] = mapped_column(ForeignKey("institutions.id"), nullable=False)
    field: Mapped[str] = mapped_column(String(40), nullable=False)
    requested_value: Mapped[str] = mapped_column(String(300), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="OPEN")
    due_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = updated()
    __table_args__ = (
        CheckConstraint("status IN ('OPEN','ACCEPTED','REJECTED')", name="ck_cr_status"),
    )


class IdentityCandidate(Base):
    __tablename__ = "identity_candidates"
    id: Mapped[str] = pk()
    student_a: Mapped[str] = mapped_column(ForeignKey("students.id"), nullable=False)
    student_b: Mapped[str] = mapped_column(ForeignKey("students.id"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    weights: Mapped[list] = mapped_column(JSON, nullable=False)
    decision: Mapped[str | None] = mapped_column(String(20))
    decided_by: Mapped[str | None] = mapped_column(String(36))
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = updated()
    __table_args__ = (UniqueConstraint("student_a", "student_b"),)


class SeatCheckLog(Base):
    __tablename__ = "seat_check_logs"
    id: Mapped[str] = pk()
    programme_id: Mapped[str] = mapped_column(ForeignKey("programmes.id"), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(7), nullable=False)
    seat_category: Mapped[str] = mapped_column(String(20), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36))
    at: Mapped[datetime] = created()


class IntegrationClient(Base):
    __tablename__ = "integration_clients"
    id: Mapped[str] = pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    institution_id: Mapped[str] = mapped_column(ForeignKey("institutions.id"), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created()


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict] = mapped_column(JSON, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    created_at: Mapped[datetime] = created()


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = pk()
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    institution_id: Mapped[str | None] = mapped_column(ForeignKey("institutions.id"))
    audience_role: Mapped[str | None] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[str | None] = mapped_column(String(300))
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = created()


class SimApaarRegistry(Base):
    """Synthetic stand-in for the national APAAR registry. Used only by the simulated adapter."""

    __tablename__ = "sim_apaar_registry"
    apaar_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
