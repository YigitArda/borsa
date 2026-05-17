from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env")

    # Override these in .env. Defaults intentionally avoid embedding secrets.
    database_url: str = "postgresql+asyncpg://borsa@localhost:5432/borsa"
    sync_database_url: str = "postgresql://borsa@localhost:5432/borsa"
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

    # Self-improving research controls
    research_max_daily_iterations: int = 100
    bayesian_opt_interval: int = 10
    bayesian_opt_trials: int = 50
    enable_bayesian_optimization: bool = True
    genetic_population_size: int = 10
    population_search_size: int = 10

    # CORS — comma-separated allowed origins. Add production domain here.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # API auth — set API_KEY env var to enable Bearer token protection on write routes
    api_key: str | None = None
    jwt_secret: str | None = None
    fred_api_key: str | None = None
    polygon_api_key: str | None = None
    adanos_api_key: str | None = None
    adanos_base_url: str | None = None
    kraken_api_key: str | None = None
    kraken_api_secret: str | None = None
    kraken_pairs: list[str] = ["XBTUSD", "ETHUSD"]
    akshare_enabled: bool = False
    worldbank_default_countries: list[str] = ["US"]
    imf_default_countries: list[str] = ["USA"]
    connector_request_timeout: int = 20
    connector_max_retries: int = 3

    # Reddit API (https://www.reddit.com/prefs/apps → "script" app)
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = "borsa-research-bot/1.0"

    # X / Twitter API v2 Bearer Token
    # Free tier: 7-day recent search only.
    # Pro/Academic tier: full-archive search (tweets/search/all).
    twitter_bearer_token: str | None = None

    # Notification settings
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    slack_webhook_url: str | None = None

    # Backup settings
    backup_dir: str = "./backups"
    backup_retention_days: int = 7

settings = Settings()
