"""add sector fund backtest runs and samples

Revision ID: c8d4f6b21e34
Revises: b7c3e5a90d12
"""
from alembic import op
import sqlalchemy as sa


revision = "c8d4f6b21e34"
down_revision = "b7c3e5a90d12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sector_fund_backtest_run",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("fund_code", sa.String(length=16), nullable=False),
        sa.Column("requested_end_date", sa.String(length=10), nullable=False),
        sa.Column("feature_version", sa.String(length=64), nullable=False),
        sa.Column("scoring_version", sa.String(length=64), nullable=False),
        sa.Column("label_version", sa.String(length=64), nullable=False),
        sa.Column("sample_start_date", sa.String(length=10), nullable=True),
        sa.Column("sample_end_date", sa.String(length=10), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(op.f("ix_sector_fund_backtest_run_fund_code"), "sector_fund_backtest_run", ["fund_code"])
    op.create_index(op.f("ix_sector_fund_backtest_run_input_hash"), "sector_fund_backtest_run", ["input_hash"])
    op.create_table(
        "sector_fund_backtest_sample",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("analysis_date", sa.String(length=10), nullable=False),
        sa.Column("weight_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("weight_snapshot_date", sa.String(length=10), nullable=False),
        sa.Column("core_score", sa.Float(), nullable=True),
        sa.Column("short_score", sa.Float(), nullable=True),
        sa.Column("forward_1d_pct", sa.Float(), nullable=True),
        sa.Column("forward_3d_pct", sa.Float(), nullable=True),
        sa.Column("label_1d", sa.String(length=16), nullable=True),
        sa.Column("label_3d", sa.String(length=16), nullable=True),
        sa.Column("prediction_json", sa.Text(), nullable=True),
        sa.Column("brier_1d", sa.Float(), nullable=True),
        sa.Column("brier_3d", sa.Float(), nullable=True),
        sa.Column("feature_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["sector_fund_backtest_run.run_id"]),
        sa.ForeignKeyConstraint(["weight_snapshot_id"], ["universe_snapshot.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "analysis_date"),
    )
    op.create_index(op.f("ix_sector_fund_backtest_sample_run_id"), "sector_fund_backtest_sample", ["run_id"])
    op.create_index(op.f("ix_sector_fund_backtest_sample_analysis_date"), "sector_fund_backtest_sample", ["analysis_date"])


def downgrade() -> None:
    op.drop_index(op.f("ix_sector_fund_backtest_sample_analysis_date"), table_name="sector_fund_backtest_sample")
    op.drop_index(op.f("ix_sector_fund_backtest_sample_run_id"), table_name="sector_fund_backtest_sample")
    op.drop_table("sector_fund_backtest_sample")
    op.drop_index(op.f("ix_sector_fund_backtest_run_input_hash"), table_name="sector_fund_backtest_run")
    op.drop_index(op.f("ix_sector_fund_backtest_run_fund_code"), table_name="sector_fund_backtest_run")
    op.drop_table("sector_fund_backtest_run")
