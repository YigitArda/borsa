"""Add data-quality import tables

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-15

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM stock_universe_snapshots
        WHERE id IN (
            SELECT id
            FROM (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY snapshot_date, index_name, ticker
                        ORDER BY id DESC
                    ) AS rn
                FROM stock_universe_snapshots
            ) duplicates
            WHERE rn > 1
        )
        """
    )
    op.create_unique_constraint(
        "uq_stock_universe_snapshot",
        "stock_universe_snapshots",
        ["snapshot_date", "index_name", "ticker"],
    )

    op.add_column("financial_metrics", sa.Column("data_source", sa.String(100), nullable=True))
    op.drop_constraint("uq_financial_metrics", "financial_metrics", type_="unique")
    op.create_unique_constraint(
        "uq_financial_metrics_pit",
        "financial_metrics",
        ["stock_id", "fiscal_period_end", "metric_name", "as_of_date"],
    )

    op.create_table(
        "ticker_aliases",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("old_ticker", sa.String(20), nullable=False),
        sa.Column("new_ticker", sa.String(20), nullable=False),
        sa.Column("effective_date", sa.Date, nullable=False),
        sa.Column("reason", sa.String(200)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("old_ticker", "new_ticker", "effective_date", name="uq_ticker_alias"),
    )
    op.create_index("ix_ticker_aliases_old_ticker", "ticker_aliases", ["old_ticker"])
    op.create_index("ix_ticker_aliases_new_ticker", "ticker_aliases", ["new_ticker"])
    op.create_index("ix_ticker_aliases_effective_date", "ticker_aliases", ["effective_date"])

    op.create_table(
        "corporate_actions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_id", sa.Integer, nullable=False),
        sa.Column("action_date", sa.Date, nullable=False),
        sa.Column("action_type", sa.String(50), nullable=False),
        sa.Column("value", sa.Float),
        sa.Column("description", sa.String(500)),
        sa.Column("data_source", sa.String(100)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("stock_id", "action_date", "action_type", name="uq_corporate_action"),
    )
    op.create_index("ix_corporate_actions_stock_id", "corporate_actions", ["stock_id"])
    op.create_index("ix_corporate_actions_action_date", "corporate_actions", ["action_date"])


def downgrade() -> None:
    op.drop_index("ix_corporate_actions_action_date", "corporate_actions")
    op.drop_index("ix_corporate_actions_stock_id", "corporate_actions")
    op.drop_table("corporate_actions")
    op.drop_index("ix_ticker_aliases_effective_date", "ticker_aliases")
    op.drop_index("ix_ticker_aliases_new_ticker", "ticker_aliases")
    op.drop_index("ix_ticker_aliases_old_ticker", "ticker_aliases")
    op.drop_table("ticker_aliases")
    op.drop_constraint("uq_financial_metrics_pit", "financial_metrics", type_="unique")
    op.create_unique_constraint(
        "uq_financial_metrics",
        "financial_metrics",
        ["stock_id", "fiscal_period_end", "metric_name"],
    )
    op.drop_column("financial_metrics", "data_source")
    op.drop_constraint("uq_stock_universe_snapshot", "stock_universe_snapshots", type_="unique")
