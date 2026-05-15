from datetime import date, datetime
from sqlalchemy import String, Date, DateTime, Float, Integer, JSON, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class DataQualityScore(Base):
    """Per-stock per-week data quality scorecard."""
    __tablename__ = "data_quality_scores"
    __table_args__ = (UniqueConstraint("stock_id", "week_ending", name="uq_dq_score_stock_week"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    week_ending: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    overall_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    price_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    feature_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    financial_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    news_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    macro_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
