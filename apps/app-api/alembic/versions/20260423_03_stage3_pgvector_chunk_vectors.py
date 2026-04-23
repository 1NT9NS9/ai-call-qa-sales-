"""store stage 3 chunk vectors in pgvector

Revision ID: 20260423_03
Revises: 20260422_02
Create Date: 2026-04-23 09:50:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260423_03"
down_revision = "20260422_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE knowledge_chunk_vectors (
            chunk_id INTEGER PRIMARY KEY REFERENCES knowledge_chunks (id) ON DELETE CASCADE,
            embedding vector NOT NULL
        )
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP TABLE IF EXISTS knowledge_chunk_vectors")
