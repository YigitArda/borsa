from datetime import datetime, date

from sqlalchemy import Date, DateTime, Integer, String, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DataSourceHealth(Base):
    """Event log for external data source attempts and fallback usage."""

    __tablename__ = "data_source_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_used: Mapped[str | None] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok", index=True)
    target_ticker: Mapped[str | None] = mapped_column(String(20), index=True)
    week_ending: Mapped[date | None] = mapped_column(Date, index=True)
    message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
