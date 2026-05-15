from datetime import datetime
from sqlalchemy import String, DateTime, Float, Integer, JSON, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class AblationResult(Base):
    """Stores results of feature ablation tests for a strategy."""

    __tablename__ = "ablation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    base_strategy_id: Mapped[int | None] = mapped_column(Integer, index=True)
    feature_group: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="technical|financial|news|macro|sentiment|tech_macro|tech_financial|all",
    )
    features_removed: Mapped[list | None] = mapped_column(JSON)

    # Core metrics
    sharpe: Mapped[float | None] = mapped_column(Float)
    profit_factor: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    win_rate: Mapped[float | None] = mapped_column(Float)
    avg_return: Mapped[float | None] = mapped_column(Float)

    # Impact scores (relative to baseline)
    sharpe_impact: Mapped[float | None] = mapped_column(Float)
    profit_factor_impact: Mapped[float | None] = mapped_column(Float)
    drawdown_impact: Mapped[float | None] = mapped_column(Float)
    stability_score: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
