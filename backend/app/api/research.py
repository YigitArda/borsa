from fastapi import APIRouter, Depends, HTTPException
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
from app.models.regime import MarketRegime
from app.models.calibration import ProbabilityCalibration
from app.models.ablation import AblationResult
from app.models.kill_switch import KillSwitchEvent

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
    """Segment walk-forward fold performance by market regime (enhanced with new regime types)."""
    from app.services.regime_detection import RegimeDetector

    # Try new regime-based analysis first
    sync_engine = db.sync_engine if hasattr(db, "sync_engine") else db.bind
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=sync_engine)
    sync_session = SessionLocal()
    try:
        detector = RegimeDetector(sync_session)
        result = detector.analyze_strategy_by_regime(strategy_id)
        if result.get("regimes"):
            return result
    finally:
        sync_session.close()

    # Fallback to legacy VIX-only buckets if no regime data yet
    folds_q = await db.execute(
        select(WalkForwardResult).where(WalkForwardResult.strategy_id == strategy_id)
    )
    folds = folds_q.scalars().all()
    if not folds:
        return {"strategy_id": strategy_id, "regimes": {}}

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


@router.get("/regime/current")
async def get_current_regime(db: AsyncSession = Depends(get_db)):
    """Return the most recent detected market regime."""
    row = await db.execute(
        select(MarketRegime)
        .order_by(MarketRegime.week_ending.desc())
        .limit(1)
    )
    regime = row.scalar_one_or_none()
    if not regime:
        return {"regime": None}
    return {
        "regime": {
            "id": regime.id,
            "week_starting": str(regime.week_starting),
            "week_ending": str(regime.week_ending),
            "regime_type": regime.regime_type,
            "spy_200ma_ratio": regime.spy_200ma_ratio,
            "vix_level": regime.vix_level,
            "vix_change": regime.vix_change,
            "nasdaq_spy_ratio": regime.nasdaq_spy_ratio,
            "market_breadth": regime.market_breadth,
            "yield_trend": regime.yield_trend,
            "sector_rotation_score": regime.sector_rotation_score,
            "confidence": regime.confidence,
            "created_at": str(regime.created_at),
        }
    }


