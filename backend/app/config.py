from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env")

    database_url: str = "postgresql+asyncpg://borsa:borsa123@localhost:5432/borsa"
    sync_database_url: str = "postgresql://borsa:borsa123@localhost:5432/borsa"
    redis_url: str = "redis://localhost:6379/0"
    environment: str = "development"

    # MVP universe — top 20 liquid S&P 500 stocks
    mvp_tickers: list[str] = [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
        "META", "TSLA", "BRK-B", "JPM", "V",
        "UNH", "XOM", "JNJ", "MA", "PG",
        "HD", "CVX", "MRK", "LLY", "ABBV",
    ]

    # Backtest defaults
    transaction_cost_bps: float = 10.0  # 10 bps round-trip
    slippage_bps: float = 5.0
    min_trades_for_promotion: int = 30
    holdout_months: int = 18
    min_paper_trades_for_promotion: int = 10
    min_paper_hit_rate_2pct: float = 0.45
    max_paper_calibration_error_2pct: float = 0.20
    models_dir: str = "/app/models_store"

    # Scheduled automation. Defaults run after the US market week has closed.
    celery_timezone: str = "America/New_York"
    weekly_pipeline_day_of_week: str = "sat"
    weekly_pipeline_hour: int = 8
    weekly_pipeline_minute: int = 0
    paper_eval_day_of_week: str = "mon-fri"
    paper_eval_hour: int = 18
    paper_eval_minute: int = 30

    # Optional MLflow tracking. Disabled unless a tracking URI is configured.
    mlflow_tracking_uri: str | None = None
    mlflow_experiment_name: str = "borsa-research"

    # API auth — set API_KEY env var to enable Bearer token protection on write routes
    api_key: str | None = None

settings = Settings()
