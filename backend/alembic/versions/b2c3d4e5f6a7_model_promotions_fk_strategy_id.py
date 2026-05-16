"""model_promotions FK on strategy_id

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-16

"""
from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    # Make strategy_id nullable so SET NULL on delete works
    op.alter_column("model_promotions", "strategy_id", nullable=True)

    # Add FK: model_promotions.strategy_id -> strategies.id (SET NULL on delete)
    op.create_foreign_key(
        "fk_model_promotions_strategy_id",
        "model_promotions", "strategies",
        ["strategy_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_model_promotions_strategy_id", "model_promotions", type_="foreignkey")
    op.alter_column("model_promotions", "strategy_id", nullable=False)
