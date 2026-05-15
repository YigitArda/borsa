import logging
from datetime import date
from celery import chain
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _check_kill_switch(session) -> bool:
    """Return True if kill switch is active and pipeline should be blocked."""
    from app.services.kill_switch import KillSwitchMonitor
    monitor = KillSwitchMonitor(session)
    if monitor.is_kill_switch_active():
        logger.warning("Kill switch is active; blocking pipeline task")
        return True
    return False


def _get_sync_session():
    engine = create_engine(settings.sync_database_url)
    Session = sessionmaker(bind=engine)
    return Session()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.ingest_prices")
def ingest_prices(self, tickers: list[str] | None = None, start: str = "2010-01-01"):
    from app.services.data_ingestion import DataIngestionService
    session = _get_sync_session()
    try:
        svc = DataIngestionService(session)
        tickers = tickers or settings.mvp_tickers
        svc.run_full_ingest(tickers, start=start)
        return {"status": "ok", "tickers": tickers}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.compute_features")
def compute_features(self, tickers: list[str] | None = None):
    from app.services.feature_engineering import FeatureEngineeringService
    session = _get_sync_session()
    try:
        svc = FeatureEngineeringService(session)
        tickers = tickers or settings.mvp_tickers
        results = svc.run_all(tickers)
        return {"status": "ok", "results": results}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.run_research_loop")
def run_research_loop(
    self,
    n_iterations: int = 5,
    base_strategy_id: int | None = None,
    mode: str = "sequential",
    n_generations: int | None = None,
):
    from app.services.research_loop import ResearchLoop
    session = _get_sync_session()
    try:
        if _check_kill_switch(session):
            return {"status": "blocked", "reason": "kill_switch_active"}
        loop = ResearchLoop(session, settings.mvp_tickers)
        results = loop.run_loop(
            n_iterations=n_iterations,
            base_strategy_id=base_strategy_id,
            mode=mode,
            n_generations=n_generations,
        )
        return {"status": "ok", "results": results}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.evaluate_individual_task")
def evaluate_individual_task(self, config: dict, tickers: list[str] | None = None):
    """Evaluate one strategy config for population/genetic search."""
    from app.services.research_loop import ResearchLoop

    session = _get_sync_session()
    try:
        if _check_kill_switch(session):
            return [], None
        loop = ResearchLoop(session, tickers or settings.mvp_tickers)
        return loop.evaluate_config(config)
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.optimize_hyperparams")
def optimize_hyperparams(
    self,
    base_config: dict | None = None,
    tickers: list[str] | None = None,
    n_trials: int | None = None,
):
    from app.services.hyperparam_optimizer import HyperparamOptimizer
    from app.services.research_loop import BASE_STRATEGY

    session = _get_sync_session()
    try:
        if _check_kill_switch(session):
            return {"status": "blocked", "reason": "kill_switch_active"}
        optimizer = HyperparamOptimizer(session, tickers or settings.mvp_tickers)
        best = optimizer.optimize(base_config or BASE_STRATEGY, n_trials=n_trials or settings.bayesian_opt_trials)
        return {"status": "ok", "best_config": best, "optuna": optimizer.status()}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.ingest_macro")
def ingest_macro(self, start: str = "2010-01-01"):
    from app.services.macro_data import MacroDataService
    session = _get_sync_session()
    try:
        svc = MacroDataService(session)
        n = svc.ingest_macro(start=start)
        return {"status": "ok", "rows": n}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.ingest_news")
def ingest_news(self, tickers: list[str] | None = None):
    from app.services.news_service import NewsService
    session = _get_sync_session()
    try:
        svc = NewsService(session)
        tickers = tickers or settings.mvp_tickers
        results = svc.run_all(tickers)
        return {"status": "ok", "results": results}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.ingest_financials")
