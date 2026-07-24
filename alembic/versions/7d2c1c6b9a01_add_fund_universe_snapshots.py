"""add fund metadata and universe constituent snapshots"""
from alembic import op
import sqlalchemy as sa

revision = "7d2c1c6b9a01"
down_revision = "66cb471014e5"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "fund_metadata_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fund_instrument_id", sa.Integer(), nullable=False),
        sa.Column("as_of_date", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("source_url", sa.String(length=512), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("is_official", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["fund_instrument_id"], ["instrument.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fund_instrument_id", "as_of_date", "source"),
    )
    op.create_index("ix_fund_metadata_snapshot_fund_instrument_id", "fund_metadata_snapshot", ["fund_instrument_id"])
    op.create_index("ix_fund_metadata_snapshot_as_of_date", "fund_metadata_snapshot", ["as_of_date"])
    op.create_table(
        "universe_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("universe_id", sa.Integer(), nullable=False),
        sa.Column("as_of_date", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("source_url", sa.String(length=512), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["universe_id"], ["universe.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("universe_id", "as_of_date", "source"),
    )
    op.create_index("ix_universe_snapshot_universe_id", "universe_snapshot", ["universe_id"])
    op.create_index("ix_universe_snapshot_as_of_date", "universe_snapshot", ["as_of_date"])
    op.create_table(
        "universe_constituent_weight",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("weight_pct", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["universe_snapshot.id"]),
        sa.ForeignKeyConstraint(["instrument_id"], ["instrument.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "instrument_id"),
    )
    op.create_index("ix_universe_constituent_weight_snapshot_id", "universe_constituent_weight", ["snapshot_id"])
    op.create_index("ix_universe_constituent_weight_instrument_id", "universe_constituent_weight", ["instrument_id"])

def downgrade():
    op.drop_index("ix_universe_constituent_weight_instrument_id", table_name="universe_constituent_weight")
    op.drop_index("ix_universe_constituent_weight_snapshot_id", table_name="universe_constituent_weight")
    op.drop_table("universe_constituent_weight")
    op.drop_index("ix_universe_snapshot_as_of_date", table_name="universe_snapshot")
    op.drop_index("ix_universe_snapshot_universe_id", table_name="universe_snapshot")
    op.drop_table("universe_snapshot")
    op.drop_index("ix_fund_metadata_snapshot_as_of_date", table_name="fund_metadata_snapshot")
    op.drop_index("ix_fund_metadata_snapshot_fund_instrument_id", table_name="fund_metadata_snapshot")
    op.drop_table("fund_metadata_snapshot")
