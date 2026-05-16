"""add social source health logging and source_used tracking

Revision ID: 9a1b2c3d4e5f
Revises: f3c9a6b7d8e1
Create Date: 2026-05-16 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9a1b2c3d4e5f"
down_revision: Union[str, None] = "f3c9a6b7d8e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("social_sentiment") as batch_op:
        batch_op.add_column(sa.Column("source_used", sa.String(length=100), nullable=True))

    op.create_table(
        "data_source_health",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_name", sa.String(length=100), nullable=False),
        sa.Column("source_used", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ok"),
        sa.Column("target_ticker", sa.String(length=20), nullable=True),
        sa.Column("week_ending", sa.Date(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_data_source_health_source_name", "data_source_health", ["source_name"])
    op.create_index("ix_data_source_health_source_used", "data_source_health", ["source_used"])
    op.create_index("ix_data_source_health_status", "data_source_health", ["status"])
    op.create_index("ix_data_source_health_target_ticker", "data_source_health", ["target_ticker"])
    op.create_index("ix_data_source_health_week_ending", "data_source_health", ["week_ending"])


def downgrade() -> None:
    op.drop_index("ix_data_source_health_week_ending", table_name="data_source_health")
    op.drop_index("ix_data_source_health_target_ticker", table_name="data_source_health")
    op.drop_index("ix_data_source_health_status", table_name="data_source_health")
    op.drop_index("ix_data_source_health_source_used", table_name="data_source_health")
    op.drop_index("ix_data_source_health_source_name", table_name="data_source_health")
    op.drop_table("data_source_health")

    with op.batch_alter_table("social_sentiment") as batch_op:
        batch_op.drop_column("source_used")
