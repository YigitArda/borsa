"""Add pead_signals and short_interest_data tables for alpha factors

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-15

Tables:
  pead_signals         — SUE score and drift confirmation per earnings event
  short_interest_data  — Short interest snapshots from yfinance + FINRA
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pead_signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("earnings_date", sa.Date(), nullable=False),
        sa.Column("actual_eps", sa.Float(), nullable=True),
        sa.Column("expected_eps", sa.Float(), nullable=True),
        sa.Column("sue_score", sa.Float(), nullable=True),
        sa.Column("earnings_day_return", sa.Float(), nullable=True),
        sa.Column("post_earnings_week1", sa.Float(), nullable=True),
        sa.Column("earnings_volume_ratio", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("stock_id", "earnings_date", name="uq_pead_signals_stock_date"),
    )
    op.create_index("ix_pead_signals_stock_id", "pead_signals", ["stock_id"])
    op.create_index("ix_pead_signals_earnings_date", "pead_signals", ["earnings_date"])

    op.create_table(
        "short_interest_data",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("short_shares", sa.Float(), nullable=True),
        sa.Column("float_shares", sa.Float(), nullable=True),
        sa.Column("short_ratio", sa.Float(), nullable=True),
        sa.Column("short_pct_float", sa.Float(), nullable=True),
        sa.Column("avg_daily_volume", sa.Float(), nullable=True),
        sa.Column("short_volume_ratio", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("stock_id", "report_date", name="uq_short_interest_stock_date"),
    )
    op.create_index("ix_short_interest_data_stock_id", "short_interest_data", ["stock_id"])
    op.create_index("ix_short_interest_data_report_date", "short_interest_data", ["report_date"])


def downgrade() -> None:
    op.drop_index("ix_short_interest_data_report_date", table_name="short_interest_data")
    op.drop_index("ix_short_interest_data_stock_id", table_name="short_interest_data")
    op.drop_table("short_interest_data")
    op.drop_index("ix_pead_signals_earnings_date", table_name="pead_signals")
    op.drop_index("ix_pead_signals_stock_id", table_name="pead_signals")
    op.drop_table("pead_signals")
