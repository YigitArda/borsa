from datetime import date, datetime
from sqlalchemy import String, Date, DateTime, Float, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class FeatureWeekly(Base):
    """Long-format feature store — one row per (stock, week, feature)."""
    __tablename__ = "features_weekly"
    __table_args__ = (UniqueConstraint("stock_id", "week_ending", "feature_name", "feature_set_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    week_ending: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    feature_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    value: Mapped[float | None] = mapped_column(Float)
    feature_set_version: Mapped[str] = mapped_column(String(50), default="v1")
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LabelWeekly(Base):
    """Target labels for each (stock, week)."""
    __tablename__ = "labels_weekly"
    __table_args__ = (UniqueConstraint("stock_id", "week_ending", "target_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    week_ending: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    target_name: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
