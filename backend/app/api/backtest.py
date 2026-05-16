from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.backtest import BacktestRun, BacktestMetric
from app.models.portfolio import PortfolioSimulation, PortfolioSnapshot
from app.tasks.celery_app import enqueue_task

router = APIRouter(prefix="/backtest", tags=["backtest"])


class BacktestRequest(BaseModel):
    strategy_config: dict
    tickers: list[str]
    min_train_years: int = 5


class DirectBacktestRequest(BaseModel):
    model_type: str = "lightgbm"
    features: list[str] | None = None
    target: str = "target_2pct_1w"
    threshold: float = 0.5
    top_n: int = 5
    holding_weeks: int = 1
    stop_loss: float | None = None
    take_profit: float | None = None
    apply_liquidity_filter: bool = True
    tickers: list[str] | None = None
    min_train_years: int = 5
    cpcv_groups: int = 6
    cpcv_test_groups: int = 2


class PortfolioSimulationRequest(BaseModel):
    strategy_id: int
    backtest_run_id: int | None = None
    initial_capital: float = 100000.0
    max_positions: int = 5
    max_position_weight: float = 0.25
    sector_limit: float = 0.40
    cash_ratio: float = 0.10
    rebalance_frequency: str = "weekly"
    stop_loss: float | None = None
    take_profit: float | None = None
    transaction_cost_bps: float = 10.0
    slippage_bps: float = 5.0
    tickers: list[str] | None = None
    model_type: str = "lightgbm"
    features: list[str] | None = None
    target: str = "target_2pct_1w"
    threshold: float = 0.5
    top_n: int = 5
    holding_weeks: int = 1
    min_train_years: int = 5
    apply_liquidity_filter: bool = True


@router.post("/run")
async def run_backtest(req: BacktestRequest, db: AsyncSession = Depends(get_db)):
    """Queue a research loop iteration with the given strategy config."""
    from app.tasks.pipeline_tasks import run_research_loop
    task = enqueue_task(run_research_loop, n_iterations=1)
    return {"task_id": task.id, "status": "queued"}


@router.post("/direct")
async def run_direct_backtest(req: DirectBacktestRequest, db: AsyncSession = Depends(get_db)):
    """Run a walk-forward backtest synchronously and return fold results.

    Strategy Lab uses this to test arbitrary configs without going through the research loop.
    """
    from app.services.feature_engineering import TECHNICAL_FEATURES
    from app.config import settings

    config = {
        "model_type": req.model_type,
        "features": req.features or TECHNICAL_FEATURES,
        "target": req.target,
        "threshold": req.threshold,
        "top_n": req.top_n,
        "embargo_weeks": 4,
        "holding_weeks": req.holding_weeks,
        "stop_loss": req.stop_loss,
        "take_profit": req.take_profit,
        "apply_liquidity_filter": req.apply_liquidity_filter,
    }
    tickers = req.tickers or settings.mvp_tickers

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import settings as cfg
    engine = create_engine(cfg.sync_database_url)
    SyncSession = sessionmaker(bind=engine)
    session = SyncSession()

    try:
        from app.services.model_training import ModelTrainer
        trainer = ModelTrainer(session, config)
        folds = trainer.walk_forward(
            tickers,
            min_train_years=req.min_train_years,
            apply_liquidity_filter=req.apply_liquidity_filter,
        )

        if not folds:
            return {"status": "failed", "reason": "no walk-forward folds produced"}

        fold_results = [
            {
                "fold": f.fold,
                "train_start": str(f.train_start),
                "train_end": str(f.train_end),
                "test_start": str(f.test_start),
                "test_end": str(f.test_end),
                "metrics": f.metrics,
                "equity_curve": f.equity_curve or [],
            }
            for f in folds
        ]

        # Aggregate
        import numpy as np
        all_metrics = [f.metrics for f in folds if f.metrics]
        avg_metrics = {}
        if all_metrics:
            for key in all_metrics[0]:
                vals = [m.get(key) for m in all_metrics if m.get(key) is not None]
                avg_metrics[key] = round(float(np.mean(vals)), 4) if vals else None

        return {
            "status": "ok",
            "config": config,
            "n_folds": len(folds),
            "avg_metrics": avg_metrics,
            "folds": fold_results,
        }
    finally:
        session.close()


