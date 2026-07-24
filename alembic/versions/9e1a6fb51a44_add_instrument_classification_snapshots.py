"""add instrument classification snapshots

Revision ID: 9e1a6fb51a44
Revises: 7d2c1c6b9a01
"""
from alembic import op
import sqlalchemy as sa


revision = "9e1a6fb51a44"
down_revision = "7d2c1c6b9a01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instrument_classification_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("as_of_date", sa.String(length=10), nullable=False),
        sa.Column("scheme", sa.String(length=48), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("source_url", sa.String(length=512), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("classification_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["instrument_id"], ["instrument.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instrument_id", "as_of_date", "scheme", "source"),
    )
    op.create_index(
        op.f("ix_instrument_classification_snapshot_instrument_id"),
        "instrument_classification_snapshot",
        ["instrument_id"],
    )
    op.create_index(
        op.f("ix_instrument_classification_snapshot_as_of_date"),
        "instrument_classification_snapshot",
        ["as_of_date"],
    )
    op.create_index(
        op.f("ix_instrument_classification_snapshot_scheme"),
        "instrument_classification_snapshot",
        ["scheme"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_instrument_classification_snapshot_scheme"), table_name="instrument_classification_snapshot")
    op.drop_index(op.f("ix_instrument_classification_snapshot_as_of_date"), table_name="instrument_classification_snapshot")
    op.drop_index(op.f("ix_instrument_classification_snapshot_instrument_id"), table_name="instrument_classification_snapshot")
    op.drop_table("instrument_classification_snapshot")
