"""add stage 3 knowledge document fields

Revision ID: 20260422_02
Revises: 20260422_01
Create Date: 2026-04-22 21:40:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260422_02"
down_revision = "20260422_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "source_path",
            sa.String(length=1024),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "content",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_documents", "content")
    op.drop_column("knowledge_documents", "source_path")
