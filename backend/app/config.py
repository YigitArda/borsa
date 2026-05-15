from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://borsa:borsa123@localhost:5432/borsa"
    sync_database_url: str = "postgresql://borsa:borsa123@localhost:5432/borsa"
    redis_url: str = "redis://localhost:6379/0"

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

    # API auth — set API_KEY env var to enable Bearer token protection on write routes
    api_key: str | None = None

    class Config:
        env_file = ".env"


settings = Settings()
