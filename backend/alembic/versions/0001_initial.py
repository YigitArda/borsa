"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-15

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stocks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticker", sa.String(20), unique=True, nullable=False),
        sa.Column("name", sa.String(200)),
        sa.Column("sector", sa.String(100)),
        sa.Column("industry", sa.String(100)),
        sa.Column("exchange", sa.String(20)),
        sa.Column("ipo_date", sa.Date),
        sa.Column("delisting_date", sa.Date),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_stocks_ticker", "stocks", ["ticker"])

    op.create_table(
        "stock_universe_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("snapshot_date", sa.Date, nullable=False),
        sa.Column("index_name", sa.String(50), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("weight", sa.Float),
    )

    op.create_table(
        "prices_daily",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_id", sa.Integer, nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("open", sa.Float),
        sa.Column("high", sa.Float),
        sa.Column("low", sa.Float),
        sa.Column("close", sa.Float),
        sa.Column("adj_close", sa.Float),
        sa.Column("volume", sa.BigInteger),
        sa.Column("data_source", sa.String(50), default="yfinance"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("stock_id", "date", name="uq_prices_daily_stock_date"),
    )
    op.create_index("ix_prices_daily_stock_id", "prices_daily", ["stock_id"])
    op.create_index("ix_prices_daily_date", "prices_daily", ["date"])

    op.create_table(
        "prices_weekly",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_id", sa.Integer, nullable=False),
        sa.Column("week_ending", sa.Date, nullable=False),
        sa.Column("open", sa.Float),
        sa.Column("high", sa.Float),
        sa.Column("low", sa.Float),
        sa.Column("close", sa.Float),
        sa.Column("volume", sa.BigInteger),
        sa.Column("weekly_return", sa.Float),
        sa.Column("realized_volatility", sa.Float),
        sa.Column("max_drawdown_in_week", sa.Float),
        sa.UniqueConstraint("stock_id", "week_ending", name="uq_prices_weekly_stock_week"),
    )
    op.create_index("ix_prices_weekly_stock_id", "prices_weekly", ["stock_id"])
    op.create_index("ix_prices_weekly_week_ending", "prices_weekly", ["week_ending"])

    op.create_table(
        "financial_metrics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_id", sa.Integer, nullable=False),
        sa.Column("fiscal_period_end", sa.Date, nullable=False),
        sa.Column("as_of_date", sa.Date),
        sa.Column("metric_name", sa.String(100), nullable=False),
        sa.Column("value", sa.Float),
        sa.Column("is_ttm", sa.Boolean, default=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("stock_id", "fiscal_period_end", "metric_name", name="uq_financial_metrics"),
    )
    op.create_index("ix_financial_metrics_stock_id", "financial_metrics", ["stock_id"])

    op.create_table(
        "news_articles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("url_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("published_at", sa.DateTime),
        sa.Column("source", sa.String(100)),
        sa.Column("headline", sa.String(500)),
        sa.Column("body_excerpt", sa.Text),
        sa.Column("ticker_mentions", sa.JSON),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "news_analysis",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("news_id", sa.Integer, nullable=False),
        sa.Column("stock_id", sa.Integer, nullable=False),
        sa.Column("sentiment_score", sa.Float),
        sa.Column("sentiment_label", sa.String(20)),
        sa.Column("relevance_score", sa.Float),
        sa.Column("is_earnings", sa.Boolean, default=False),
        sa.Column("is_legal", sa.Boolean, default=False),
        sa.Column("is_product_launch", sa.Boolean, default=False),
        sa.Column("is_analyst_action", sa.Boolean, default=False),
        sa.Column("is_management_change", sa.Boolean, default=False),
        sa.Column("model_version", sa.String(50), default="vader_v1"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_news_analysis_stock_id", "news_analysis", ["stock_id"])

    op.create_table(
        "social_sentiment",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_id", sa.Integer, nullable=False),
        sa.Column("week_ending", sa.String(20), nullable=False),
        sa.Column("mention_count", sa.Integer),
        sa.Column("mention_momentum", sa.Float),
        sa.Column("sentiment_polarity", sa.Float),
        sa.Column("hype_risk", sa.Float),
        sa.Column("abnormal_attention", sa.Float),
        sa.Column("source", sa.String(50), default="reddit"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "macro_indicators",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("indicator_code", sa.String(50), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("value", sa.Float),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("indicator_code", "date", name="uq_macro_indicator_date"),
    )
    op.create_index("ix_macro_indicators_code", "macro_indicators", ["indicator_code"])
    op.create_index("ix_macro_indicators_date", "macro_indicators", ["date"])

    op.create_table(
        "features_weekly",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_id", sa.Integer, nullable=False),
        sa.Column("week_ending", sa.Date, nullable=False),
        sa.Column("feature_name", sa.String(100), nullable=False),
        sa.Column("value", sa.Float),
        sa.Column("feature_set_version", sa.String(50), default="v1"),
        sa.Column("computed_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("stock_id", "week_ending", "feature_name", "feature_set_version", name="uq_features_weekly"),
    )
    op.create_index("ix_features_weekly_stock_id", "features_weekly", ["stock_id"])
    op.create_index("ix_features_weekly_week_ending", "features_weekly", ["week_ending"])

    op.create_table(
        "labels_weekly",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_id", sa.Integer, nullable=False),
        sa.Column("week_ending", sa.Date, nullable=False),
        sa.Column("target_name", sa.String(100), nullable=False),
        sa.Column("value", sa.Float),
        sa.Column("computed_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("stock_id", "week_ending", "target_name", name="uq_labels_weekly"),
    )
    op.create_index("ix_labels_weekly_stock_id", "labels_weekly", ["stock_id"])

    op.create_table(
        "strategies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("config", sa.JSON, nullable=False),
        sa.Column("parent_strategy_id", sa.Integer),
        sa.Column("status", sa.String(20), default="research"),
        sa.Column("generation", sa.Integer, default=0),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("promoted_at", sa.DateTime),
        sa.Column("notes", sa.Text),
    )
    op.create_index("ix_strategies_status", "strategies", ["status"])

    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("strategy_id", sa.Integer, nullable=False),
        sa.Column("model_path", sa.String(500)),
        sa.Column("feature_set_version", sa.String(50)),
        sa.Column("train_start", sa.String(20)),
        sa.Column("train_end", sa.String(20)),
        sa.Column("metrics", sa.JSON),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "model_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("strategy_id", sa.Integer, nullable=False),
        sa.Column("model_type", sa.String(50)),
        sa.Column("fold", sa.Integer),
        sa.Column("train_rows", sa.Integer),
        sa.Column("test_rows", sa.Integer),
        sa.Column("hyperparams", sa.JSON),
        sa.Column("metrics", sa.JSON),
        sa.Column("feature_importance", sa.JSON),
        sa.Column("model_path", sa.String(500)),
        sa.Column("status", sa.String(20), default="completed"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_model_runs_strategy_id", "model_runs", ["strategy_id"])

    op.create_table(
        "strategy_rules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("strategy_id", sa.Integer, nullable=False),
        sa.Column("rule_type", sa.String(50)),
        sa.Column("description", sa.Text),
        sa.Column("feature_name", sa.String(100)),
        sa.Column("operator", sa.String(10)),
        sa.Column("threshold", sa.Float),
        sa.Column("importance", sa.Float),
    )

    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("strategy_id", sa.Integer, nullable=False),
        sa.Column("run_type", sa.String(30)),
        sa.Column("train_start", sa.Date),
        sa.Column("train_end", sa.Date),
        sa.Column("test_start", sa.Date),
        sa.Column("test_end", sa.Date),
        sa.Column("status", sa.String(20), default="pending"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime),
    )
    op.create_index("ix_backtest_runs_strategy_id", "backtest_runs", ["strategy_id"])

    op.create_table(
        "backtest_metrics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("backtest_run_id", sa.Integer, nullable=False),
        sa.Column("metric_name", sa.String(100), nullable=False),
        sa.Column("value", sa.Float),
    )
    op.create_index("ix_backtest_metrics_run_id", "backtest_metrics", ["backtest_run_id"])

    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("backtest_run_id", sa.Integer, nullable=False),
        sa.Column("stock_id", sa.Integer, nullable=False),
        sa.Column("entry_date", sa.Date),
        sa.Column("exit_date", sa.Date),
        sa.Column("entry_price", sa.Float),
        sa.Column("exit_price", sa.Float),
        sa.Column("return_pct", sa.Float),
        sa.Column("pnl", sa.Float),
        sa.Column("signal_strength", sa.Float),
        sa.Column("exit_reason", sa.String(50)),
    )
    op.create_index("ix_backtest_trades_run_id", "backtest_trades", ["backtest_run_id"])

    op.create_table(
        "walk_forward_results",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("strategy_id", sa.Integer, nullable=False),
        sa.Column("fold", sa.Integer),
        sa.Column("train_start", sa.Date),
        sa.Column("train_end", sa.Date),
        sa.Column("test_start", sa.Date),
        sa.Column("test_end", sa.Date),
        sa.Column("metrics", sa.JSON),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_walk_forward_strategy_id", "walk_forward_results", ["strategy_id"])

    op.create_table(
        "weekly_predictions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("week_starting", sa.Date, nullable=False),
        sa.Column("stock_id", sa.Integer, nullable=False),
        sa.Column("strategy_id", sa.Integer, nullable=False),
        sa.Column("prob_2pct", sa.Float),
        sa.Column("prob_loss_2pct", sa.Float),
        sa.Column("expected_return", sa.Float),
        sa.Column("confidence", sa.String(20)),
        sa.Column("rank", sa.Integer),
        sa.Column("signal_summary", sa.String(500)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_weekly_predictions_week", "weekly_predictions", ["week_starting"])

    op.create_table(
        "selected_stocks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("week_starting", sa.String(20), nullable=False),
        sa.Column("stock_id", sa.Integer, nullable=False),
        sa.Column("strategy_id", sa.Integer, nullable=False),
        sa.Column("rank", sa.Integer),
        sa.Column("signal", sa.String(30)),
        sa.Column("confidence", sa.String(20)),
        sa.Column("risk_level", sa.String(20)),
        sa.Column("reasoning", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "job_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), default="running"),
        sa.Column("started_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime),
        sa.Column("error", sa.Text),
        sa.Column("metadata", sa.Text),
    )
    op.create_index("ix_job_runs_job_name", "job_runs", ["job_name"])


def downgrade() -> None:
    for table in [
        "job_runs", "selected_stocks", "weekly_predictions", "walk_forward_results",
        "backtest_trades", "backtest_metrics", "backtest_runs", "strategy_rules",
        "model_runs", "model_versions", "strategies", "labels_weekly", "features_weekly",
        "macro_indicators", "social_sentiment", "news_analysis", "news_articles",
        "financial_metrics", "prices_weekly", "prices_daily", "stock_universe_snapshots", "stocks",
    ]:
        op.drop_table(table)