@router.post("/cpcv")
async def run_cpcv_backtest(req: DirectBacktestRequest, db: AsyncSession = Depends(get_db)):
    """Run combinatorial purged CV for robustness checks."""
    from app.services.feature_engineering import TECHNICAL_FEATURES
    from app.config import settings
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    config = {
        "model_type": req.model_type,
        "features": req.features or TECHNICAL_FEATURES,
        "target": req.target,
        "threshold": req.threshold,
        "top_n": req.top_n,
        "embargo_weeks": 4,
        "holding_weeks": req.holding_weeks,
        "stop_loss": req.stop_loss,
        "take_profit": req.take_profit,
    }
    tickers = req.tickers or settings.mvp_tickers
    engine = create_engine(settings.sync_database_url)
    SyncSession = sessionmaker(bind=engine)
    session = SyncSession()
    try:
        from app.services.model_training import ModelTrainer
        trainer = ModelTrainer(session, config)
        folds = trainer.combinatorial_purged_cv(
            tickers,
            n_groups=req.cpcv_groups,
            n_test_groups=req.cpcv_test_groups,
            apply_liquidity_filter=req.apply_liquidity_filter,
        )
        if not folds:
            return {"status": "failed", "reason": "no CPCV folds produced"}

        import numpy as np
        all_metrics = [f.metrics for f in folds if f.metrics]
        avg_metrics = {}
        if all_metrics:
            for key in all_metrics[0]:
                vals = [m.get(key) for m in all_metrics if m.get(key) is not None]
                avg_metrics[key] = round(float(np.mean(vals)), 4) if vals else None

        return {
            "status": "ok",
            "config": config,
            "n_folds": len(folds),
            "avg_metrics": avg_metrics,
            "folds": [
                {
                    "fold": f.fold,
                    "train_start": str(f.train_start),
                    "train_end": str(f.train_end),
                    "test_start": str(f.test_start),
                    "test_end": str(f.test_end),
                    "metrics": f.metrics,
                    "equity_curve": f.equity_curve or [],
                }
                for f in folds
            ],
        }
    finally:
        session.close()


