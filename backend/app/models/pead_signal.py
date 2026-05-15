from sqlalchemy import Column, Integer, Float, String, Date, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from app.database import Base


class PEADSignal(Base):
    __tablename__ = "pead_signals"

    id = Column(Integer, primary_key=True)
    stock_id = Column(Integer, nullable=False, index=True)
    earnings_date = Column(Date, nullable=False)
    actual_eps = Column(Float, nullable=True)
    expected_eps = Column(Float, nullable=True)
    sue_score = Column(Float, nullable=True)
    earnings_day_return = Column(Float, nullable=True)
    post_earnings_week1 = Column(Float, nullable=True)
    earnings_volume_ratio = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("stock_id", "earnings_date", name="uq_pead_signals_stock_date"),
    )
