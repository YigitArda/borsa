from datetime import datetime
from sqlalchemy import String, DateTime, Integer, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SignalStackerWeights(Base):
    __tablename__ = "signal_stacker_weights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    regime_type: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    weights_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    n_samples: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_trained: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
