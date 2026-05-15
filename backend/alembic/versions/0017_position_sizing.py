"""Add position_sizing_log table for Kelly + regime audit trail

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-15

Stores per-week Kelly fraction and regime multiplier for each backtest run.
Enables post-hoc analysis of sizing decisions without re-running backtests.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "position_sizing_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), sa.ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("backtest_run_id", sa.Integer(), nullable=True),  # optional link to backtest_runs
        sa.Column("week_ending", sa.Date(), nullable=False),
        sa.Column("regime_type", sa.String(32), nullable=True),
        sa.Column("regime_multiplier", sa.Float(), nullable=True),
        sa.Column("kelly_fraction", sa.Float(), nullable=True),
        sa.Column("kelly_win_rate", sa.Float(), nullable=True),
        sa.Column("kelly_avg_win", sa.Float(), nullable=True),
        sa.Column("kelly_avg_loss", sa.Float(), nullable=True),
        sa.Column("kelly_full", sa.Float(), nullable=True),
        sa.Column("effective_allocation", sa.Float(), nullable=True),  # kelly_fraction * regime_multiplier
        sa.Column("n_positions", sa.Integer(), nullable=True),
        sa.Column("skipped", sa.Boolean(), default=False),  # True if regime blocked trading
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_position_sizing_log_strategy_week", "position_sizing_log", ["strategy_id", "week_ending"])


def downgrade() -> None:
    op.drop_index("ix_position_sizing_log_strategy_week", table_name="position_sizing_log")
    op.drop_table("position_sizing_log")
