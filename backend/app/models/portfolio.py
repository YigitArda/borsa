from datetime import date, datetime
from sqlalchemy import String, Date, DateTime, Float, Integer, JSON, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class PortfolioSimulation(Base):
    __tablename__ = "portfolio_simulations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    backtest_run_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("backtest_runs.id"), nullable=True, index=True
    )

    initial_capital: Mapped[float] = mapped_column(Float, default=100000.0)
    max_positions: Mapped[int] = mapped_column(Integer, default=5)
    max_position_weight: Mapped[float] = mapped_column(Float, default=0.25)
    sector_limit: Mapped[float] = mapped_column(Float, default=0.40)
    cash_ratio: Mapped[float] = mapped_column(Float, default=0.10)

    rebalance_frequency: Mapped[str] = mapped_column(
        String(20), default="weekly"
    )  # weekly | monthly | quarterly
    stop_loss: Mapped[float | None] = mapped_column(Float)
    take_profit: Mapped[float | None] = mapped_column(Float)
    transaction_cost_bps: Mapped[float] = mapped_column(Float, default=10.0)
    slippage_bps: Mapped[float] = mapped_column(Float, default=5.0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    simulation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portfolio_simulations.id"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    total_value: Mapped[float] = mapped_column(Float, nullable=False)
    cash_value: Mapped[float] = mapped_column(Float, nullable=False)
    invested_value: Mapped[float] = mapped_column(Float, nullable=False)

    n_positions: Mapped[int] = mapped_column(Integer, default=0)
    sector_exposure: Mapped[dict] = mapped_column(JSON, default=dict)

    monthly_return: Mapped[float | None] = mapped_column(Float)
    ytd_return: Mapped[float | None] = mapped_column(Float)
    drawdown: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
