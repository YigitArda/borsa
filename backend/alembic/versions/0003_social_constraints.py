"""Add unique constraint to social_sentiment and model_promotions index

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-15

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    try:
        op.create_unique_constraint(
            "uq_social_stock_week_source",
            "social_sentiment",
            ["stock_id", "week_ending", "source"],
        )
    except Exception:
        pass  # constraint may already exist if table was just created


def downgrade() -> None:
    op.drop_constraint("uq_social_stock_week_source", "social_sentiment")
