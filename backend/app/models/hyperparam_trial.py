from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class HyperparamTrial(Base):
    __tablename__ = "hyperparam_trials"
    __table_args__ = (
        UniqueConstraint("study_name", "trial_number", name="uq_hyperparam_trials_study_trial"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    study_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    trial_number: Mapped[int] = mapped_column(Integer, nullable=False)
    params_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    sharpe: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), default="completed", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
