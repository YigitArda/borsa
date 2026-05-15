from datetime import datetime
from sqlalchemy import String, DateTime, Float, Integer, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class KillSwitchEvent(Base):
    """Records each kill switch trigger event."""

    __tablename__ = "kill_switch_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trigger_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
    )  # paper_poor | drawdown | data_quality | vix_spike | confidence_anomaly | prediction_count | feature_drift | manual
    strategy_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    severity: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="warning",
    )  # warning | critical
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_by: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="active",
        index=True,
    )  # active | resolved | ignored
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class KillSwitchConfig(Base):
    """Singleton-ish config row for kill switch thresholds."""

    __tablename__ = "kill_switch_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    max_paper_drawdown_weeks: Mapped[int] = mapped_column(Integer, default=4)
    max_paper_drawdown_pct: Mapped[float] = mapped_column(Float, default=0.10)
    max_model_drawdown_pct: Mapped[float] = mapped_column(Float, default=0.15)
    min_data_quality_score: Mapped[float] = mapped_column(Float, default=50.0)
    max_vix_level: Mapped[float] = mapped_column(Float, default=40.0)
    confidence_distribution_threshold: Mapped[float] = mapped_column(Float, default=0.20)
    min_predictions_per_week: Mapped[int] = mapped_column(Integer, default=10)
    max_feature_drift_pct: Mapped[float] = mapped_column(Float, default=0.30)
    enabled: Mapped[bool] = mapped_column(
        String(5), default="true", nullable=False
    )  # stored as "true" | "false" for compatibility
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
