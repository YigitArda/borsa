"""Add data_quality_scores table

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-15

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_quality_scores",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_id", sa.Integer, nullable=False, index=True),
        sa.Column("week_ending", sa.Date, nullable=False, index=True),
        sa.Column("overall_score", sa.Float, nullable=False, default=0.0),
        sa.Column("price_score", sa.Float, nullable=False, default=0.0),
        sa.Column("feature_score", sa.Float, nullable=False, default=0.0),
        sa.Column("financial_score", sa.Float, nullable=False, default=0.0),
        sa.Column("news_score", sa.Float, nullable=False, default=0.0),
        sa.Column("macro_score", sa.Float, nullable=False, default=0.0),
        sa.Column("details", sa.JSON),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("stock_id", "week_ending", name="uq_dq_score_stock_week"),
    )


def downgrade() -> None:
    op.drop_table("data_quality_scores")
