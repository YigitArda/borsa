from datetime import date, datetime
from sqlalchemy import Boolean, String, Date, DateTime, Float, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class WeeklyPrediction(Base):
    __tablename__ = "weekly_predictions"
    __table_args__ = (
        UniqueConstraint("week_starting", "stock_id", "strategy_id", name="uq_weekly_predictions_week_stock_strategy"),
    )

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


class PaperTrade(Base):
    """Forward-test record created from a weekly prediction.

    These rows are paper-only: they compare predicted weekly signals with
    subsequent realized price action and never imply live execution.
    """

    __tablename__ = "paper_trades"
    __table_args__ = (
        UniqueConstraint("prediction_id", name="uq_paper_trades_prediction"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    week_starting: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    stock_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    strategy_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    rank: Mapped[int | None] = mapped_column(Integer)

    prob_2pct: Mapped[float | None] = mapped_column(Float)
    prob_loss_2pct: Mapped[float | None] = mapped_column(Float)
    expected_return: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[str | None] = mapped_column(String(20))
    signal_summary: Mapped[str | None] = mapped_column(String(500))

    entry_date: Mapped[date | None] = mapped_column(Date)
    planned_exit_date: Mapped[date] = mapped_column(Date, nullable=False)
    exit_date: Mapped[date | None] = mapped_column(Date)
    entry_price: Mapped[float | None] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float)
    realized_return: Mapped[float | None] = mapped_column(Float)
    max_rise_in_period: Mapped[float | None] = mapped_column(Float)
    max_drawdown_in_period: Mapped[float | None] = mapped_column(Float)
    hit_2pct: Mapped[bool | None] = mapped_column(Boolean)
    hit_3pct: Mapped[bool | None] = mapped_column(Boolean)
    hit_loss_2pct: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime)
