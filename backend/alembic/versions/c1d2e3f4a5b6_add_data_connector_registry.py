from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b90e4c7235e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_connectors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("requires_api_key", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("configured", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="100", nullable=False),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=True),
        sa.Column("last_status", sa.String(length=20), server_default="unknown", nullable=False),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(), nullable=True),
        sa.Column("last_message", sa.Text(), nullable=True),
        sa.Column("coverage_score", sa.Float(), nullable=True),
        sa.Column("freshness_score", sa.Float(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id"),
    )
    op.create_index("ix_data_connectors_provider_id", "data_connectors", ["provider_id"], unique=False)
    op.create_index("ix_data_connectors_category", "data_connectors", ["category"], unique=False)
    op.create_index("ix_data_connectors_enabled", "data_connectors", ["enabled"], unique=False)
    op.create_index("ix_data_connectors_configured", "data_connectors", ["configured"], unique=False)
    op.create_index("ix_data_connectors_last_status", "data_connectors", ["last_status"], unique=False)

    op.add_column("news_articles", sa.Column("available_at", sa.DateTime(), nullable=True))
    op.add_column("news_articles", sa.Column("provider_id", sa.String(length=100), nullable=True))
    op.add_column("news_articles", sa.Column("source_quality", sa.Float(), nullable=True))
    op.add_column("news_articles", sa.Column("fallback_used", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("news_articles", sa.Column("raw_payload", sa.JSON(), nullable=True))
    op.create_index("ix_news_articles_available_at", "news_articles", ["available_at"], unique=False)
    op.create_index("ix_news_articles_provider_id", "news_articles", ["provider_id"], unique=False)

    op.add_column("macro_indicators", sa.Column("available_at", sa.DateTime(), nullable=True))
    op.add_column("macro_indicators", sa.Column("provider_id", sa.String(length=100), nullable=True))
    op.add_column("macro_indicators", sa.Column("source_quality", sa.Float(), nullable=True))
    op.create_index("ix_macro_indicators_available_at", "macro_indicators", ["available_at"], unique=False)
    op.create_index("ix_macro_indicators_provider_id", "macro_indicators", ["provider_id"], unique=False)

    op.add_column("prices_daily", sa.Column("available_at", sa.DateTime(), nullable=True))
    op.add_column("prices_daily", sa.Column("provider_id", sa.String(length=100), nullable=True))
    op.add_column("prices_daily", sa.Column("source_quality", sa.Float(), nullable=True))
    op.create_index("ix_prices_daily_available_at", "prices_daily", ["available_at"], unique=False)
    op.create_index("ix_prices_daily_provider_id", "prices_daily", ["provider_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_prices_daily_provider_id", table_name="prices_daily")
    op.drop_index("ix_prices_daily_available_at", table_name="prices_daily")
    op.drop_column("prices_daily", "source_quality")
    op.drop_column("prices_daily", "provider_id")
    op.drop_column("prices_daily", "available_at")

    op.drop_index("ix_macro_indicators_provider_id", table_name="macro_indicators")
    op.drop_index("ix_macro_indicators_available_at", table_name="macro_indicators")
    op.drop_column("macro_indicators", "source_quality")
    op.drop_column("macro_indicators", "provider_id")
    op.drop_column("macro_indicators", "available_at")

    op.drop_index("ix_news_articles_provider_id", table_name="news_articles")
    op.drop_index("ix_news_articles_available_at", table_name="news_articles")
    op.drop_column("news_articles", "raw_payload")
    op.drop_column("news_articles", "fallback_used")
    op.drop_column("news_articles", "source_quality")
    op.drop_column("news_articles", "provider_id")
    op.drop_column("news_articles", "available_at")

    op.drop_index("ix_data_connectors_last_status", table_name="data_connectors")
    op.drop_index("ix_data_connectors_configured", table_name="data_connectors")
    op.drop_index("ix_data_connectors_enabled", table_name="data_connectors")
    op.drop_index("ix_data_connectors_category", table_name="data_connectors")
    op.drop_index("ix_data_connectors_provider_id", table_name="data_connectors")
    op.drop_table("data_connectors")