def ingest_financials(self, tickers: list[str] | None = None):
    from app.services.financial_data import FinancialDataService
    session = _get_sync_session()
    try:
        svc = FinancialDataService(session)
        tickers = tickers or settings.mvp_tickers
        results = svc.run_all(tickers)
        return {"status": "ok", "results": results}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.ingest_statements")
def ingest_statements(self, tickers: list[str] | None = None):
    from app.services.fundamental_statements import FundamentalStatementsService
    session = _get_sync_session()
    try:
        svc = FundamentalStatementsService(session)
        tickers = tickers or settings.mvp_tickers
        results = svc.run_all(tickers)
        return {"status": "ok", "results": results}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.ingest_social")
def ingest_social(self, tickers: list[str] | None = None):
    from app.services.social_sentiment import SocialSentimentService
    session = _get_sync_session()
    try:
        svc = SocialSentimentService(session)
        tickers = tickers or settings.mvp_tickers
        results = svc.run_all(tickers)
        return {"status": "ok", "results": results}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.generate_weekly_predictions")
def generate_weekly_predictions(
    self,
    tickers: list[str] | None = None,
    week_starting: str | None = None,
    strategy_id: int | None = None,
    open_paper: bool = True,
):
    from app.services.paper_trading import PaperTradingService
    from app.services.weekly_prediction import WeeklyPredictionService

    session = _get_sync_session()
    try:
        if _check_kill_switch(session):
            return {"status": "blocked", "reason": "kill_switch_active"}
        week_date = date.fromisoformat(week_starting) if week_starting else None
        tickers = tickers or settings.mvp_tickers
        prediction_svc = WeeklyPredictionService(session)
        predictions = prediction_svc.generate(
            tickers=tickers,
            week_starting=week_date,
            strategy_id=strategy_id,
        )

        paper_trades = 0
        if predictions and open_paper:
            paper_svc = PaperTradingService(session)
            paper_trades = paper_svc.open_from_predictions(
                week_starting=week_date,
                strategy_id=strategy_id,
            )

        return {"status": "ok", "predictions": predictions, "paper_trades": paper_trades}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.open_paper_trades")
def open_paper_trades(
    self,
    week_starting: str | None = None,
    strategy_id: int | None = None,
    top_n: int | None = None,
):
    from app.services.paper_trading import PaperTradingService

    session = _get_sync_session()
    try:
        if _check_kill_switch(session):
            return {"status": "blocked", "reason": "kill_switch_active"}
        week_date = date.fromisoformat(week_starting) if week_starting else None
        svc = PaperTradingService(session)
        count = svc.open_from_predictions(week_starting=week_date, strategy_id=strategy_id, top_n=top_n)
        return {"status": "ok", "paper_trades": count}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.evaluate_paper_trades")
def evaluate_paper_trades(self, as_of: str | None = None):
    from app.services.paper_trading import PaperTradingService

    session = _get_sync_session()
    try:
        as_of_date = date.fromisoformat(as_of) if as_of else None
        svc = PaperTradingService(session)
        return {"status": "ok", **svc.evaluate_open_positions(as_of=as_of_date)}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.import_pit_financials")
def import_pit_financials(self, path: str, data_source: str = "pit_csv"):
    from app.services.financial_data import FinancialDataService

    session = _get_sync_session()
    try:
        count = FinancialDataService(session).ingest_pit_csv(path, data_source=data_source)
        return {"status": "ok", "rows": count}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.import_universe_snapshots")
def import_universe_snapshots(self, path: str, index_name: str = "SP500"):
    from app.services.data_ingestion import DataIngestionService

    session = _get_sync_session()
    try:
        count = DataIngestionService(session).import_universe_snapshots_csv(path, index_name=index_name)
        return {"status": "ok", "rows": count}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.import_ticker_aliases")
def import_ticker_aliases(self, path: str):
    from app.services.data_ingestion import DataIngestionService

    session = _get_sync_session()
    try:
        count = DataIngestionService(session).import_ticker_aliases_csv(path)
        return {"status": "ok", "rows": count}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.import_corporate_actions")
