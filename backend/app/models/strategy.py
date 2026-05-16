from datetime import datetime
from sqlalchemy import Boolean, String, DateTime, Integer, Float, Text, JSON, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    parent_strategy_id: Mapped[int | None] = mapped_column(Integer)
    # status: research | promoted | archived
    status: Mapped[str] = mapped_column(String(20), default="research", index=True)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    model_path: Mapped[str] = mapped_column(String(500))
    feature_set_version: Mapped[str | None] = mapped_column(String(50))
    train_start: Mapped[str | None] = mapped_column(String(20))
    train_end: Mapped[str | None] = mapped_column(String(20))
    metrics: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Model Registry & Versioning enhancements
    status: Mapped[str] = mapped_column(
        String(20), default="research", nullable=False, index=True
    )
    holdout_period: Mapped[dict | None] = mapped_column(JSON)
    validation_period: Mapped[dict | None] = mapped_column(JSON)
    parent_model_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("model_versions.id"), nullable=True, index=True
    )
    promotion_reason: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    hyperparams: Mapped[dict | None] = mapped_column(JSON)
    model_file_hash: Mapped[str | None] = mapped_column(String(64))


class ModelPromotion(Base):
    """Records each time a strategy passes the acceptance gate and is promoted."""
    __tablename__ = "model_promotions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    promoted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    avg_sharpe: Mapped[float | None] = mapped_column(Float)
    deflated_sharpe: Mapped[float | None] = mapped_column(Float)
    probabilistic_sr: Mapped[float | None] = mapped_column(Float)
    permutation_pvalue: Mapped[float | None] = mapped_column(Float)
    spy_sharpe: Mapped[float | None] = mapped_column(Float)
    outperforms_spy: Mapped[bool | None] = mapped_column(Boolean)
    avg_win_rate: Mapped[float | None] = mapped_column(Float)
    total_trades: Mapped[int | None] = mapped_column(Integer)
    min_drawdown: Mapped[float | None] = mapped_column(Float)
    avg_profit_factor: Mapped[float | None] = mapped_column(Float)
    concentration_ok: Mapped[bool | None] = mapped_column(Boolean)
    details: Mapped[dict | None] = mapped_column(JSON)
