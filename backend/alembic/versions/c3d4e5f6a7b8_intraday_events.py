"""intraday_events table for spike/crash detection and learning

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "intraday_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("week_ending", sa.Date(), nullable=False),

        # Spike metrics
        sa.Column("max_intraday_up_pct", sa.Float(), nullable=True),
        sa.Column("max_intraday_down_pct", sa.Float(), nullable=True),
        sa.Column("high_low_range_pct", sa.Float(), nullable=True),
        sa.Column("spike_type", sa.String(10), nullable=True),
        sa.Column("spike_day", sa.Date(), nullable=True),

        # Cause attribution
        sa.Column("has_earnings", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("has_news_spike", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("has_macro_event", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("news_sentiment_delta", sa.Float(), nullable=True),
        sa.Column("vix_level", sa.Float(), nullable=True),
        sa.Column("vix_change", sa.Float(), nullable=True),

        # Pipeline feature deltas (JSONB for flexible schema)
        sa.Column("feature_delta", JSONB(), nullable=True),

        # Outcome
        sa.Column("actual_return", sa.Float(), nullable=True),

        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),

        sa.UniqueConstraint("stock_id", "week_ending", name="uq_intraday_events_stock_week"),
    )

    op.create_index("ix_intraday_events_stock_id", "intraday_events", ["stock_id"])
    op.create_index("ix_intraday_events_week_ending", "intraday_events", ["week_ending"])
    op.create_index(
        "ix_intraday_events_stock_week",
        "intraday_events",
        ["stock_id", "week_ending"],
    )


def downgrade():
    op.drop_index("ix_intraday_events_stock_week", "intraday_events")
    op.drop_index("ix_intraday_events_week_ending", "intraday_events")
    op.drop_index("ix_intraday_events_stock_id", "intraday_events")
    op.drop_table("intraday_events")
