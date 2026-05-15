from datetime import datetime

from sqlalchemy import DateTime, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StrategyBanditArm(Base):
    __tablename__ = "strategy_bandit_arms"
    __table_args__ = (
        UniqueConstraint("strategy_id", name="uq_strategy_bandit_arms_strategy"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    alpha: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    beta: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
