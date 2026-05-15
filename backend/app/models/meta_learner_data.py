from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, JSON, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MetaLearnerTrainingData(Base):
    __tablename__ = "meta_learner_training_data"
    __table_args__ = (
        UniqueConstraint("strategy_id", name="uq_meta_learner_training_strategy"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    features_json: Mapped[list] = mapped_column(JSON, nullable=False)
    label: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    paper_hit_rate: Mapped[float | None] = mapped_column(Float)
    meta_confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
