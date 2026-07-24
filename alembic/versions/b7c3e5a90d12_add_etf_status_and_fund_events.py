"""add ETF status and cached fund events

Revision ID: b7c3e5a90d12
Revises: a2f4d8e1c903
"""
from alembic import op
import sqlalchemy as sa


revision = "b7c3e5a90d12"
down_revision = "a2f4d8e1c903"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "etf_status_observation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("etf_instrument_id", sa.Integer(), nullable=False),
        sa.Column("observed_date", sa.String(length=10), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("nav_date", sa.String(length=10), nullable=True),
        sa.Column("unit_nav", sa.Float(), nullable=True),
        sa.Column("market_price", sa.Float(), nullable=True),
        sa.Column("iopv", sa.Float(), nullable=True),
        sa.Column("discount_rate_pct", sa.Float(), nullable=True),
        sa.Column("shares", sa.Float(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("circulating_market_cap", sa.Float(), nullable=True),
        sa.Column("total_market_cap", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["etf_instrument_id"], ["instrument.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("etf_instrument_id", "observed_at", "source"),
    )
    op.create_index(op.f("ix_etf_status_observation_etf_instrument_id"), "etf_status_observation", ["etf_instrument_id"])
    op.create_index(op.f("ix_etf_status_observation_observed_date"), "etf_status_observation", ["observed_date"])
    op.create_table(
        "fund_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fund_instrument_id", sa.Integer(), nullable=False),
        sa.Column("event_date", sa.String(length=10), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("source_level", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("confirmation_status", sa.String(length=32), nullable=False),
        sa.Column("already_reflected_status", sa.String(length=32), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("dedup_key", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["fund_instrument_id"], ["instrument.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedup_key"),
    )
    for column in ("fund_instrument_id", "event_date", "available_at", "source", "content_hash", "dedup_key"):
        op.create_index(op.f(f"ix_fund_event_{column}"), "fund_event", [column])
    op.create_table(
        "fund_event_sync_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fund_instrument_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("last_successful_event_date", sa.String(length=10), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["fund_instrument_id"], ["instrument.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fund_instrument_id", "source"),
    )
    op.create_index(op.f("ix_fund_event_sync_state_fund_instrument_id"), "fund_event_sync_state", ["fund_instrument_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_fund_event_sync_state_fund_instrument_id"), table_name="fund_event_sync_state")
    op.drop_table("fund_event_sync_state")
    for column in reversed(("fund_instrument_id", "event_date", "available_at", "source", "content_hash", "dedup_key")):
        op.drop_index(op.f(f"ix_fund_event_{column}"), table_name="fund_event")
    op.drop_table("fund_event")
    op.drop_index(op.f("ix_etf_status_observation_observed_date"), table_name="etf_status_observation")
    op.drop_index(op.f("ix_etf_status_observation_etf_instrument_id"), table_name="etf_status_observation")
    op.drop_table("etf_status_observation")
