from datetime import date, datetime
from sqlalchemy import String, Date, DateTime, Float, Integer, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class MarketRegime(Base):
    __tablename__ = "market_regimes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_starting: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    week_ending: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    regime_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )  # bull | bear | sideways | high_vol | low_vol | risk_on | risk_off

    # Indicator snapshots
    spy_200ma_ratio: Mapped[float | None] = mapped_column(Float)
    vix_level: Mapped[float | None] = mapped_column(Float)
    vix_change: Mapped[float | None] = mapped_column(Float)
    nasdaq_spy_ratio: Mapped[float | None] = mapped_column(Float)
    market_breadth: Mapped[float | None] = mapped_column(Float)
    yield_trend: Mapped[float | None] = mapped_column(Float)
    sector_rotation_score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
