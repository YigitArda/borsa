"""Enhance model_versions with registry and versioning fields

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-15

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # status
    op.add_column(
        "model_versions",
        sa.Column("status", sa.String(20), nullable=False, server_default="research"),
    )
    op.create_index("ix_model_versions_status", "model_versions", ["status"])

    # JSON periods
    op.add_column(
        "model_versions",
        sa.Column("holdout_period", sa.JSON, nullable=True),
    )
    op.add_column(
        "model_versions",
        sa.Column("validation_period", sa.JSON, nullable=True),
    )

    # Parent / lineage
    op.add_column(
        "model_versions",
        sa.Column("parent_model_id", sa.Integer, nullable=True),
    )
    op.create_index("ix_model_versions_parent_model_id", "model_versions", ["parent_model_id"])
    op.create_foreign_key(
        "fk_model_versions_parent",
        "model_versions",
        "model_versions",
        ["parent_model_id"],
        ["id"],
    )

    # Reasons
    op.add_column(
        "model_versions",
        sa.Column("promotion_reason", sa.Text, nullable=True),
    )
    op.add_column(
        "model_versions",
        sa.Column("rejection_reason", sa.Text, nullable=True),
    )

    # Hyperparams & immutability hash
    op.add_column(
        "model_versions",
        sa.Column("hyperparams", sa.JSON, nullable=True),
    )
    op.add_column(
        "model_versions",
        sa.Column("model_file_hash", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_versions", "model_file_hash")
    op.drop_column("model_versions", "hyperparams")
    op.drop_column("model_versions", "rejection_reason")
    op.drop_column("model_versions", "promotion_reason")

    op.drop_constraint("fk_model_versions_parent", "model_versions", type_="foreignkey")
    op.drop_index("ix_model_versions_parent_model_id", "model_versions")
    op.drop_column("model_versions", "parent_model_id")

    op.drop_column("model_versions", "validation_period")
    op.drop_column("model_versions", "holdout_period")

    op.drop_index("ix_model_versions_status", "model_versions")
    op.drop_column("model_versions", "status")
