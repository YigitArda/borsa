"""Research API endpoints.

Includes:
- Feature importance, walk-forward results, strategy comparison
- Risk warnings, promotions, rolling Sharpe
- Trade overlap, regime analysis
- Calibration, ablation, kill-switch
- Research loop status (/research/status)
"""
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
from app.tasks.celery_app import enqueue_task

router = APIRouter(prefix="/research", tags=["research"])


def _sync_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import settings

    engine = create_engine(settings.sync_database_url)
    Session = sessionmaker(bind=engine)
    return Session()


# ---------------------------------------------------------------------------
# Research Loop Status
# ---------------------------------------------------------------------------

@router.get("/status")
async def get_research_status(db: AsyncSession = Depends(get_db)):
    """Return current research loop status: active iteration, strategies, promotions."""
    # Count strategies by status
    status_counts = {}
    for status in ["research", "promoted", "archived", "candidate"]:
        count = await db.scalar(
            select(func.count()).where(Strategy.status == status)
        )
        status_counts[status] = count or 0

    # Latest strategy
    latest = await db.scalar(
        select(Strategy).order_by(Strategy.created_at.desc()).limit(1)
    )

    # Latest promotion
    latest_promo = await db.scalar(
        select(ModelPromotion).order_by(ModelPromotion.promoted_at.desc()).limit(1)
    )

    # Active kill switch
    active_ks = await db.scalar(
        select(func.count()).where(KillSwitchEvent.status == "active")
    )

    return {
        "strategies": status_counts,
        "latest_strategy": {
            "id": latest.id,
            "name": latest.name,
            "status": latest.status,
            "created_at": str(latest.created_at),
        } if latest else None,
        "latest_promotion": {
            "strategy_id": latest_promo.strategy_id,
            "promoted_at": str(latest_promo.promoted_at),
            "avg_sharpe": latest_promo.avg_sharpe,
        } if latest_promo else None,
        "kill_switch_active": (active_ks or 0) > 0,
    }


# ---------------------------------------------------------------------------
# Feature Importance
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Walk-Forward Results
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Strategy Comparison
# ---------------------------------------------------------------------------

@router.get("/compare")
async def compare_strategies(strategy_ids: str, db: AsyncSession = Depends(get_db)):
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


# ---------------------------------------------------------------------------
# Risk Warnings
# ---------------------------------------------------------------------------

@router.get("/risk-warnings")
async def get_risk_warnings(db: AsyncSession = Depends(get_db)):
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

        # 1. Sharpe degradation
        recent_folds = all_folds[-3:]
        recent_sharpes = [f.metrics.get("sharpe", 0) for f in recent_folds if f.metrics]
        if recent_sharpes and sum(recent_sharpes) / len(recent_sharpes) < 0.2:
            warnings.append({
                "strategy_id": s.id,
                "name": s.name,
                "warning": "Recent 3-fold avg Sharpe < 0.2",
                "severity": "high",
            })

        # 2. OOS suspiciously close to IS (leakage signal)
        if len(all_folds) >= 3:
            early_sharpes = [f.metrics.get("sharpe", 0) for f in all_folds[:3] if f.metrics]
            late_sharpes = [f.metrics.get("sharpe", 0) for f in all_folds[-3:] if f.metrics]
            if early_sharpes and late_sharpes:
                if np.mean(late_sharpes) >= np.mean(early_sharpes) * 1.1:
                    warnings.append({
                        "strategy_id": s.id,
                        "name": s.name,
                        "warning": f"OOS Sharpe >= IS Sharpe x1.1 — possible leakage",
                        "severity": "medium",
                    })

    # 3. Feature drift
    from datetime import date
    from dateutil.relativedelta import relativedelta
    now = date.today()
    cutoff_recent = now - relativedelta(months=6)
    cutoff_old = now - relativedelta(months=12)

    drift_features = ["rsi_14", "volume_zscore", "return_1w", "VIX", "macd"]
    drift_issues = []
    for fname in drift_features:
        recent_q = await db.execute(
            select(func.avg(FeatureWeekly.value))
            .where(FeatureWeekly.feature_name == fname, FeatureWeekly.week_ending >= cutoff_recent)
        )
        old_q = await db.execute(
            select(func.avg(FeatureWeekly.value))
            .where(FeatureWeekly.feature_name == fname, FeatureWeekly.week_ending >= cutoff_old, FeatureWeekly.week_ending < cutoff_recent)
        )
        recent_avg = recent_q.scalar()
        old_avg = old_q.scalar()
        if recent_avg and old_avg and old_avg != 0:
            pct_change = abs(recent_avg - old_avg) / abs(old_avg)
            if pct_change > 0.3:
                drift_issues.append(f"{fname} shifted {pct_change*100:.0f}%")

    if drift_issues:
        warnings.append({
            "strategy_id": None,
            "name": "Feature Distribution Drift",
            "warning": f"Feature means shifted >30%: {', '.join(drift_issues)}",
            "severity": "medium",
        })

    # 4. Stale data
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
            "warning": f"{len(stale_tickers)} stocks stale: {', '.join(stale_tickers[:5])}{'...' if len(stale_tickers) > 5 else ''}",
            "severity": "high",
        })

    return {"warnings": warnings, "count": len(warnings)}


