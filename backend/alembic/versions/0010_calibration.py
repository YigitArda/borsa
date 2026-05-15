"""Add probability calibration table

Revision ID: 0010
Revises: 0007
Create Date: 2026-05-15

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "probability_calibrations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("strategy_id", sa.Integer, nullable=False),
        sa.Column("week_starting", sa.Date, nullable=False),
        sa.Column("brier_score", sa.Float),
        sa.Column("calibration_error", sa.Float),
        sa.Column("prob_buckets", sa.JSON),
        sa.Column("reliability_data", sa.JSON),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_probability_calibrations_strategy_id",
        "probability_calibrations",
        ["strategy_id"],
    )
    op.create_index(
        "ix_probability_calibrations_week_starting",
        "probability_calibrations",
        ["week_starting"],
    )


def downgrade() -> None:
    op.drop_index("ix_probability_calibrations_week_starting", "probability_calibrations")
    op.drop_index("ix_probability_calibrations_strategy_id", "probability_calibrations")
    op.drop_table("probability_calibrations")
