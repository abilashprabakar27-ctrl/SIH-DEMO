"""Bootstrap an empty prototype database and add reliability metadata to an existing one.

Revision ID: 0001_prototype
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0001_prototype"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # A clean install gets the complete current prototype schema. Existing installations keep
    # their data; create_all only creates absent tables and never alters existing ones.
    from app import models  # noqa: F401
    from app.db import Base

    Base.metadata.create_all(bind)
    additions = {
        "students": [
            ("apaar_verified_mode", sa.String(16)),
            ("apaar_verified_at", sa.DateTime()),
            ("apaar_adapter_version", sa.String(40)),
        ],
        "enrolments": [("content_hash", sa.String(64))],
        "import_jobs": [
            ("locked_at", sa.DateTime()),
            ("lock_token", sa.String(36)),
            ("lock_expires_at", sa.DateTime()),
            ("version", sa.Integer(), "1"),
            ("rules_snapshot_id", sa.String(36)),
        ],
        "validation_issues": [
            ("explanation", sa.JSON(), "{}"),
            ("evidence_hash", sa.String(64), ""),
            ("rules_snapshot_id", sa.String(36)),
            ("resolution_outcome", sa.String(30)),
        ],
        "idempotency_records": [("expires_at", sa.DateTime())],
        "supernumerary_quotas": [
            ("rule_set_id", sa.String(36)),
            ("rule_set_version", sa.Integer()),
            ("entry_id", sa.String(36)),
            ("calc", sa.JSON(), "{}"),
            ("source", sa.String(12), "RULE_SET"),
            ("override_reason", sa.Text()),
            ("override_by", sa.String(36)),
            ("computed_at", sa.DateTime()),
            ("version", sa.Integer(), "1"),
        ],
    }
    for table, columns in additions.items():
        if not inspect(bind).has_table(table):
            continue
        existing = {c["name"] for c in inspect(bind).get_columns(table)}
        for item in columns:
            name, type_ = item[:2]
            if name not in existing:
                kwargs = {"nullable": True}
                if len(item) == 3:
                    kwargs["server_default"] = item[2]
                op.add_column(table, sa.Column(name, type_, **kwargs))
    if inspect(bind).has_table("supernumerary_quotas"):
        bind.execute(sa.text(
            "UPDATE supernumerary_quotas SET source='OVERRIDE', override_reason=rule_source "
            "WHERE rule_source NOT LIKE 'DEFAULT%'"
        ))
    for table, column, index_name in [
        ("enrolments", "content_hash", "ix_enrolments_content_hash"),
        ("import_jobs", "lock_expires_at", "ix_import_jobs_lock_expires_at"),
        ("idempotency_records", "expires_at", "ix_idempotency_records_expires_at"),
    ]:
        if inspect(bind).has_table(table) and column in {c["name"] for c in inspect(bind).get_columns(table)}:
            if index_name not in {i["name"] for i in inspect(bind).get_indexes(table)}:
                op.create_index(index_name, table, [column])


def downgrade() -> None:
    # Downgrading could discard lock and verification history. Keep this additive migration forward-only.
    raise RuntimeError("This data-preserving prototype bootstrap migration is forward-only.")
