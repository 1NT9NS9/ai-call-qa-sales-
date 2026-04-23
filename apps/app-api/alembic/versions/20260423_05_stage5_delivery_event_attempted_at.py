"""add attempted_at to delivery events

Revision ID: 20260423_05
Revises: 20260423_04
Create Date: 2026-04-23 14:58:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260423_05"
down_revision = "20260423_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "delivery_events",
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("delivery_events", "attempted_at")
