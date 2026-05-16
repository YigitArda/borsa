from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest


def test_social_sentiment_runs_sources_in_priority_order(monkeypatch):
    from app.services.social_sentiment import SocialSentimentService

    calls: list[str] = []

    class DummyReddit:
        def __init__(self, session):
            self.session = session

        def ingest_recent(self, tickers):
            calls.append("reddit")
            return {ticker: 1 for ticker in tickers}

    class DummyStocktwits:
        def __init__(self, session):
            self.session = session

        def ingest_recent(self, tickers):
            calls.append("stocktwits")
            return {ticker: 2 for ticker in tickers}

    class DummyTwitter:
        def __init__(self, session):
            self.session = session

        def ingest_recent(self, tickers):
            calls.append("twitter")
            return {ticker: 3 for ticker in tickers}

    monkeypatch.setattr("app.services.reddit_sentiment.RedditSentimentService", DummyReddit)
    monkeypatch.setattr("app.services.stocktwits_sentiment.StocktwitsSentimentService", DummyStocktwits)
    monkeypatch.setattr("app.services.twitter_sentiment.TwitterSentimentService", DummyTwitter)

    service = SocialSentimentService(session=object())
    result = service.run_all(["AAPL"])

    assert calls == ["reddit", "stocktwits", "twitter"]
    assert result["AAPL"] == 6


def test_reddit_falls_back_month_then_year(monkeypatch):
    from app.models.stock import Stock
    from app.services.reddit_sentiment import RedditSentimentService

    stock = Stock(id=1, ticker="AAPL")
    attempts: list[str] = []
    captured: dict[str, str] = {}

    class FakeResult:
        def __init__(self, row):
            self._row = row

        def scalar_one_or_none(self):
            return self._row

    class FakeSession:
        def execute(self, stmt):
            return FakeResult(stock)

    def fake_record_source_health(*args, **kwargs):
        return None

    def fake_fetch_pushshift(self, ticker, start, end):
        return iter(())

    def fake_fetch_praw(self, ticker, limit=500, time_filter="month"):
        attempts.append(time_filter)
        if time_filter == "year":
            created_utc = datetime(2025, 1, 7, tzinfo=timezone.utc).timestamp()
            return iter(
                [
                    {
                        "title": "AAPL beats estimates",
                        "selftext": "strong quarter",
                        "created_utc": created_utc,
                        "score": 1,
                        "subreddit": "stocks",
                    }
                ]
            )
        return iter(())

    def fake_get_vader():
        return SimpleNamespace(polarity_scores=lambda text: {"compound": 0.75})

    def fake_upsert_weeks(session, *, stock_id, week_data, source, source_used):
        captured["source_used"] = source_used
        captured["week_count"] = str(len(week_data))
        return len(week_data)

    monkeypatch.setattr("app.services.reddit_sentiment.record_source_health", fake_record_source_health)
    monkeypatch.setattr("app.services.reddit_sentiment.get_vader_analyzer", fake_get_vader)
    monkeypatch.setattr("app.services.reddit_sentiment.upsert_social_weekly_rows", fake_upsert_weeks)
    monkeypatch.setattr(RedditSentimentService, "_fetch_pushshift", fake_fetch_pushshift)
    monkeypatch.setattr(RedditSentimentService, "_fetch_praw", fake_fetch_praw)

    service = RedditSentimentService(FakeSession())
    written = service.ingest_ticker("AAPL", date(2025, 1, 1), date(2025, 1, 10))

    assert attempts == ["month", "year"]
    assert captured["source_used"] == "praw_year"
    assert written == 1
