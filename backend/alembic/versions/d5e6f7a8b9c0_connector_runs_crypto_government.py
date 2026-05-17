from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connector_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("rows_inserted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_skipped", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_connector_runs_provider_id", "connector_runs", ["provider_id"], unique=False)
    op.create_index("ix_connector_runs_status", "connector_runs", ["status"], unique=False)
    op.create_index("ix_connector_runs_provider_started", "connector_runs", ["provider_id", "started_at"], unique=False)

    op.create_table(
        "crypto_price_daily",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pair", sa.String(length=20), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Float(), nullable=True),
        sa.Column("high", sa.Float(), nullable=True),
        sa.Column("low", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("vwap", sa.Float(), nullable=True),
        sa.Column("provider_id", sa.String(length=100), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=True),
        sa.Column("source_quality", sa.Float(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pair", "date", name="uq_crypto_pair_date"),
    )
    op.create_index("ix_crypto_price_daily_pair_date", "crypto_price_daily", ["pair", "date"], unique=False)
    op.create_index("ix_crypto_price_daily_pair", "crypto_price_daily", ["pair"], unique=False)
    op.create_index("ix_crypto_price_daily_date", "crypto_price_daily", ["date"], unique=False)

    # Add social_sentiment columns (using try/except pattern for idempotency)
    with op.batch_alter_table("social_sentiment") as batch_op:
        batch_op.add_column(sa.Column("available_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("provider_id", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("source_quality", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("raw_payload", sa.JSON(), nullable=True))

    op.create_index("ix_social_sentiment_available_at", "social_sentiment", ["available_at"], unique=False)
    op.create_index("ix_social_sentiment_provider_id", "social_sentiment", ["provider_id"], unique=False)

    # Add macro_indicators.raw_payload (not added in previous migration)
    with op.batch_alter_table("macro_indicators") as batch_op:
        batch_op.add_column(sa.Column("raw_payload", sa.JSON(), nullable=True))

    # Add government_contracts columns for connector tracking
    # (GovernmentContract already exists, add provider tracking cols if missing)
    try:
        with op.batch_alter_table("government_contracts") as batch_op:
            batch_op.add_column(sa.Column("available_at", sa.DateTime(), nullable=True))
            batch_op.add_column(sa.Column("provider_id", sa.String(length=100), nullable=True))
            batch_op.add_column(sa.Column("source_quality", sa.Float(), nullable=True))
            batch_op.add_column(sa.Column("raw_payload", sa.JSON(), nullable=True))
    except Exception:
        pass


def downgrade() -> None:
    try:
        with op.batch_alter_table("macro_indicators") as batch_op:
            batch_op.drop_column("raw_payload")
    except Exception:
        pass

    try:
        op.drop_index("ix_social_sentiment_provider_id", table_name="social_sentiment")
        op.drop_index("ix_social_sentiment_available_at", table_name="social_sentiment")
        with op.batch_alter_table("social_sentiment") as batch_op:
            batch_op.drop_column("raw_payload")
            batch_op.drop_column("source_quality")
            batch_op.drop_column("provider_id")
            batch_op.drop_column("available_at")
    except Exception:
        pass

    op.drop_index("ix_crypto_price_daily_date", table_name="crypto_price_daily")
    op.drop_index("ix_crypto_price_daily_pair", table_name="crypto_price_daily")
    op.drop_index("ix_crypto_price_daily_pair_date", table_name="crypto_price_daily")
    op.drop_table("crypto_price_daily")

    op.drop_index("ix_connector_runs_provider_started", table_name="connector_runs")
    op.drop_index("ix_connector_runs_status", table_name="connector_runs")
    op.drop_index("ix_connector_runs_provider_id", table_name="connector_runs")
    op.drop_table("connector_runs")
