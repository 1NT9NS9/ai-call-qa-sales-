"""create stage 1 schema

Revision ID: 20260422_01
Revises:
Create Date: 2026-04-22 16:15:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260422_01"
down_revision = None
branch_labels = None
depends_on = None


processing_status_enum = sa.Enum(
    "created",
    "uploaded",
    "transcribed",
    "analyzed",
    "exported",
    "failed",
    name="callprocessingstatus",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "call_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_call_id", sa.String(length=255), nullable=True),
        sa.Column("processing_status", processing_status_enum, nullable=False),
        sa.Column("audio_storage_key", sa.String(length=512), nullable=True),
        sa.Column("source_type", sa.String(length=100), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("call_id", sa.Integer(), nullable=False),
        sa.Column("speaker", sa.String(length=100), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["call_id"], ["call_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "call_analyses",
        sa.Column("call_id", sa.Integer(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        sa.Column("review_reasons", sa.JSON(), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["call_id"], ["call_sessions.id"]),
        sa.PrimaryKeyConstraint("call_id"),
    )

    op.create_table(
        "delivery_events",
        sa.Column("call_id", sa.Integer(), nullable=False),
        sa.Column("target_url", sa.String(length=2048), nullable=False),
        sa.Column("delivery_status", sa.String(length=100), nullable=False),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["call_id"], ["call_sessions.id"]),
        sa.PrimaryKeyConstraint("call_id", "attempt_no"),
    )


def downgrade() -> None:
    op.drop_table("delivery_events")
    op.drop_table("call_analyses")
    op.drop_table("knowledge_chunks")
    op.drop_table("transcript_segments")
    op.drop_table("knowledge_documents")
    op.drop_table("call_sessions")