@router.get("/regime/history")
async def get_regime_history(
    start: str | None = None,
    end: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get regime history for a date range. Pass dates as ISO strings (YYYY-MM-DD)."""
    from datetime import date as dt_date

    query = select(MarketRegime).order_by(MarketRegime.week_ending)
    if start:
        try:
            s = dt_date.fromisoformat(start)
            query = query.where(MarketRegime.week_ending >= s)
        except ValueError:
            pass
    if end:
        try:
            e = dt_date.fromisoformat(end)
            query = query.where(MarketRegime.week_ending <= e)
        except ValueError:
            pass

    rows = await db.execute(query)
    regimes = rows.scalars().all()
    return {
        "count": len(regimes),
        "regimes": [
            {
                "id": r.id,
                "week_starting": str(r.week_starting),
                "week_ending": str(r.week_ending),
                "regime_type": r.regime_type,
                "spy_200ma_ratio": r.spy_200ma_ratio,
                "vix_level": r.vix_level,
                "vix_change": r.vix_change,
                "nasdaq_spy_ratio": r.nasdaq_spy_ratio,
                "market_breadth": r.market_breadth,
                "yield_trend": r.yield_trend,
                "sector_rotation_score": r.sector_rotation_score,
                "confidence": r.confidence,
                "created_at": str(r.created_at),
            }
            for r in regimes
        ],
    }


@router.post("/regime/detect")
async def trigger_regime_detection(week_ending: str, db: AsyncSession = Depends(get_db)):
    """Trigger regime detection for a specific week ending date (YYYY-MM-DD)."""
    from datetime import date as dt_date
    from app.services.regime_detection import RegimeDetector

    try:
        we = dt_date.fromisoformat(week_ending)
    except ValueError:
        return {"error": "Invalid week_ending format. Use YYYY-MM-DD."}

    sync_engine = db.sync_engine if hasattr(db, "sync_engine") else db.bind
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=sync_engine)
    sync_session = SessionLocal()
    try:
        detector = RegimeDetector(sync_session)
        regime = detector.detect_regime_for_week(we)
        if not regime:
            return {"status": "failed", "reason": "insufficient_data"}
        return {
            "status": "ok",
            "regime_id": regime.id,
            "week_ending": str(regime.week_ending),
            "regime_type": regime.regime_type,
            "confidence": regime.confidence,
        }
    finally:
        sync_session.close()


@router.post("/ablation/{strategy_id}")
async def run_ablation(strategy_id: int, db: AsyncSession = Depends(get_db)):
    """Run ablation tests for a strategy (isolates each feature group)."""
    from app.services.ablation import AblationTester
    from sqlalchemy.orm import Session
    from sqlalchemy import create_engine
    from app.config import settings

    sync_engine = db.sync_engine if hasattr(db, "sync_engine") else db.bind
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=sync_engine)
    sync_session = SessionLocal()
    try:
        tester = AblationTester(sync_session)
        results = tester.run_ablation_test(strategy_id)
        return {"strategy_id": strategy_id, "status": "ok", "results": results}
    finally:
        sync_session.close()


@router.get("/ablation/{strategy_id}/results")
async def get_ablation_results(strategy_id: int, db: AsyncSession = Depends(get_db)):
    """Get persisted ablation results for a strategy."""
    rows = await db.execute(
        select(AblationResult)
        .where(AblationResult.strategy_id == strategy_id)
        .order_by(AblationResult.created_at.desc())
    )
    records = rows.scalars().all()
    return [
        {
            "id": r.id,
            "feature_group": r.feature_group,
            "features_removed": r.features_removed,
            "sharpe": r.sharpe,
            "profit_factor": r.profit_factor,
            "max_drawdown": r.max_drawdown,
            "win_rate": r.win_rate,
            "avg_return": r.avg_return,
            "sharpe_impact": r.sharpe_impact,
            "profit_factor_impact": r.profit_factor_impact,
            "drawdown_impact": r.drawdown_impact,
            "stability_score": r.stability_score,
            "created_at": str(r.created_at) if r.created_at else None,
        }
        for r in records
    ]


@router.get("/ablation/{strategy_id}/recommendations")
async def get_ablation_recommendations(strategy_id: int, db: AsyncSession = Depends(get_db)):
    """Get feature-group keep/remove recommendations based on ablation results."""
    from app.services.ablation import AblationTester

    rows = await db.execute(
        select(AblationResult)
        .where(AblationResult.strategy_id == strategy_id)
    )
    records = rows.scalars().all()
    if not records:
        return {"strategy_id": strategy_id, "recommendations": []}

    result_dicts = [
        {
            "feature_group": r.feature_group,
            "sharpe_impact": r.sharpe_impact,
            "profit_factor_impact": r.profit_factor_impact,
            "drawdown_impact": r.drawdown_impact,
            "stability_score": r.stability_score,
        }
        for r in records
    ]
    recommendations = AblationTester.recommend_feature_groups(result_dicts)
    return {"strategy_id": strategy_id, "recommendations": recommendations}


@router.get("/kill-switch/status")
async def get_kill_switch_status(db: AsyncSession = Depends(get_db)):
    """Return current kill switch state and active warnings."""
    from app.services.kill_switch import KillSwitchMonitor
    from sqlalchemy.orm import Session
    from sqlalchemy import create_engine
    from app.config import settings

    sync_engine = create_engine(settings.sync_database_url)
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=sync_engine)
    sync_session = SessionLocal()
    try:
        monitor = KillSwitchMonitor(sync_session)
        active = monitor.get_active_warnings()
        return {
            "active": len(active) > 0,
            "count": len(active),
            "warnings": [
                {
                    "id": e.id,
                    "trigger_type": e.trigger_type,
                    "strategy_id": e.strategy_id,
                    "severity": e.severity,
                    "reason": e.reason,
                    "details": e.details,
                    "triggered_at": str(e.triggered_at),
                }
                for e in active
            ],
        }
    finally:
        sync_session.close()


@router.post("/kill-switch/resolve")
async def resolve_kill_switch(event_id: int, resolved_by: str, db: AsyncSession = Depends(get_db)):
    """Resolve an active kill switch event (admin only)."""
    from app.services.kill_switch import KillSwitchMonitor
    from sqlalchemy.orm import Session
    from sqlalchemy import create_engine
    from app.config import settings

    sync_engine = create_engine(settings.sync_database_url)
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=sync_engine)
    sync_session = SessionLocal()
    try:
        monitor = KillSwitchMonitor(sync_session)
        event = monitor.resolve_kill_switch(event_id, resolved_by)
        if not event:
            raise HTTPException(status_code=404, detail="Kill switch event not found")
        return {
            "id": event.id,
            "status": event.status,
            "resolved_at": str(event.resolved_at),
            "resolved_by": event.resolved_by,
        }
    finally:
        sync_session.close()


@router.get("/kill-switch/history")
async def get_kill_switch_history(
    limit: int = 50,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get kill switch event history with optional status filter."""
    query = select(KillSwitchEvent).order_by(KillSwitchEvent.created_at.desc())
    if status:
        query = query.where(KillSwitchEvent.status == status)
    rows = await db.execute(query.limit(limit))
    events = rows.scalars().all()
    return {
        "count": len(events),
        "events": [
            {
                "id": e.id,
                "trigger_type": e.trigger_type,
                "strategy_id": e.strategy_id,
                "severity": e.severity,
                "reason": e.reason,
                "details": e.details,
                "triggered_at": str(e.triggered_at),
                "resolved_at": str(e.resolved_at) if e.resolved_at else None,
                "resolved_by": e.resolved_by,
                "status": e.status,
            }
            for e in events
        ],
    }


@router.get("/calibration/{strategy_id}")
async def get_calibration(strategy_id: int, db: AsyncSession = Depends(get_db)):
    """Return the latest calibration data for a strategy."""
    row = await db.execute(
        select(ProbabilityCalibration)
        .where(ProbabilityCalibration.strategy_id == strategy_id)
        .order_by(ProbabilityCalibration.week_starting.desc())
        .limit(1)
    )
    cal = row.scalar_one_or_none()
    if not cal:
        return {"strategy_id": strategy_id, "calibration": None}
    return {
        "strategy_id": strategy_id,
        "calibration": {
            "week_starting": str(cal.week_starting),
            "brier_score": cal.brier_score,
            "calibration_error": cal.calibration_error,
            "prob_buckets": cal.prob_buckets,
            "reliability_data": cal.reliability_data,
            "created_at": str(cal.created_at),
        },
    }


@router.post("/calibration/{strategy_id}/compute")
async def compute_calibration(strategy_id: int, db: AsyncSession = Depends(get_db)):
    """Trigger calibration computation for a strategy and persist the result."""
    from app.services.calibration import CalibrationAnalyzer
    from sqlalchemy.orm import Session

    # CalibrationAnalyzer expects a sync session; create one from the async engine
    sync_engine = db.sync_engine if hasattr(db, "sync_engine") else db.bind
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=sync_engine)
    sync_session = SessionLocal()
    try:
        analyzer = CalibrationAnalyzer(sync_session)
        analysis = analyzer.analyze_strategy(strategy_id)
        if analysis is None:
            return {"strategy_id": strategy_id, "status": "insufficient_data"}
        cal = analyzer.save_analysis(analysis)
        return {
            "strategy_id": strategy_id,
            "status": "ok",
            "calibration_id": cal.id,
            "week_starting": str(cal.week_starting),
            "brier_score": cal.brier_score,
            "calibration_error": cal.calibration_error,
            "sample_count": analysis.get("sample_count"),
        }
    finally:
        sync_session.close()


