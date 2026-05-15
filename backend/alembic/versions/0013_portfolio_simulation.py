"""Add portfolio simulation tables

Revision ID: 0013
Revises: 0010
Create Date: 2026-05-15

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0013"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "portfolio_simulations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("strategy_id", sa.Integer, nullable=False, index=True),
        sa.Column(
            "backtest_run_id",
            sa.Integer,
            sa.ForeignKey("backtest_runs.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("initial_capital", sa.Float, default=100000.0),
        sa.Column("max_positions", sa.Integer, default=5),
        sa.Column("max_position_weight", sa.Float, default=0.25),
        sa.Column("sector_limit", sa.Float, default=0.40),
        sa.Column("cash_ratio", sa.Float, default=0.10),
        sa.Column("rebalance_frequency", sa.String(20), default="weekly"),
        sa.Column("stop_loss", sa.Float, nullable=True),
        sa.Column("take_profit", sa.Float, nullable=True),
        sa.Column("transaction_cost_bps", sa.Float, default=10.0),
        sa.Column("slippage_bps", sa.Float, default=5.0),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "simulation_id",
            sa.Integer,
            sa.ForeignKey("portfolio_simulations.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("date", sa.Date, nullable=False, index=True),
        sa.Column("total_value", sa.Float, nullable=False),
        sa.Column("cash_value", sa.Float, nullable=False),
        sa.Column("invested_value", sa.Float, nullable=False),
        sa.Column("n_positions", sa.Integer, default=0),
        sa.Column("sector_exposure", sa.JSON, default=dict),
        sa.Column("monthly_return", sa.Float, nullable=True),
        sa.Column("ytd_return", sa.Float, nullable=True),
        sa.Column("drawdown", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_index(
        "ix_portfolio_snapshots_simulation_date",
        "portfolio_snapshots",
        ["simulation_id", "date"],
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_snapshots_simulation_date", "portfolio_snapshots")
    op.drop_table("portfolio_snapshots")
    op.drop_table("portfolio_simulations")
