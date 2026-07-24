"""add isolated MCP web observations

Revision ID: e4a8f5c13d76
Revises: d9e7f3a41b52
"""
from alembic import op
import sqlalchemy as sa


revision = "e4a8f5c13d76"
down_revision = "d9e7f3a41b52"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mcp_web_observation",
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
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.UniqueConstraint("instrument_id", "dataset_type", "field_name", "applicable_date", "source", "content_hash"),
    )
    for column in ("instrument_id", "fund_code", "dataset_type", "field_name", "applicable_date", "published_date", "available_at", "content_hash"):
        op.create_index(f"ix_mcp_web_observation_{column}", "mcp_web_observation", [column])


def downgrade():
    op.drop_table("mcp_web_observation")
