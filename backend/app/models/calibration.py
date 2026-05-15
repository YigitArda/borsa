from datetime import date, datetime
from sqlalchemy import String, Date, DateTime, Float, Integer, JSON, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ProbabilityCalibration(Base):
    """Stores per-strategy probability calibration metrics and reliability data.

    Each row represents a calibration snapshot for a strategy over a given
    week_starting period, computed from historical predictions vs actuals.
    """

    __tablename__ = "probability_calibrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    week_starting: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    brier_score: Mapped[float | None] = mapped_column(Float)
    calibration_error: Mapped[float | None] = mapped_column(Float)

    prob_buckets: Mapped[list[dict] | None] = mapped_column(JSON)
    """List of bucket dicts, e.g.:
    [{"bucket": "0.5-0.6", "predicted_avg": 0.55, "actual_rate": 0.52, "count": 10}, ...]
    """

    reliability_data: Mapped[dict | None] = mapped_column(JSON)
    """Data for reliability diagram, e.g.:
    {"prob_pred": [0.1, 0.2, ...], "prob_true": [0.12, 0.18, ...], "counts": [5, 8, ...]}
    """

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
