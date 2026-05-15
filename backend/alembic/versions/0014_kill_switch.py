"""Add kill switch tables

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-15

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kill_switch_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("trigger_type", sa.String(30), nullable=False, index=True),
        sa.Column("strategy_id", sa.Integer, nullable=True, index=True),
        sa.Column("severity", sa.String(10), nullable=False, default="warning"),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("details", sa.JSON, nullable=True),
        sa.Column("triggered_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
        sa.Column("resolved_by", sa.String(100), nullable=True),
        sa.Column("status", sa.String(10), nullable=False, default="active", index=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "kill_switch_configs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("max_paper_drawdown_weeks", sa.Integer, default=4),
        sa.Column("max_paper_drawdown_pct", sa.Float, default=0.10),
        sa.Column("max_model_drawdown_pct", sa.Float, default=0.15),
        sa.Column("min_data_quality_score", sa.Float, default=50.0),
        sa.Column("max_vix_level", sa.Float, default=40.0),
        sa.Column("confidence_distribution_threshold", sa.Float, default=0.20),
        sa.Column("min_predictions_per_week", sa.Integer, default=10),
        sa.Column("max_feature_drift_pct", sa.Float, default=0.30),
        sa.Column("enabled", sa.String(5), default="true", nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("kill_switch_configs")
    op.drop_table("kill_switch_events")