def import_corporate_actions(self, path: str, data_source: str = "csv"):
    from app.services.data_ingestion import DataIngestionService

    session = _get_sync_session()
    try:
        count = DataIngestionService(session).import_corporate_actions_csv(path, data_source=data_source)
        return {"status": "ok", "rows": count}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.detect_regimes")
def detect_regimes(self, start: str | None = None, end: str | None = None):
    """
    Detect and persist market regimes for all weeks in [start, end].
    Defaults to last 2 years if start is omitted.
    Must run after macro data is ingested (VIX, TNX, SPY prices).
    """
    from app.services.regime_detection import RegimeDetector
    import pandas as pd

    session = _get_sync_session()
    try:
        from datetime import timedelta
        end_date = date.fromisoformat(end) if end else date.today()
        start_date = date.fromisoformat(start) if start else end_date - timedelta(weeks=104)

        detector = RegimeDetector(session)
        detected = 0
        skipped = 0

        # Generate Friday dates for the range
        all_fridays = pd.date_range(start=start_date, end=end_date, freq="W-FRI")
        for friday in all_fridays:
            week_date = friday.date()
            try:
                mr = detector.detect_regime_for_week(week_date)
                if mr:
                    detected += 1
            except Exception as exc:
                logger.warning("Regime detection failed for %s: %s", week_date, exc)
                skipped += 1

        logger.info("detect_regimes: detected=%d skipped=%d", detected, skipped)
        return {"status": "ok", "detected": detected, "skipped": skipped}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.run_regime_aware_backtest")
def run_regime_aware_backtest(
    self,
    strategy_id: int,
    tickers: list[str] | None = None,
    kelly_fraction: float = 0.0,
    n_iterations: int = 1,
):
    """
    Re-run walk-forward backtest for a strategy with Kelly sizing and regime filter active.
    Results are saved to walk_forward_results (overwrite by strategy_id + fold).

    This task is separate from the main research loop so it can be triggered
    independently after regime data is updated.

    Args:
        strategy_id:   Strategy to backtest.
        tickers:       Override ticker list (defaults to mvp_tickers).
        kelly_fraction: Pre-set Kelly fraction (0 = auto-compute from prior folds).
        n_iterations:  Number of research loop iterations to run (useful for re-tuning).
    """
    from app.services.model_training import ModelTrainer
    from app.services.regime_filter import RegimeFilter
    from app.models.strategy import Strategy
    from app.models.backtest import WalkForwardResult

    session = _get_sync_session()
    try:
        if _check_kill_switch(session):
            return {"status": "blocked", "reason": "kill_switch_active"}

        strategy = session.get(Strategy, strategy_id)
        if not strategy:
            return {"status": "error", "reason": f"strategy {strategy_id} not found"}

        tickers = tickers or settings.mvp_tickers
        trainer = ModelTrainer(session, strategy.config)
        folds = trainer.walk_forward(tickers, min_train_years=5)

        if not folds:
            return {"status": "error", "reason": "no walk-forward folds produced"}

        # Compute Kelly from all folds (for logging; actual per-fold Kelly uses prior folds)
        from app.services.position_sizing import kelly_from_folds
        kelly_est = kelly_from_folds(folds)

        fold_summaries = []
        for fold in folds:
            wfr = session.execute(
                __import__("sqlalchemy", fromlist=["select"]).select(WalkForwardResult).where(
                    WalkForwardResult.strategy_id == strategy_id,
                    WalkForwardResult.fold == fold.fold,
                )
            ).scalar_one_or_none()

            if wfr:
                wfr.metrics = fold.metrics
                wfr.equity_curve = fold.equity_curve or []
            else:
                wfr = WalkForwardResult(
                    strategy_id=strategy_id,
                    fold=fold.fold,
                    train_start=fold.train_start,
                    train_end=fold.train_end,
                    test_start=fold.test_start,
                    test_end=fold.test_end,
                    metrics=fold.metrics,
                    equity_curve=fold.equity_curve or [],
                )
                session.add(wfr)

            fold_summaries.append({
                "fold": fold.fold,
                "sharpe": fold.metrics.get("sharpe"),
                "kelly_fraction": fold.metrics.get("kelly_fraction"),
                "regime_weeks_skipped": fold.metrics.get("regime_weeks_skipped"),
            })

        session.commit()

        return {
            "status": "ok",
            "strategy_id": strategy_id,
            "n_folds": len(folds),
            "kelly_auto": round(kelly_est.fractional_kelly, 4),
            "kelly_win_rate": round(kelly_est.win_rate, 4),
            "folds": fold_summaries,
        }
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.scan_arxiv_papers")
def scan_arxiv_papers(self, days: int = 7, max_results: int = 50):
    """Fetch recent quantitative finance papers from ArXiv."""
    from app.services.arxiv_scanner import ArxivScanner
    session = _get_sync_session()
    try:
        scanner = ArxivScanner(session)
        n_new = scanner.fetch_recent(days=days, max_results=max_results)
        return {"status": "ok", "new_papers": n_new}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.extract_arxiv_features")
