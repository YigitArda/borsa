from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RLAgentQTable(Base):
    __tablename__ = "rl_agent_qtable"
    __table_args__ = (
        UniqueConstraint("agent_name", name="uq_rl_agent_qtable_agent"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    qtable_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    epsilon: Mapped[float] = mapped_column(Float, default=0.30, nullable=False)
    steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
