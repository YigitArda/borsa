"""Add ablation_results table

Revision ID: 0012
Revises: 0010
Create Date: 2026-05-15

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0012"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ablation_results",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("strategy_id", sa.Integer, nullable=False, index=True),
        sa.Column("base_strategy_id", sa.Integer, nullable=True, index=True),
        sa.Column(
            "feature_group",
            sa.String(30),
            nullable=False,
            comment="technical|financial|news|macro|sentiment|tech_macro|tech_financial|all",
        ),
        sa.Column("features_removed", sa.JSON),
        sa.Column("sharpe", sa.Float),
        sa.Column("profit_factor", sa.Float),
        sa.Column("max_drawdown", sa.Float),
        sa.Column("win_rate", sa.Float),
        sa.Column("avg_return", sa.Float),
        sa.Column("sharpe_impact", sa.Float),
        sa.Column("profit_factor_impact", sa.Float),
        sa.Column("drawdown_impact", sa.Float),
        sa.Column("stability_score", sa.Float),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_ablation_results_strategy_id_feature_group",
        "ablation_results",
        ["strategy_id", "feature_group"],
    )


def downgrade() -> None:
    op.drop_index("ix_ablation_results_strategy_id_feature_group", "ablation_results")
    op.drop_table("ablation_results")
