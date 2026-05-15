"""Add paper trading forward-test tracking

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-15

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM weekly_predictions
        WHERE id IN (
            SELECT id
            FROM (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY week_starting, stock_id, strategy_id
                        ORDER BY created_at DESC, id DESC
                    ) AS rn
                FROM weekly_predictions
            ) duplicates
            WHERE rn > 1
        )
        """
    )
    op.create_unique_constraint(
        "uq_weekly_predictions_week_stock_strategy",
        "weekly_predictions",
        ["week_starting", "stock_id", "strategy_id"],
    )

    op.create_table(
        "paper_trades",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("prediction_id", sa.Integer, nullable=False),
        sa.Column("week_starting", sa.Date, nullable=False),
        sa.Column("stock_id", sa.Integer, nullable=False),
        sa.Column("strategy_id", sa.Integer, nullable=False),
        sa.Column("rank", sa.Integer),
        sa.Column("prob_2pct", sa.Float),
        sa.Column("prob_loss_2pct", sa.Float),
        sa.Column("expected_return", sa.Float),
        sa.Column("confidence", sa.String(20)),
        sa.Column("signal_summary", sa.String(500)),
        sa.Column("entry_date", sa.Date),
        sa.Column("planned_exit_date", sa.Date, nullable=False),
        sa.Column("exit_date", sa.Date),
        sa.Column("entry_price", sa.Float),
        sa.Column("exit_price", sa.Float),
        sa.Column("realized_return", sa.Float),
        sa.Column("max_rise_in_period", sa.Float),
        sa.Column("max_drawdown_in_period", sa.Float),
        sa.Column("hit_2pct", sa.Boolean),
        sa.Column("hit_3pct", sa.Boolean),
        sa.Column("hit_loss_2pct", sa.Boolean),
        sa.Column("status", sa.String(20), server_default="open"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("evaluated_at", sa.DateTime),
        sa.UniqueConstraint("prediction_id", name="uq_paper_trades_prediction"),
    )
    op.create_index("ix_paper_trades_prediction_id", "paper_trades", ["prediction_id"])
    op.create_index("ix_paper_trades_week_starting", "paper_trades", ["week_starting"])
    op.create_index("ix_paper_trades_stock_id", "paper_trades", ["stock_id"])
    op.create_index("ix_paper_trades_strategy_id", "paper_trades", ["strategy_id"])
    op.create_index("ix_paper_trades_status", "paper_trades", ["status"])


def downgrade() -> None:
    op.drop_index("ix_paper_trades_status", "paper_trades")
    op.drop_index("ix_paper_trades_strategy_id", "paper_trades")
    op.drop_index("ix_paper_trades_stock_id", "paper_trades")
    op.drop_index("ix_paper_trades_week_starting", "paper_trades")
    op.drop_index("ix_paper_trades_prediction_id", "paper_trades")
    op.drop_table("paper_trades")
    op.drop_constraint("uq_weekly_predictions_week_stock_strategy", "weekly_predictions", type_="unique")
