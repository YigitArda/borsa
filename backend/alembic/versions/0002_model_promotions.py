"""Add model_promotions table

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-15

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_promotions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("strategy_id", sa.Integer, nullable=False),
        sa.Column("promoted_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("avg_sharpe", sa.Float),
        sa.Column("deflated_sharpe", sa.Float),
        sa.Column("probabilistic_sr", sa.Float),
        sa.Column("permutation_pvalue", sa.Float),
        sa.Column("spy_sharpe", sa.Float),
        sa.Column("outperforms_spy", sa.String(5)),
        sa.Column("avg_win_rate", sa.Float),
        sa.Column("total_trades", sa.Integer),
        sa.Column("min_drawdown", sa.Float),
        sa.Column("avg_profit_factor", sa.Float),
        sa.Column("concentration_ok", sa.String(5)),
        sa.Column("details", sa.JSON),
    )
    op.create_index("ix_model_promotions_strategy_id", "model_promotions", ["strategy_id"])


def downgrade() -> None:
    op.drop_index("ix_model_promotions_strategy_id", "model_promotions")
    op.drop_table("model_promotions")
