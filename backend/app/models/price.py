from datetime import date, datetime
from sqlalchemy import String, Date, DateTime, Float, Integer, BigInteger, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class PriceDaily(Base):
    __tablename__ = "prices_daily"
    __table_args__ = (UniqueConstraint("stock_id", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    adj_close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    data_source: Mapped[str] = mapped_column(String(50), default="yfinance")
    available_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    provider_id: Mapped[str | None] = mapped_column(String(100), index=True)
    source_quality: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PriceWeekly(Base):
    __tablename__ = "prices_weekly"
    __table_args__ = (UniqueConstraint("stock_id", "week_ending"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    week_ending: Mapped[date] = mapped_column(Date, nullable=False, index=True)  # Friday
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    weekly_return: Mapped[float | None] = mapped_column(Float)
    realized_volatility: Mapped[float | None] = mapped_column(Float)
    max_drawdown_in_week: Mapped[float | None] = mapped_column(Float)
    max_rise_in_week: Mapped[float | None] = mapped_column(Float)