def _make_sync_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import settings

    engine = create_engine(settings.sync_database_url)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


@router.get("/mutation-memory")
async def get_mutation_memory():
    """Return learned mutation and feature scores for the directed search layer."""
    from app.services.mutation_memory import MutationScoreTracker

    session = _make_sync_session()
    try:
        return MutationScoreTracker(session).summary()
    finally:
        session.close()


@router.get("/optuna-status")
async def get_optuna_status(study_name: str = "borsa_strategy"):
    """Return Bayesian optimization study status."""
    from app.config import settings
    from app.services.hyperparam_optimizer import HyperparamOptimizer

    session = _make_sync_session()
    try:
        optimizer = HyperparamOptimizer(session, settings.mvp_tickers, study_name=study_name)
        return optimizer.status()
    finally:
        session.close()


@router.post("/optimize")
async def start_hyperparam_optimization(n_trials: int | None = None):
    """Queue Bayesian hyperparameter optimization as a Celery task."""
    from app.tasks.celery_app import enqueue_task
    from app.tasks.pipeline_tasks import optimize_hyperparams

    task = enqueue_task(optimize_hyperparams, n_trials=n_trials)
    return {"status": "queued", "task_id": task.id, "n_trials": n_trials}


@router.get("/bandit/arms")
async def get_bandit_arms():
    """Return Thompson-sampling state for promoted strategy selection."""
    from app.services.strategy_bandit import StrategyBandit

    session = _make_sync_session()
    try:
        return {"arms": StrategyBandit(session).arm_summary()}
    finally:
        session.close()


@router.get("/rl/status")
async def get_rl_status():
    """Return Q-learning agent state size and exploration rate."""
    from app.services.rl_agent import RLStrategyAgent

    session = _make_sync_session()
    try:
        return RLStrategyAgent(session).status()
    finally:
        session.close()


