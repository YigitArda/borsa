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
def run_research_loop(self, n_iterations: int = 5, base_strategy_id: int | None = None):
    from app.services.research_loop import ResearchLoop
    session = _get_sync_session()
    try:
        if _check_kill_switch(session):
            return {"status": "blocked", "reason": "kill_switch_active"}
        loop = ResearchLoop(session, settings.mvp_tickers)
        results = loop.run_loop(n_iterations=n_iterations, base_strategy_id=base_strategy_id)
        return {"status": "ok", "results": results}
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
        compute_features.si(tickers=tickers),
        generate_weekly_predictions.si(
            tickers=tickers,
            week_starting=week_starting,
            strategy_id=strategy_id,
            open_paper=True,
        ),
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
            "compute_features",
            "generate_weekly_predictions",
        ],
    }
