from datetime import date, datetime
from sqlalchemy import String, Date, DateTime, Float, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class MacroIndicator(Base):
    __tablename__ = "macro_indicators"
    __table_args__ = (UniqueConstraint("indicator_code", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    indicator_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # VIX, TNX_10Y, SP500, NASDAQ, FED_RATE, CPI_YOY
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    value: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