# ---------------------------------------------------------------------------
# Sector Models
# ---------------------------------------------------------------------------

@router.post("/sector-models")
def run_sector_models(tickers: list[str] | None = None):
    from app.services.model_training import ModelTrainer
    from app.services.research_loop import BASE_STRATEGY
    from app.config import settings
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(settings.sync_database_url)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        trainer = ModelTrainer(session, BASE_STRATEGY)
        results = trainer.train_per_sector(tickers or settings.mvp_tickers)
        return {"status": "ok", "sectors": results}


# ---------------------------------------------------------------------------
# Promotions
# ---------------------------------------------------------------------------

@router.get("/promotions")
async def get_promotions(limit: int = 50, db: AsyncSession = Depends(get_db)):
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


# ---------------------------------------------------------------------------
# Rolling Sharpe
# ---------------------------------------------------------------------------

@router.get("/rolling-sharpe/{strategy_id}")
async def get_rolling_sharpe(strategy_id: int, window: int = 4, db: AsyncSession = Depends(get_db)):
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


# ---------------------------------------------------------------------------
# Trade Overlap
# ---------------------------------------------------------------------------

@router.get("/trade-overlap")
async def get_trade_overlap(strategy_ids: str, db: AsyncSession = Depends(get_db)):
    ids = [int(i) for i in strategy_ids.split(",") if i.strip().isdigit()]
    if len(ids) < 2:
        return {"error": "provide at least 2 strategy_ids"}

    trade_sets = {}
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


# ---------------------------------------------------------------------------
# Regime Analysis
# ---------------------------------------------------------------------------

@router.get("/regime-analysis/{strategy_id}")
async def get_regime_analysis(strategy_id: int, db: AsyncSession = Depends(get_db)):
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

    def _avg_vix_for_period(start, end):
        vals = [v for d, v in vix_map.items() if str(start) <= d <= str(end) and v is not None]
        return sum(vals) / len(vals) if vals else None

    regimes = {"low_vix": [], "mid_vix": [], "high_vix": [], "unknown": []}

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


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

@router.get("/calibration/{strategy_id}")
async def get_calibration(strategy_id: int, db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(ProbabilityCalibration)
        .where(ProbabilityCalibration.strategy_id == strategy_id)
        .order_by(ProbabilityCalibration.week_starting.desc())
        .limit(1)
    )
    cal = rows.scalar_one_or_none()
    if not cal:
        return {"strategy_id": strategy_id, "calibration": None}
    return {
        "strategy_id": strategy_id,
        "week_starting": str(cal.week_starting) if cal.week_starting else None,
        "brier_score": cal.brier_score,
        "calibration_error": cal.calibration_error,
        "prob_buckets": cal.prob_buckets,
        "reliability_data": cal.reliability_data,
    }


