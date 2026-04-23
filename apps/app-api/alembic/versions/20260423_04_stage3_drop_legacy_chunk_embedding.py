"""drop legacy chunk embedding column

Revision ID: 20260423_04
Revises: 20260423_03
Create Date: 2026-04-23 11:05:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260423_04"
down_revision = "20260423_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_chunks") as batch_op:
        batch_op.drop_column("embedding")


def downgrade() -> None:
    with op.batch_alter_table("knowledge_chunks") as batch_op:
        batch_op.add_column(sa.Column("embedding", sa.JSON(), nullable=True))
