from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b90e4c7235e8"
down_revision: Union[str, None] = "811815f79fa5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "insider_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("filed_date", sa.Date(), nullable=False),
        sa.Column("insider_name", sa.String(length=200), nullable=False),
        sa.Column("insider_title", sa.String(length=200), nullable=True),
        sa.Column("transaction_type", sa.String(length=20), nullable=False),
        sa.Column("shares", sa.Float(), nullable=True),
        sa.Column("price_per_share", sa.Float(), nullable=True),
        sa.Column("total_value", sa.Float(), nullable=True),
        sa.Column("is_open_market", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("ownership_after", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=50), server_default="sec_form4", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stock_id", "filed_date", "insider_name", "transaction_type", name="uq_insider_tx"),
    )
    op.create_index(
        "ix_insider_transactions_stock_date",
        "insider_transactions",
        ["stock_id", "filed_date"],
        unique=False,
    )

    op.create_table(
        "government_contracts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("award_id", sa.String(length=100), nullable=False),
        sa.Column("award_date", sa.Date(), nullable=False),
        sa.Column("awarding_agency", sa.String(length=200), nullable=True),
        sa.Column("recipient_name", sa.String(length=200), nullable=True),
        sa.Column("award_amount", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("contract_type", sa.String(length=50), nullable=True),
        sa.Column("performance_end_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stock_id", "award_id", name="uq_gov_contract"),
    )
    op.create_index(
        "ix_gov_contracts_stock_date",
        "government_contracts",
        ["stock_id", "award_date"],
        unique=False,
    )

    op.create_table(
        "institutional_positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("filer_cik", sa.String(length=20), nullable=False),
        sa.Column("filer_name", sa.String(length=200), nullable=True),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("shares_held", sa.Float(), nullable=True),
        sa.Column("market_value", sa.Float(), nullable=True),
        sa.Column("is_new_position", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("prev_shares", sa.Float(), nullable=True),
        sa.Column("change_pct", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stock_id", "filer_cik", "report_date", name="uq_inst_position"),
    )
    op.create_index(
        "ix_institutional_positions_stock_date",
        "institutional_positions",
        ["stock_id", "report_date"],
        unique=False,
    )

    op.create_table(
        "smallcap_radar_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("scan_date", sa.Date(), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=True),
        sa.Column("insider_score", sa.Float(), nullable=True),
        sa.Column("smart_money_score", sa.Float(), nullable=True),
        sa.Column("business_score", sa.Float(), nullable=True),
        sa.Column("structural_score", sa.Float(), nullable=True),
        sa.Column("sector_multiplier", sa.Float(), nullable=True),
        sa.Column("regime_multiplier", sa.Float(), nullable=True),
        sa.Column("signals_triggered", sa.JSON(), nullable=True),
        sa.Column("eliminated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("elimination_reason", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stock_id", "scan_date", name="uq_radar_scan"),
    )
    op.create_index(
        "ix_smallcap_radar_score",
        "smallcap_radar_results",
        ["scan_date", sa.text("total_score DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_smallcap_radar_score", table_name="smallcap_radar_results")
    op.drop_table("smallcap_radar_results")
    op.drop_index("ix_institutional_positions_stock_date", table_name="institutional_positions")
    op.drop_table("institutional_positions")
    op.drop_index("ix_gov_contracts_stock_date", table_name="government_contracts")
    op.drop_table("government_contracts")
    op.drop_index("ix_insider_transactions_stock_date", table_name="insider_transactions")
    op.drop_table("insider_transactions")