@router.post("/calibration/{strategy_id}/compute")
def compute_calibration(strategy_id: int):
    from app.services.calibration import CalibrationAnalyzer
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import settings

    engine = create_engine(settings.sync_database_url)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        analyzer = CalibrationAnalyzer(session)
        analysis = analyzer.analyze_strategy(strategy_id)
        if analysis:
            analyzer.save_analysis(analysis)
        return {"status": "ok", "analysis": analysis}


# ---------------------------------------------------------------------------
# Ablation
# ---------------------------------------------------------------------------

@router.post("/ablation/{strategy_id}")
def run_ablation(strategy_id: int):
    from app.services.ablation import AblationTester
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import settings

    engine = create_engine(settings.sync_database_url)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        tester = AblationTester(session)
        results = tester.run_ablation_test(strategy_id)
        return {"status": "ok", "results": [r.__dict__ if hasattr(r, "__dict__") else r for r in results]}


@router.get("/ablation/{strategy_id}/results")
async def get_ablation_results(strategy_id: int, db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(AblationResult)
        .where(AblationResult.strategy_id == strategy_id)
        .order_by(AblationResult.created_at.desc())
    )
    results = rows.scalars().all()
    return [
        {
            "feature_group": r.feature_group,
            "sharpe": r.sharpe,
            "sharpe_impact": r.sharpe_impact,
            "profit_factor": r.profit_factor,
            "drawdown_impact": r.drawdown_impact,
            "stability_score": r.stability_score,
        }
        for r in results
    ]


@router.get("/ablation/{strategy_id}/recommendations")
def get_ablation_recommendations(strategy_id: int):
    from app.services.ablation import AblationTester
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import settings

    engine = create_engine(settings.sync_database_url)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        tester = AblationTester(session)
        rows = session.execute(
            select(AblationResult).where(AblationResult.strategy_id == strategy_id)
        ).scalars().all()
        recs = tester.recommend_feature_groups(results)
        return {"strategy_id": strategy_id, "recommendations": recs}


# ---------------------------------------------------------------------------
# ArXiv Papers
# ---------------------------------------------------------------------------

@router.get("/papers")
def list_arxiv_papers(limit: int = 30, unread_only: bool = False):
    from app.services.arxiv_scanner import ArxivScanner

    session = _sync_session()
    try:
        return ArxivScanner(session).get_recent(limit=limit, unread_only=unread_only)
    finally:
        session.close()


@router.get("/insights")
def list_arxiv_insights(status: str | None = None, limit: int = 50):
    from app.services.arxiv_scanner import FeatureExtractor

    session = _sync_session()
    try:
        return FeatureExtractor(session).get_insights(status=status, limit=limit)
    finally:
        session.close()


@router.post("/papers/scan")
def scan_arxiv_papers(days: int = 7, max_results: int = 50):
    from app.tasks.pipeline_tasks import scan_arxiv_papers as scan_task

    task = enqueue_task(scan_task, days=days, max_results=max_results)
    return {"task_id": task.id, "status": "queued"}


@router.post("/papers/extract")
def extract_arxiv_papers(limit: int = 10):
    from app.tasks.pipeline_tasks import extract_arxiv_features as extract_task

    task = enqueue_task(extract_task, limit=limit)
    return {"task_id": task.id, "status": "queued"}


@router.post("/papers/{paper_id}/read")
def mark_arxiv_paper_read(paper_id: int):
    from app.services.arxiv_scanner import ArxivScanner

    session = _sync_session()
    try:
        scanner = ArxivScanner(session)
        if not scanner.mark_read(paper_id):
            raise HTTPException(status_code=404, detail="Paper not found")
        return {"status": "ok", "paper_id": paper_id}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Kill Switch
# ---------------------------------------------------------------------------