def extract_arxiv_features(self, limit: int = 10):
    """Send unprocessed paper abstracts to Claude API for feature extraction."""
    from app.services.arxiv_scanner import FeatureExtractor
    session = _get_sync_session()
    try:
        extractor = FeatureExtractor(session)
        n = extractor.extract_from_unprocessed(limit=limit)
        return {"status": "ok", "insights_created": n}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.ingest_pead")
def ingest_pead(self, tickers: list[str] | None = None):
    """Ingest PEAD earnings data from yfinance for all tickers."""
    from app.services.pead_factor import PEADFactor
    session = _get_sync_session()
    try:
        tickers = tickers or settings.mvp_tickers
        svc = PEADFactor(session)
        results = svc.run_all(tickers)
        total = sum(results.values())
        logger.info(f"PEAD ingested {total} records for {len(tickers)} tickers")
        return {"status": "ok", "total_records": total, "tickers": len(tickers)}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.ingest_short_interest")
def ingest_short_interest(self, tickers: list[str] | None = None, use_finra: bool = True):
    """Ingest short interest data from yfinance (+ optionally FINRA) for all tickers."""
    from app.services.short_interest_factor import ShortInterestService
    from datetime import date, timedelta
    session = _get_sync_session()
    try:
        tickers = tickers or settings.mvp_tickers
        svc = ShortInterestService(session)
        results = svc.run_all(tickers)
        total = sum(results.values())
        if use_finra:
            # Try yesterday's FINRA data
            finra_count = svc.ingest_from_finra(date.today() - timedelta(days=1))
            logger.info(f"FINRA SHO: {finra_count} records")
        logger.info(f"Short interest ingested for {len(tickers)} tickers")
        return {"status": "ok", "yfinance_records": total, "tickers": len(tickers)}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.update_pead_confirmations")
def update_pead_confirmations(self, tickers: list[str] | None = None):
    """Update PEAD price confirmations — loads price data from DB, no df needed."""
    from app.services.pead_factor import PEADFactor
    session = _get_sync_session()
    try:
        svc = PEADFactor(session)
        tickers = tickers or settings.mvp_tickers
        results = {}
        for ticker in tickers:
            try:
                n = svc.update_price_confirmations(ticker)
                results[ticker] = n
            except Exception as e:
                logger.error("PEAD confirmation failed %s: %s", ticker, e)
                results[ticker] = 0
        logger.info("PEAD confirmations updated: %s", results)
        return {"status": "ok", "results": results}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.compute_data_quality_scores")
