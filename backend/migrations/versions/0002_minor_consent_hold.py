"""Add explicit consent hold metadata for records belonging to minors.

Revision ID: 0002_minor_consent_hold
Revises: 0001_prototype
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0002_minor_consent_hold"
down_revision = "0001_prototype"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("verification_requests"):
        columns = {c["name"] for c in inspect(bind).get_columns("verification_requests")}
        if "consent_hold_reason" not in columns:
            op.add_column("verification_requests", sa.Column("consent_hold_reason", sa.String(40), nullable=True))


def downgrade() -> None:
    raise RuntimeError("This data-preserving prototype migration is forward-only.")