@router.get("/{run_id}")
async def get_backtest(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(404, "Backtest run not found")
    metrics = await db.execute(
        select(BacktestMetric).where(BacktestMetric.backtest_run_id == run_id)
    )
    metric_rows = metrics.scalars().all()
    return {
        "id": run.id,
        "strategy_id": run.strategy_id,
        "status": run.status,
        "train_start": str(run.train_start),
        "train_end": str(run.train_end),
        "test_start": str(run.test_start),
        "test_end": str(run.test_end),
        "metrics": {m.metric_name: m.value for m in metric_rows},
    }


# ------------------------------------------------------------------
# Portfolio Simulation endpoints
# ------------------------------------------------------------------

@router.post("/portfolio")
async def run_portfolio_simulation(
    req: PortfolioSimulationRequest, db: AsyncSession = Depends(get_db)
):
    """Run a portfolio-level capital simulation from backtest trades."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import settings as cfg
    from app.services.feature_engineering import TECHNICAL_FEATURES
    from app.services.model_training import ModelTrainer
    from app.services.backtester import Backtester
    from app.services.portfolio_simulation import (
        PortfolioSimulator,
        SimulationConfig,
    )

    config = {
        "model_type": req.model_type,
        "features": req.features or TECHNICAL_FEATURES,
        "target": req.target,
        "threshold": req.threshold,
        "top_n": req.top_n,
        "embargo_weeks": 4,
        "holding_weeks": req.holding_weeks,
        "stop_loss": req.stop_loss,
        "take_profit": req.take_profit,
        "apply_liquidity_filter": req.apply_liquidity_filter,
    }
    tickers = req.tickers or cfg.mvp_tickers

    engine = create_engine(cfg.sync_database_url)
    SyncSession = sessionmaker(bind=engine)
    session = SyncSession()

    try:
        trainer = ModelTrainer(session, config)
        df = trainer.load_dataset(tickers)
        if df.empty:
            return {"status": "failed", "reason": "no data loaded"}

        predictions = trainer.predict_all(df)
        if predictions.empty:
            return {"status": "failed", "reason": "no predictions produced"}

        # Price data for backtester must come from the price table, not the feature dataset
        price_df = trainer._load_prices_for_tickers(tickers)

        backtester = Backtester(
            predictions,
            price_df,
            threshold=req.threshold,
            top_n=req.top_n,
            holding_weeks=req.holding_weeks,
            stop_loss=req.stop_loss,
            take_profit=req.take_profit,
        )
        result = backtester.run()

        # Convert Trade objects to dicts for portfolio simulator
        trades = [
            {
                "ticker": t.ticker,
                "stock_id": t.stock_id,
                "entry_date": t.entry_date,
                "exit_date": t.exit_date,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "return_pct": t.return_pct,
                "signal_strength": t.signal_strength,
            }
            for t in result.trades
        ]

        sim_config = SimulationConfig(
            initial_capital=req.initial_capital,
            max_positions=req.max_positions,
            max_position_weight=req.max_position_weight,
            sector_limit=req.sector_limit,
            cash_ratio=req.cash_ratio,
            rebalance_frequency=req.rebalance_frequency,
            stop_loss=req.stop_loss,
            take_profit=req.take_profit,
            transaction_cost_bps=req.transaction_cost_bps,
            slippage_bps=req.slippage_bps,
        )
        simulator = PortfolioSimulator(sim_config)
        sim_result = simulator.simulate(trades, price_df)

        # Persist simulation and snapshots
        sim = PortfolioSimulation(
            strategy_id=req.strategy_id,
            backtest_run_id=req.backtest_run_id,
            initial_capital=req.initial_capital,
            max_positions=req.max_positions,
            max_position_weight=req.max_position_weight,
            sector_limit=req.sector_limit,
            cash_ratio=req.cash_ratio,
            rebalance_frequency=req.rebalance_frequency,
            stop_loss=req.stop_loss,
            take_profit=req.take_profit,
            transaction_cost_bps=req.transaction_cost_bps,
            slippage_bps=req.slippage_bps,
        )
        session.add(sim)
        session.flush()

        for snap in sim_result.snapshots:
            snapshot = PortfolioSnapshot(
                simulation_id=sim.id,
                date=snap["date"],
                total_value=snap["total_value"],
                cash_value=snap["cash_value"],
                invested_value=snap["invested_value"],
                n_positions=snap["n_positions"],
                sector_exposure=snap["sector_exposure"],
                monthly_return=snap.get("monthly_return"),
                ytd_return=snap.get("ytd_return"),
                drawdown=snap.get("drawdown"),
            )
            session.add(snapshot)

        session.commit()

        return {
            "status": "ok",
            "simulation_id": sim.id,
            "equity_curve": [
                {"date": str(d), "value": float(v)}
                for d, v in sim_result.equity_curve.items()
            ],
            "drawdown_curve": [
                {"date": str(d), "value": float(v)}
                for d, v in sim_result.drawdown_curve.items()
            ],
            "monthly_returns": sim_result.monthly_returns,
            "yearly_returns": sim_result.yearly_returns,
            "worst_month": sim_result.worst_month,
            "best_month": sim_result.best_month,
            "consecutive_losses": sim_result.consecutive_losses,
            "portfolio_volatility": sim_result.portfolio_volatility,
            "trades_executed": len(result.trades),
        }
    finally:
        session.close()


@router.get("/portfolio/{simulation_id}")
async def get_portfolio_simulation(
    simulation_id: int, db: AsyncSession = Depends(get_db)
):
    """Get portfolio simulation summary."""
    sim = await db.get(PortfolioSimulation, simulation_id)
    if not sim:
        raise HTTPException(404, "Portfolio simulation not found")

    snapshots_result = await db.execute(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.simulation_id == simulation_id)
        .order_by(PortfolioSnapshot.date)
    )
    snaps = snapshots_result.scalars().all()

    equity_curve = [
        {"date": str(s.date), "value": s.total_value} for s in snaps
    ]
    drawdowns = [
        {"date": str(s.date), "value": s.drawdown} for s in snaps if s.drawdown is not None
    ]

    return {
        "id": sim.id,
        "strategy_id": sim.strategy_id,
        "backtest_run_id": sim.backtest_run_id,
        "initial_capital": sim.initial_capital,
        "max_positions": sim.max_positions,
        "max_position_weight": sim.max_position_weight,
        "sector_limit": sim.sector_limit,
        "cash_ratio": sim.cash_ratio,
        "rebalance_frequency": sim.rebalance_frequency,
        "stop_loss": sim.stop_loss,
        "take_profit": sim.take_profit,
        "transaction_cost_bps": sim.transaction_cost_bps,
        "slippage_bps": sim.slippage_bps,
        "created_at": str(sim.created_at),
        "equity_curve": equity_curve,
        "drawdown_curve": drawdowns,
        "final_value": equity_curve[-1]["value"] if equity_curve else sim.initial_capital,
    }


@router.get("/portfolio/{simulation_id}/snapshots")
async def get_portfolio_snapshots(
    simulation_id: int, db: AsyncSession = Depends(get_db)
):
    """Get all daily snapshots for a portfolio simulation."""
    result = await db.execute(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.simulation_id == simulation_id)
        .order_by(PortfolioSnapshot.date)
    )
    rows = result.scalars().all()
    return {
        "simulation_id": simulation_id,
        "count": len(rows),
        "snapshots": [
            {
                "date": str(r.date),
                "total_value": r.total_value,
                "cash_value": r.cash_value,
                "invested_value": r.invested_value,
                "n_positions": r.n_positions,
                "sector_exposure": r.sector_exposure,
                "monthly_return": r.monthly_return,
                "ytd_return": r.ytd_return,
                "drawdown": r.drawdown,
            }
            for r in rows
        ],
    }
