"""prediction indexes, FK on strategy_id, allocation_layer field

Revision ID: a1b2c3d4e5f6
Revises: f3c9a6b7d8e1
Create Date: 2026-05-16

"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "f3c9a6b7d8e1"
branch_labels = None
depends_on = None


def upgrade():
    # Compound index on paper_trades for common filter pattern
    op.create_index(
        "ix_paper_trades_strategy_status_week",
        "paper_trades",
        ["strategy_id", "status", "week_starting"],
    )

    # Compound index on weekly_predictions
    op.create_index(
        "ix_weekly_predictions_strategy_week",
        "weekly_predictions",
        ["strategy_id", "week_starting"],
    )

    # allocation_layer column on paper_trades
    op.add_column(
        "paper_trades",
        sa.Column("allocation_layer", sa.String(20), nullable=True),
    )

    # FK from paper_trades.strategy_id -> strategies.id (SET NULL on delete)
    op.create_foreign_key(
        "fk_paper_trades_strategy_id",
        "paper_trades", "strategies",
        ["strategy_id"], ["id"],
        ondelete="SET NULL",
    )

    # FK from weekly_predictions.strategy_id -> strategies.id (SET NULL on delete)
    # strategy_id must allow NULL for SET NULL to work
    op.alter_column("weekly_predictions", "strategy_id", nullable=True)
    op.create_foreign_key(
        "fk_weekly_predictions_strategy_id",
        "weekly_predictions", "strategies",
        ["strategy_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_weekly_predictions_strategy_id", "weekly_predictions", type_="foreignkey")
    op.alter_column("weekly_predictions", "strategy_id", nullable=False)
    op.drop_constraint("fk_paper_trades_strategy_id", "paper_trades", type_="foreignkey")
    op.drop_column("paper_trades", "allocation_layer")
    op.drop_index("ix_weekly_predictions_strategy_week", "weekly_predictions")
    op.drop_index("ix_paper_trades_strategy_status_week", "paper_trades")
