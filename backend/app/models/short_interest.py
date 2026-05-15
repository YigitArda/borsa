from sqlalchemy import Column, Integer, Float, String, Date, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from app.database import Base


class ShortInterestData(Base):
    __tablename__ = "short_interest_data"

    id = Column(Integer, primary_key=True)
    stock_id = Column(Integer, nullable=False, index=True)
    report_date = Column(Date, nullable=False)
    short_shares = Column(Float, nullable=True)
    float_shares = Column(Float, nullable=True)
    short_ratio = Column(Float, nullable=True)       # days to cover
    short_pct_float = Column(Float, nullable=True)   # SI / float
    avg_daily_volume = Column(Float, nullable=True)
    short_volume_ratio = Column(Float, nullable=True)  # from FINRA daily SHO
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("stock_id", "report_date", name="uq_short_interest_stock_date"),
    )