@router.get("/rl/actions/{strategy_id}")
async def get_rl_actions(strategy_id: int, db: AsyncSession = Depends(get_db)):
    """Rank mutation actions for the current strategy state."""
    strategy = await db.get(Strategy, strategy_id)
    if not strategy:
        raise HTTPException(404, "Strategy not found")

    rows = await db.execute(
        select(WalkForwardResult)
        .where(WalkForwardResult.strategy_id == strategy_id)
        .order_by(WalkForwardResult.fold)
    )
    recent_metrics = [r.metrics for r in rows.scalars().all() if r.metrics]

    from app.services.rl_agent import RLStrategyAgent
    session = _make_sync_session()
    try:
        agent = RLStrategyAgent(session)
        return {
            "strategy_id": strategy_id,
            "actions": agent.best_actions(strategy.config or {}, recent_metrics),
        }
    finally:
        session.close()


@router.get("/meta-learner/status")
async def get_meta_learner_status():
    """Return training sample count and current coefficient importance."""
    from app.services.meta_learner import MetaPromotionModel

    session = _make_sync_session()
    try:
        model = MetaPromotionModel(session)
        return {
            "n_samples": model.n_samples(),
            "feature_importance": model.feature_importance(),
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# ArXiv paper scanner endpoints
# ---------------------------------------------------------------------------

@router.get("/papers")
async def get_arxiv_papers(limit: int = 30, unread_only: bool = False):
    """Return recent ArXiv quantitative finance papers."""
    from app.services.arxiv_scanner import ArxivScanner
    session = _make_sync_session()
    try:
        scanner = ArxivScanner(session)
        return {"papers": scanner.get_recent(limit=limit, unread_only=unread_only)}
    finally:
        session.close()


@router.post("/papers/{paper_id}/read")
async def mark_paper_read(paper_id: int):
    """Mark a paper as read."""
    from app.services.arxiv_scanner import ArxivScanner
    session = _make_sync_session()
    try:
        ok = ArxivScanner(session).mark_read(paper_id)
        if not ok:
            raise HTTPException(404, "Paper not found")
        return {"status": "ok"}
    finally:
        session.close()


@router.get("/papers/insights")
async def get_research_insights(status: str | None = None, limit: int = 50):
    """Return Claude-extracted feature ideas from papers."""
    from app.services.arxiv_scanner import FeatureExtractor
    session = _make_sync_session()
    try:
        return {"insights": FeatureExtractor(session).get_insights(status=status, limit=limit)}
    finally:
        session.close()


@router.post("/papers/insights/{insight_id}/status")
async def update_insight_status(insight_id: int, status: str):
    """Update insight status: approved / rejected / implemented."""
    if status not in {"approved", "rejected", "implemented", "new"}:
        raise HTTPException(400, "Invalid status")
    from app.services.arxiv_scanner import FeatureExtractor
    session = _make_sync_session()
    try:
        ok = FeatureExtractor(session).update_status(insight_id, status)
        if not ok:
            raise HTTPException(404, "Insight not found")
        return {"status": "ok", "new_status": status}
    finally:
        session.close()


@router.post("/papers/insights/{insight_id}/generate-code")
async def generate_insight_code(insight_id: int):
    """Generate implementation code for an approved insight (human review required)."""
    from app.services.arxiv_scanner import AutoImplementer
    session = _make_sync_session()
    try:
        impl = AutoImplementer(session)
        code = impl.generate_code(insight_id)
        if code is None:
            raise HTTPException(400, "Generation failed (not approved or API key missing)")
        passed, error = impl.sandbox_test(code)
        return {"insight_id": insight_id, "code": code, "sandbox_passed": passed, "sandbox_error": error or None}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Bandit, stacker, mutation memory endpoints
# ---------------------------------------------------------------------------

@router.get("/bandit/status")
async def get_bandit_status():
    """Return Thompson Sampling Beta parameters for all strategy arms."""
    from app.services.strategy_bandit import StrategyBandit
    session = _make_sync_session()
    try:
        return {"arms": StrategyBandit(session).arm_summary()}
    finally:
        session.close()


@router.get("/signal-stacker/weights")
async def get_signal_stacker_weights():
    """Return regime-conditional signal stacker weights."""
    from app.services.signal_stacker import SignalStacker
    session = _make_sync_session()
    try:
        stacker = SignalStacker(session)
        stacker.load_weights()
        return stacker.weights_summary()
    finally:
        session.close()


@router.get("/mutation-memory/summary")
async def get_mutation_memory_summary():
    """Return top/bottom features and mutation type scores."""
    from app.services.mutation_memory import MutationScoreTracker
    session = _make_sync_session()
    try:
        return MutationScoreTracker(session).summary()
    finally:
        session.close()