def compute_data_quality_scores(self, week_str: str | None = None):
    """Compute data quality scores for all active stocks and log poor-quality ones."""
    from app.services.data_quality_scoring import DataQualityScorerSync
    from datetime import timedelta
    session = _get_sync_session()
    try:
        if week_str:
            week = date.fromisoformat(week_str)
        else:
            today = date.today()
            days_since_friday = (today.weekday() - 4) % 7
            week = today - timedelta(days=days_since_friday)

        scorer = DataQualityScorerSync(session)
        result = scorer.score_all_stocks_sync(week)
        if result["poor_quality_tickers"]:
            logger.warning(
                "Kalite uyarısı: %d hisse düşük veri kalitesi: %s",
                len(result["poor_quality_tickers"]),
                result["poor_quality_tickers"][:10],
            )
        return {"status": "ok", **result}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.run_portfolio_simulation_auto")
def run_portfolio_simulation_auto(
    self,
    tickers: list[str] | None = None,
    strategy_id: int | None = None,
):
    """Run portfolio simulation for the most recently promoted strategy."""
    from sqlalchemy import select as _select
    from app.models.strategy import Strategy
    session = _get_sync_session()
    try:
        if strategy_id is None:
            strategy = session.execute(
                _select(Strategy)
                .where(Strategy.status == "promoted")
                .order_by(Strategy.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if not strategy:
                logger.info("Portfolio simulation: promoted strateji yok, atlanıyor")
                return {"status": "skipped", "reason": "no_promoted_strategy"}
            strategy_id = strategy.id

        try:
            from app.services.portfolio_simulation import PortfolioSimulator, SimulationConfig
            from app.models.portfolio import PortfolioSimulation, PortfolioSnapshot
        except ImportError as e:
            logger.warning("Portfolio simulation modülleri eksik: %s", e)
            return {"status": "skipped", "reason": str(e)}

        strategy = session.get(Strategy, strategy_id)
        tickers = tickers or settings.mvp_tickers
        config = strategy.config or {}

        from app.services.model_training import ModelTrainer
        from app.services.backtester import Backtester

        trainer = ModelTrainer(session, config)
        df = trainer.load_dataset(tickers)
        if df.empty:
            return {"status": "failed", "reason": "no_data"}

        predict_fn = getattr(trainer, "predict_all", None)
        predictions = predict_fn(df) if predict_fn else None
        if predictions is None or (hasattr(predictions, "empty") and predictions.empty):
            logger.warning("Portfolio simulation: tahmin üretilemedi")
            return {"status": "failed", "reason": "no_predictions"}

        price_df = df[["week_ending", "ticker", "open", "close", "high", "low"]].copy()
        price_df = price_df.rename(columns={"week_ending": "date"})

        threshold = config.get("threshold", 0.5)
        top_n = config.get("top_n", 5)
        holding_weeks = config.get("holding_weeks", 1)

        backtester = Backtester(
            predictions, price_df,
            threshold=threshold, top_n=top_n,
            holding_weeks=holding_weeks,
        )
        bt_result = backtester.run()

        trades = [
            {
                "ticker": t.ticker,
                "entry_date": t.entry_date,
                "exit_date": t.exit_date,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "return_pct": t.return_pct,
                "signal_strength": getattr(t, "signal_strength", None),
            }
            for t in bt_result.trades
        ]

        sim_config = SimulationConfig(
            initial_capital=100_000.0,
            max_positions=top_n,
            max_position_weight=0.25,
            transaction_cost_bps=getattr(settings, "transaction_cost_bps", 5),
            slippage_bps=getattr(settings, "slippage_bps", 5),
        )
        simulator = PortfolioSimulator(sim_config)
        sim_result = simulator.simulate(trades, price_df)

        sim = PortfolioSimulation(
            strategy_id=strategy_id,
            initial_capital=100_000.0,
            max_positions=top_n,
            max_position_weight=0.25,
            transaction_cost_bps=getattr(settings, "transaction_cost_bps", 5),
            slippage_bps=getattr(settings, "slippage_bps", 5),
            rebalance_frequency="weekly",
        )
        session.add(sim)
        session.flush()

        for snap in sim_result.snapshots:
            session.add(PortfolioSnapshot(
                simulation_id=sim.id,
                date=snap["date"],
                total_value=snap["total_value"],
                cash_value=snap.get("cash_value"),
                invested_value=snap.get("invested_value"),
                n_positions=snap.get("n_positions"),
                sector_exposure=snap.get("sector_exposure"),
                monthly_return=snap.get("monthly_return"),
                ytd_return=snap.get("ytd_return"),
                drawdown=snap.get("drawdown"),
            ))
        session.commit()

        logger.info(
            "Portfolio simulation tamamlandı: strategy=%d sim_id=%d trades=%d",
            strategy_id, sim.id, len(bt_result.trades),
        )
        return {
            "status": "ok",
            "simulation_id": sim.id,
            "trades_executed": len(bt_result.trades),
            "worst_month": getattr(sim_result, "worst_month", None),
            "best_month": getattr(sim_result, "best_month", None),
            "portfolio_volatility": getattr(sim_result, "portfolio_volatility", None),
        }
    except Exception as e:
        logger.error("Portfolio simulation failed: %s", e, exc_info=True)
        return {"status": "failed", "reason": str(e)}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.snapshot_universe")
def snapshot_universe(self, index_name: str = "SP500", tickers: list[str] | None = None):
    """Record a survivorship-safe universe snapshot for today."""
    from app.services.data_ingestion import DataIngestionService
    from datetime import date
    session = _get_sync_session()
    try:
        svc = DataIngestionService(session)
        tickers = tickers or settings.mvp_tickers
        svc.record_universe_snapshot(date.today(), tickers, index_name)
        session.commit()
        logger.info(f"Universe snapshot recorded: {len(tickers)} tickers for {index_name}")
        return {"status": "ok", "tickers": len(tickers), "date": str(date.today())}
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.run_full_pipeline")
def run_full_pipeline(
    self,
    tickers: list[str] | None = None,
    start: str = "2010-01-01",
    strategy_id: int | None = None,
    week_starting: str | None = None,
):
    """Full weekly pipeline in dependency order."""
    session = _get_sync_session()
    try:
        if _check_kill_switch(session):
            return {"status": "blocked", "reason": "kill_switch_active"}
    finally:
        session.close()

    tickers = tickers or settings.mvp_tickers
    workflow = chain(
        snapshot_universe.si(tickers=tickers),
        ingest_prices.si(tickers=tickers, start=start),
        ingest_macro.si(start=start),
        ingest_news.si(tickers=tickers),
        ingest_social.si(tickers=tickers),
        ingest_financials.si(tickers=tickers),
        ingest_statements.si(tickers=tickers),
        ingest_pead.si(tickers=tickers),
        ingest_short_interest.si(tickers=tickers),
        compute_features.si(tickers=tickers),
        compute_data_quality_scores.si(),
        update_pead_confirmations.si(tickers=tickers),
        detect_regimes.si(),
        generate_weekly_predictions.si(
            tickers=tickers,
            week_starting=week_starting,
            strategy_id=strategy_id,
            open_paper=True,
        ),
        run_portfolio_simulation_auto.si(tickers=tickers),
    )
    result = workflow.apply_async()
    return {
        "status": "scheduled",
        "workflow_id": result.id,
        "steps": [
            "snapshot_universe",
            "ingest_prices",
            "ingest_macro",
            "ingest_news",
            "ingest_social",
            "ingest_financials",
            "ingest_statements",
            "ingest_pead",
            "ingest_short_interest",
            "compute_features",
            "compute_data_quality_scores",
            "update_pead_confirmations",
            "detect_regimes",
            "generate_weekly_predictions",
            "run_portfolio_simulation_auto",
        ],
    }
