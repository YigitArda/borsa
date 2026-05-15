from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.backtest import WalkForwardResult, BacktestMetric, BacktestRun
from app.models.model_run import ModelRun
from app.models.strategy import Strategy, ModelPromotion
from app.models.macro import MacroIndicator
from app.models.feature import FeatureWeekly
from app.models.price import PriceWeekly
from app.models.stock import Stock

router = APIRouter(prefix="/research", tags=["research"])


@router.get("/feature-importance/{strategy_id}")
async def get_feature_importance(strategy_id: int, db: AsyncSession = Depends(get_db)):
    runs = await db.execute(
        select(ModelRun)
        .where(ModelRun.strategy_id == strategy_id)
        .order_by(ModelRun.created_at.desc())
        .limit(1)
    )
    run = runs.scalar_one_or_none()
    if not run or not run.feature_importance:
        return {"strategy_id": strategy_id, "feature_importance": {}}
    return {"strategy_id": strategy_id, "feature_importance": run.feature_importance}


@router.get("/walk-forward/{strategy_id}")
async def get_walk_forward(strategy_id: int, db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(WalkForwardResult)
        .where(WalkForwardResult.strategy_id == strategy_id)
        .order_by(WalkForwardResult.fold)
    )
    folds = rows.scalars().all()
    return [
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


@router.get("/compare")
async def compare_strategies(strategy_ids: str, db: AsyncSession = Depends(get_db)):
    """Compare multiple strategies. Pass strategy_ids as comma-separated."""
    ids = [int(i) for i in strategy_ids.split(",") if i.strip().isdigit()]
    result = []
    for sid in ids:
        strategy = await db.get(Strategy, sid)
        if not strategy:
            continue
        runs = await db.execute(
            select(WalkForwardResult).where(WalkForwardResult.strategy_id == sid)
        )
        folds = runs.scalars().all()
        if not folds:
            continue
        all_metrics = [f.metrics for f in folds if f.metrics]
        if not all_metrics:
            continue
        avg = {}
        for key in all_metrics[0]:
            vals = [m.get(key) for m in all_metrics if m.get(key) is not None]
            avg[key] = round(sum(vals) / len(vals), 4) if vals else None
        result.append({
            "strategy_id": sid,
            "name": strategy.name,
            "status": strategy.status,
            "generation": strategy.generation,
            "avg_metrics": avg,
        })
    return result


@router.get("/risk-warnings")
async def get_risk_warnings(db: AsyncSession = Depends(get_db)):
    """Identify strategies that are underperforming, have data quality issues, or show leakage signals."""
    import numpy as np
    from app.models.feature import FeatureWeekly
    from app.models.stock import Stock
    warnings = []

    promoted = await db.execute(
        select(Strategy).where(Strategy.status == "promoted")
    )
    for s in promoted.scalars().all():
        all_folds_q = await db.execute(
            select(WalkForwardResult)
            .where(WalkForwardResult.strategy_id == s.id)
            .order_by(WalkForwardResult.fold)
        )
        all_folds = all_folds_q.scalars().all()
        if not all_folds:
            continue

        # 1. Sharpe degradation in recent folds
        recent_folds = all_folds[-3:]
        recent_sharpes = [f.metrics.get("sharpe", 0) for f in recent_folds if f.metrics]
        if recent_sharpes and sum(recent_sharpes) / len(recent_sharpes) < 0.2:
            warnings.append({
                "strategy_id": s.id,
                "name": s.name,
                "warning": "Recent 3-fold avg Sharpe < 0.2 — strategy may be degrading",
                "severity": "high",
            })

        # 2. OOS suspiciously close to or better than IS (leakage signal)
        # Compare first-fold vs last-fold: if OOS Sharpe >= IS avg we flag it
        if len(all_folds) >= 3:
            early_sharpes = [f.metrics.get("sharpe", 0) for f in all_folds[:3] if f.metrics]
            late_sharpes = [f.metrics.get("sharpe", 0) for f in all_folds[-3:] if f.metrics]
            if early_sharpes and late_sharpes:
                # If OOS (late) is better than IS (early), that's suspicious
                if np.mean(late_sharpes) >= np.mean(early_sharpes) * 1.1:
                    warnings.append({
                        "strategy_id": s.id,
                        "name": s.name,
                        "warning": (
                            f"OOS Sharpe ({np.mean(late_sharpes):.2f}) ≥ IS Sharpe ({np.mean(early_sharpes):.2f}) × 1.1 "
                            "— possible data leakage or lucky regime"
                        ),
                        "severity": "medium",
                    })

    # 3. Feature data drift — compare feature means last 6 months vs previous 6 months
    from datetime import date
    from dateutil.relativedelta import relativedelta
    now = date.today()
    cutoff_recent = now - relativedelta(months=6)
    cutoff_old = now - relativedelta(months=12)

    drift_features_checked = ["rsi_14", "volume_zscore", "return_1w", "VIX", "macd"]
    drift_issues = []
    for fname in drift_features_checked:
        recent_q = await db.execute(
            select(func.avg(FeatureWeekly.value))
            .where(
                FeatureWeekly.feature_name == fname,
                FeatureWeekly.week_ending >= cutoff_recent,
            )
        )
        old_q = await db.execute(
            select(func.avg(FeatureWeekly.value))
            .where(
                FeatureWeekly.feature_name == fname,
                FeatureWeekly.week_ending >= cutoff_old,
                FeatureWeekly.week_ending < cutoff_recent,
            )
        )
        recent_avg = recent_q.scalar()
        old_avg = old_q.scalar()
        if recent_avg is None or old_avg is None or old_avg == 0:
            continue
        pct_change = abs(recent_avg - old_avg) / abs(old_avg)
        if pct_change > 0.3:  # >30% shift in feature mean
            drift_issues.append(f"{fname} shifted {pct_change*100:.0f}%")

    if drift_issues:
        warnings.append({
            "strategy_id": None,
            "name": "Feature Distribution Drift",
            "warning": f"Feature means shifted >30% in last 6 months vs prior 6: {', '.join(drift_issues)}",
            "severity": "medium",
        })

    # 4. Data freshness check — flag if any stock hasn't been updated in 2 weeks
    from app.models.price import PriceWeekly
    stale_q = await db.execute(
        select(Stock.ticker, func.max(PriceWeekly.week_ending).label("latest"))
        .join(PriceWeekly, PriceWeekly.stock_id == Stock.id)
        .where(Stock.is_active == True)
        .group_by(Stock.ticker)
    )
    stale_cutoff = now - relativedelta(weeks=2)
    stale_tickers = [row.ticker for row in stale_q.all() if row.latest and row.latest < stale_cutoff]
    if stale_tickers:
        warnings.append({
            "strategy_id": None,
            "name": "Stale Price Data",
            "warning": f"{len(stale_tickers)} stocks have no price data in 2+ weeks: {', '.join(stale_tickers[:5])}{'...' if len(stale_tickers) > 5 else ''}",
            "severity": "high",
        })

    return {"warnings": warnings, "count": len(warnings)}


@router.post("/sector-models")
async def run_sector_models(tickers: list[str] | None = None):
    """Train and evaluate sector-segmented models (Technology, Financials, etc.)."""
    from app.tasks.pipeline_tasks import _get_sync_session
    from app.services.model_training import ModelTrainer
    from app.services.research_loop import BASE_STRATEGY
    from app.config import settings as cfg
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(cfg.sync_database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        trainer = ModelTrainer(session, BASE_STRATEGY)
        results = trainer.train_per_sector(tickers or cfg.mvp_tickers)
        return {"status": "ok", "sectors": results}
    finally:
        session.close()


@router.get("/promotions")
async def get_promotions(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """All promotion events with statistical validation details."""
    rows = await db.execute(
        select(ModelPromotion).order_by(ModelPromotion.promoted_at.desc()).limit(limit)
    )
    promotions = rows.scalars().all()
    return [
        {
            "id": p.id,
            "strategy_id": p.strategy_id,
            "promoted_at": str(p.promoted_at),
            "avg_sharpe": p.avg_sharpe,
            "deflated_sharpe": p.deflated_sharpe,
            "probabilistic_sr": p.probabilistic_sr,
            "permutation_pvalue": p.permutation_pvalue,
            "spy_sharpe": p.spy_sharpe,
            "outperforms_spy": p.outperforms_spy,
            "avg_win_rate": p.avg_win_rate,
            "total_trades": p.total_trades,
            "min_drawdown": p.min_drawdown,
            "concentration_ok": p.concentration_ok,
            "details": p.details,
        }
        for p in promotions
    ]


@router.get("/rolling-sharpe/{strategy_id}")
async def get_rolling_sharpe(strategy_id: int, window: int = 4, db: AsyncSession = Depends(get_db)):
    """Rolling Sharpe across walk-forward folds (window = number of folds).

    Also returns fold-by-fold metrics for charting in Model Comparison.
    """
    import numpy as np
    folds_q = await db.execute(
        select(WalkForwardResult)
        .where(WalkForwardResult.strategy_id == strategy_id)
        .order_by(WalkForwardResult.fold)
    )
    folds = folds_q.scalars().all()
    if not folds:
        return {"strategy_id": strategy_id, "rolling_sharpe": [], "fold_sharpes": []}

    fold_sharpes = [
        {"fold": f.fold, "test_start": str(f.test_start), "sharpe": (f.metrics or {}).get("sharpe")}
        for f in folds
    ]
    sharpes = [s["sharpe"] or 0.0 for s in fold_sharpes]

    rolling = []
    for i in range(len(sharpes)):
        start = max(0, i - window + 1)
        window_vals = sharpes[start: i + 1]
        rolling.append({
            "fold": fold_sharpes[i]["fold"],
            "test_start": fold_sharpes[i]["test_start"],
            "rolling_sharpe": round(float(np.mean(window_vals)), 4),
        })

    return {"strategy_id": strategy_id, "rolling_sharpe": rolling, "fold_sharpes": fold_sharpes}


@router.get("/trade-overlap")
async def get_trade_overlap(strategy_ids: str, db: AsyncSession = Depends(get_db)):
    """Compute trade overlap ratio between two strategies.

    Returns what fraction of trades (by ticker+week) are shared.
    """
    ids = [int(i) for i in strategy_ids.split(",") if i.strip().isdigit()]
    if len(ids) < 2:
        return {"error": "provide at least 2 strategy_ids"}

    trade_sets: dict[int, set] = {}
    for sid in ids:
        folds_q = await db.execute(
            select(WalkForwardResult).where(WalkForwardResult.strategy_id == sid)
        )
        folds = folds_q.scalars().all()
        keys = set()
        for fold in folds:
            for wfr in (fold.equity_curve or []):
                keys.add(wfr.get("date", ""))
        trade_sets[sid] = keys

    overlaps = {}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            sa, sb = trade_sets[a], trade_sets[b]
            union = sa | sb
            inter = sa & sb
            overlap = len(inter) / len(union) if union else 0.0
            overlaps[f"{a}_vs_{b}"] = round(overlap, 4)

    return {"strategy_ids": ids, "overlap_ratios": overlaps}


@router.get("/regime-analysis/{strategy_id}")
async def get_regime_analysis(strategy_id: int, db: AsyncSession = Depends(get_db)):
    """Segment walk-forward fold performance by VIX regime: low (<15), mid (15-25), high (>25)."""
    folds_q = await db.execute(
        select(WalkForwardResult).where(WalkForwardResult.strategy_id == strategy_id)
    )
    folds = folds_q.scalars().all()
    if not folds:
        return {"strategy_id": strategy_id, "regimes": {}}

    # Get VIX data keyed by date
    vix_q = await db.execute(
        select(MacroIndicator).where(MacroIndicator.indicator_code == "VIX")
        .order_by(MacroIndicator.date)
    )
    vix_rows = vix_q.scalars().all()
    vix_map = {str(r.date): r.value for r in vix_rows}

    def _avg_vix_for_period(start, end) -> float | None:
        vals = [v for d, v in vix_map.items() if str(start) <= d <= str(end) and v is not None]
        return sum(vals) / len(vals) if vals else None

    regimes: dict[str, list] = {"low_vix": [], "mid_vix": [], "high_vix": [], "unknown": []}

    for fold in folds:
        avg_vix = _avg_vix_for_period(fold.test_start, fold.test_end)
        if avg_vix is None:
            bucket = "unknown"
        elif avg_vix < 15:
            bucket = "low_vix"
        elif avg_vix <= 25:
            bucket = "mid_vix"
        else:
            bucket = "high_vix"

        regimes[bucket].append({
            "fold": fold.fold,
            "test_start": str(fold.test_start),
            "test_end": str(fold.test_end),
            "avg_vix": round(avg_vix, 2) if avg_vix else None,
            **{k: v for k, v in (fold.metrics or {}).items()},
        })

    import numpy as np
    summary = {}
    for regime, items in regimes.items():
        if not items:
            continue
        sharpes = [i.get("sharpe", 0) for i in items if i.get("sharpe") is not None]
        summary[regime] = {
            "n_folds": len(items),
            "avg_sharpe": round(float(np.mean(sharpes)), 4) if sharpes else None,
            "folds": items,
        }

    return {"strategy_id": strategy_id, "regimes": summary}
