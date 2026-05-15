from datetime import date, datetime
from sqlalchemy import String, Date, DateTime, Float, Integer, Boolean, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Stock(Base):
    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    exchange: Mapped[str | None] = mapped_column(String(20))
    ipo_date: Mapped[date | None] = mapped_column(Date)
    delisting_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class StockUniverseSnapshot(Base):
    __tablename__ = "stock_universe_snapshots"
    __table_args__ = (UniqueConstraint("snapshot_date", "index_name", "ticker"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    index_name: Mapped[str] = mapped_column(String(50), nullable=False)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    weight: Mapped[float | None] = mapped_column(Float)


class TickerAlias(Base):
    """Historical ticker mapping, e.g. FB -> META."""
    __tablename__ = "ticker_aliases"
    __table_args__ = (UniqueConstraint("old_ticker", "new_ticker", "effective_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    old_ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    new_ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CorporateAction(Base):
    """Imported corporate actions for audit and point-in-time data repair."""
    __tablename__ = "corporate_actions"
    __table_args__ = (UniqueConstraint("stock_id", "action_date", "action_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    action_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(String(500))
    data_source: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
