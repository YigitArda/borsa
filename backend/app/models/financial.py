from datetime import date, datetime
from sqlalchemy import String, Date, DateTime, Float, Integer, Boolean, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class FinancialMetric(Base):
    """Point-in-time financial metrics per stock per fiscal period."""
    __tablename__ = "financial_metrics"
    __table_args__ = (
        UniqueConstraint("stock_id", "fiscal_period_end", "metric_name", "as_of_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    fiscal_period_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # as_of = when this data became publicly available (earnings report date)
    as_of_date: Mapped[date | None] = mapped_column(Date, index=True)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    is_ttm: Mapped[bool] = mapped_column(Boolean, default=False)  # trailing twelve months
    data_source: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
