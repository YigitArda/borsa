from datetime import date, datetime
from sqlalchemy import String, Date, DateTime, Float, Integer, Boolean, Text, JSON, UniqueConstraint, Index, func, desc
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class InsiderTransaction(Base):
    __tablename__ = "insider_transactions"
    __table_args__ = (
        UniqueConstraint(
            "stock_id", "filed_date", "insider_name", "transaction_type",
            name="uq_insider_tx",
        ),
        Index("ix_insider_transactions_stock_date", "stock_id", "filed_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    filed_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    insider_name: Mapped[str] = mapped_column(String(200), nullable=False)
    insider_title: Mapped[str | None] = mapped_column(String(200))
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    shares: Mapped[float | None] = mapped_column(Float)
    price_per_share: Mapped[float | None] = mapped_column(Float)
    total_value: Mapped[float | None] = mapped_column(Float)
    is_open_market: Mapped[bool] = mapped_column(Boolean, default=False)
    ownership_after: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(50), default="sec_form4")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class GovernmentContract(Base):
    __tablename__ = "government_contracts"
    __table_args__ = (
        UniqueConstraint("stock_id", "award_id", name="uq_gov_contract"),
        Index("ix_gov_contracts_stock_date", "stock_id", "award_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    award_id: Mapped[str] = mapped_column(String(100), nullable=False)
    award_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    awarding_agency: Mapped[str | None] = mapped_column(String(200))
    recipient_name: Mapped[str | None] = mapped_column(String(200))
    award_amount: Mapped[float | None] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(Text)
    contract_type: Mapped[str | None] = mapped_column(String(50))
    performance_end_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class InstitutionalPosition(Base):
    __tablename__ = "institutional_positions"
    __table_args__ = (
        UniqueConstraint(
            "stock_id", "filer_cik", "report_date",
            name="uq_inst_position",
        ),
        Index("ix_institutional_positions_stock_date", "stock_id", "report_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    filer_cik: Mapped[str] = mapped_column(String(20), nullable=False)
    filer_name: Mapped[str | None] = mapped_column(String(200))
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    shares_held: Mapped[float | None] = mapped_column(Float)
    market_value: Mapped[float | None] = mapped_column(Float)
    is_new_position: Mapped[bool] = mapped_column(Boolean, default=False)
    prev_shares: Mapped[float | None] = mapped_column(Float)
    change_pct: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SmallCapRadarResult(Base):
    __tablename__ = "smallcap_radar_results"
    __table_args__ = (
        UniqueConstraint("stock_id", "scan_date", name="uq_radar_scan"),
        Index("ix_smallcap_radar_score", "scan_date", desc("total_score")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    scan_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_score: Mapped[float | None] = mapped_column(Float)
    insider_score: Mapped[float | None] = mapped_column(Float)
    smart_money_score: Mapped[float | None] = mapped_column(Float)
    business_score: Mapped[float | None] = mapped_column(Float)
    structural_score: Mapped[float | None] = mapped_column(Float)
    sector_multiplier: Mapped[float | None] = mapped_column(Float)
    regime_multiplier: Mapped[float | None] = mapped_column(Float)
    signals_triggered: Mapped[list | None] = mapped_column(JSON)
    eliminated: Mapped[bool] = mapped_column(Boolean, default=False)
    elimination_reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
