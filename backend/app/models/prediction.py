from datetime import date, datetime
from sqlalchemy import String, Date, DateTime, Float, Integer, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class WeeklyPrediction(Base):
    __tablename__ = "weekly_predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_starting: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    stock_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    strategy_id: Mapped[int] = mapped_column(Integer, nullable=False)
    prob_2pct: Mapped[float | None] = mapped_column(Float)
    prob_loss_2pct: Mapped[float | None] = mapped_column(Float)
    expected_return: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[str | None] = mapped_column(String(20))  # low | medium | high
    rank: Mapped[int | None] = mapped_column(Integer)
    signal_summary: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
