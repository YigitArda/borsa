import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


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


@celery_app.task(bind=True, name="app.tasks.pipeline_tasks.run_full_pipeline")
def run_full_pipeline(self):
    """Full weekly pipeline: ingest → macro → news → social → financials → statements → features → research."""
    ingest_prices.delay()
    ingest_macro.delay()
    ingest_news.delay()
    ingest_social.delay()
    ingest_financials.delay()
    ingest_statements.delay()
    compute_features.delay()
    return {"status": "scheduled"}
