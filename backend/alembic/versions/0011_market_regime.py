"""Add market_regimes table

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-15

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_regimes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("week_starting", sa.Date, nullable=False, index=True),
        sa.Column("week_ending", sa.Date, nullable=False, index=True),
        sa.Column("regime_type", sa.String(20), nullable=False, index=True),
        sa.Column("spy_200ma_ratio", sa.Float),
        sa.Column("vix_level", sa.Float),
        sa.Column("vix_change", sa.Float),
        sa.Column("nasdaq_spy_ratio", sa.Float),
        sa.Column("market_breadth", sa.Float),
        sa.Column("yield_trend", sa.Float),
        sa.Column("sector_rotation_score", sa.Float),
        sa.Column("confidence", sa.Float),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_market_regimes_week_ending",
        "market_regimes",
        ["week_ending"],
    )
    op.create_index(
        "ix_market_regimes_regime_type",
        "market_regimes",
        ["regime_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_regimes_regime_type", "market_regimes")
    op.drop_index("ix_market_regimes_week_ending", "market_regimes")
    op.drop_table("market_regimes")
