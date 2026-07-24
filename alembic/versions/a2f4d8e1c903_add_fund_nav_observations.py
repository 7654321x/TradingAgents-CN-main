"""add fund NAV observations

Revision ID: a2f4d8e1c903
Revises: 9e1a6fb51a44
"""
from alembic import op
import sqlalchemy as sa


revision = "a2f4d8e1c903"
down_revision = "9e1a6fb51a44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fund_nav_observation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fund_instrument_id", sa.Integer(), nullable=False),
        sa.Column("nav_date", sa.String(length=10), nullable=False),
        sa.Column("unit_nav", sa.Float(), nullable=True),
        sa.Column("cumulative_nav", sa.Float(), nullable=True),
        sa.Column("daily_change_pct", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("source_url", sa.String(length=512), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["fund_instrument_id"], ["instrument.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fund_instrument_id", "nav_date", "source"),
    )
    op.create_index(op.f("ix_fund_nav_observation_fund_instrument_id"), "fund_nav_observation", ["fund_instrument_id"])
    op.create_index(op.f("ix_fund_nav_observation_nav_date"), "fund_nav_observation", ["nav_date"])


def downgrade() -> None:
    op.drop_index(op.f("ix_fund_nav_observation_nav_date"), table_name="fund_nav_observation")
    op.drop_index(op.f("ix_fund_nav_observation_fund_instrument_id"), table_name="fund_nav_observation")
    op.drop_table("fund_nav_observation")
