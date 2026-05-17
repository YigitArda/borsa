from datetime import date, datetime
from sqlalchemy import String, Date, DateTime, Float, Integer, JSON, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class MacroIndicator(Base):
    __tablename__ = "macro_indicators"
    __table_args__ = (UniqueConstraint("indicator_code", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    indicator_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # VIX, TNX_10Y, SP500, NASDAQ, FED_RATE, CPI_YOY, YIELD_CURVE, CREDIT_SPREAD_BBB, OECD_CLI_USA
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    available_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    provider_id: Mapped[str | None] = mapped_column(String(100), index=True)
    value: Mapped[float | None] = mapped_column(Float)
    source_quality: Mapped[float | None] = mapped_column(Float)
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