@router.get("/kill-switch/status")
async def get_kill_switch_status(db: AsyncSession = Depends(get_db)):
    from app.services.kill_switch import KillSwitchMonitor
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import settings

    engine = create_engine(settings.sync_database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        monitor = KillSwitchMonitor(session)
        active = monitor.is_kill_switch_active()
        warnings = monitor.get_active_warnings()
        return {"active": active, "warnings": warnings}
    finally:
        session.close()


@router.post("/kill-switch/resolve")
async def resolve_kill_switch(event_id: int, resolved_by: str = "admin", db: AsyncSession = Depends(get_db)):
    from app.services.kill_switch import KillSwitchMonitor
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import settings

    engine = create_engine(settings.sync_database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        monitor = KillSwitchMonitor(session)
        monitor.resolve_kill_switch(event_id, resolved_by)
        return {"status": "resolved", "event_id": event_id}
    finally:
        session.close()


@router.get("/kill-switch/history")
async def get_kill_switch_history(limit: int = 50, db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(KillSwitchEvent).order_by(KillSwitchEvent.triggered_at.desc()).limit(limit)
    )
    events = rows.scalars().all()
    return [
        {
            "id": e.id,
            "trigger_type": e.trigger_type,
            "severity": e.severity,
            "reason": e.reason,
            "status": e.status,
            "triggered_at": str(e.triggered_at),
            "resolved_at": str(e.resolved_at) if e.resolved_at else None,
        }
        for e in events
    ]


# ---------------------------------------------------------------------------
# Regime Endpoints
# ---------------------------------------------------------------------------

@router.get("/regime/current")
async def get_current_regime(db: AsyncSession = Depends(get_db)):
    row = await db.execute(
        select(MarketRegime).order_by(MarketRegime.week_starting.desc()).limit(1)
    )
    regime = row.scalar_one_or_none()
    if not regime:
        return {"regime": None}
    return {
        "week_starting": str(regime.week_starting),
        "week_ending": str(regime.week_ending),
        "regime_type": regime.regime_type,
        "confidence": regime.confidence,
        "spy_200ma_ratio": regime.spy_200ma_ratio,
        "vix_level": regime.vix_level,
    }


@router.get("/regime/history")
async def get_regime_history(start: str | None = None, end: str | None = None, db: AsyncSession = Depends(get_db)):
    query = select(MarketRegime).order_by(MarketRegime.week_starting)
    if start:
        query = query.where(MarketRegime.week_starting >= start)
    if end:
        query = query.where(MarketRegime.week_ending <= end)
    rows = await db.execute(query)
    regimes = rows.scalars().all()
    return [
        {
            "week_starting": str(r.week_starting),
            "week_ending": str(r.week_ending),
            "regime_type": r.regime_type,
            "confidence": r.confidence,
        }
        for r in regimes
    ]


@router.post("/regime/detect")
async def detect_regime(week_ending: str | None = None, db: AsyncSession = Depends(get_db)):
    from app.services.regime_detection import RegimeDetector
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import settings
    from datetime import date

    engine = create_engine(settings.sync_database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        detector = RegimeDetector(session)
        week = date.fromisoformat(week_ending) if week_ending else None
        regime = detector.detect_regime_for_week(week)
        return {"status": "ok", "regime": regime}
    finally:
        session.close()


@router.post("/calibration/run-all")
async def run_calibration_all():
    """Trigger calibration computation for all promoted strategies."""
    from app.tasks.pipeline_tasks import run_calibration
    from app.tasks.celery_app import enqueue_task
    task = enqueue_task(run_calibration)
    return {"status": "queued", "task_id": task.id}


@router.post("/alpha-decay/check-all")
async def run_alpha_decay_check():
    """Trigger alpha decay check for all promoted strategies."""
    from app.tasks.pipeline_tasks import check_alpha_decay
    from app.tasks.celery_app import enqueue_task
    task = enqueue_task(check_alpha_decay)
    return {"status": "queued", "task_id": task.id}
