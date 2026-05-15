from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ResearchTrialBudget(Base):
    __tablename__ = "research_trial_budgets"
    __table_args__ = (
        UniqueConstraint("budget_date", name="uq_research_trial_budgets_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    budget_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    iterations_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_iterations: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
