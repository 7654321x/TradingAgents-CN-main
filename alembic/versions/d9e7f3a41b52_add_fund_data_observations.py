"""add auditable fund data observations

Revision ID: d9e7f3a41b52
Revises: c8d4f6b21e34
"""
from alembic import op
import sqlalchemy as sa

revision = "d9e7f3a41b52"
down_revision = "c8d4f6b21e34"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fund_data_observation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instrument.id"), nullable=True),
        sa.Column("fund_code", sa.String(length=16), nullable=True),
        sa.Column("dataset_type", sa.String(length=64), nullable=False),
        sa.Column("field_name", sa.String(length=96), nullable=False),
        sa.Column("applicable_date", sa.String(length=10), nullable=True),
        sa.Column("published_date", sa.String(length=10), nullable=True),
        sa.Column("available_at", sa.DateTime(), nullable=True),
        sa.Column("source_level", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=96), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("confirmation_status", sa.String(length=32), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.UniqueConstraint("instrument_id", "dataset_type", "field_name", "applicable_date", "source", "payload_hash"),
    )
    for column in ("instrument_id", "fund_code", "dataset_type", "field_name", "applicable_date", "published_date", "available_at", "payload_hash"):
        op.create_index(f"ix_fund_data_observation_{column}", "fund_data_observation", [column])


def downgrade():
    op.drop_table("fund_data_observation")
