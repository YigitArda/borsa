from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB
from app.database import Base


class IntradayEvent(Base):
    """Weekly intraday spike/crash event for a stock.

    Populated by IntradayEventDetector after each pipeline run.
    Used to train a spike predictor and as lookback features for the main model.
    """
    __tablename__ = "intraday_events"
    __table_args__ = (UniqueConstraint("stock_id", "week_ending"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    week_ending: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Spike magnitude (fraction of Monday open)
    max_intraday_up_pct: Mapped[float | None] = mapped_column(Float)    # max (high - open) / open across the week
    max_intraday_down_pct: Mapped[float | None] = mapped_column(Float)  # max (open - low) / open (positive = drop)
    high_low_range_pct: Mapped[float | None] = mapped_column(Float)     # (week_high - week_low) / week_low
    spike_type: Mapped[str | None] = mapped_column(String(10))          # "up" | "down" | "both" | "normal"
    spike_day: Mapped[date | None] = mapped_column(Date)                # day of largest single intraday move

    # Cause attribution (True if event detected that week)
    has_earnings: Mapped[bool] = mapped_column(Boolean, default=False)
    has_news_spike: Mapped[bool] = mapped_column(Boolean, default=False)   # news volume/sentiment spike
    has_macro_event: Mapped[bool] = mapped_column(Boolean, default=False)  # VIX spike or macro data release
    news_sentiment_delta: Mapped[float | None] = mapped_column(Float)      # sentiment change vs prior week
    vix_level: Mapped[float | None] = mapped_column(Float)                 # VIX at week start
    vix_change: Mapped[float | None] = mapped_column(Float)                # VIX weekly change

    # Pipeline state: which features changed most before → after
    # Keys = feature_name, values = {before, after, delta_pct}
    feature_delta: Mapped[dict | None] = mapped_column(JSONB)

    # Outcome
    actual_return: Mapped[float | None] = mapped_column(Float)  # full-week return (entry open → exit close)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
