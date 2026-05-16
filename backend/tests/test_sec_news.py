"""SEC EDGAR news service smoke tests."""
import pytest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from app.services.sec_news import SECNewsService, SEC_START


class FakeStock:
    def __init__(self):
        self.id = 1
        self.ticker = "AAPL"


class FakeArticle:
    def __init__(self, id, url_hash, published_at, headline, source="sec_edgar"):
        self.id = id
        self.url_hash = url_hash
        self.published_at = published_at
        self.headline = headline
        self.source = source
        self.ticker_mentions = ["AAPL"]


class FakeSession:
    def __init__(self):
        self._articles = {}
        self._analysis = []
        self._committed = False
        self._next_id = 100

    def execute(self, stmt):
        text = str(stmt)
        # Stock lookup
        if "stocks" in text and "ticker" in text:
            class Result:
                def scalar_one_or_none(_):
                    return FakeStock()
            return Result()
        # pg_insert - extract url_hash from stmt._values
        if "INSERT INTO news_articles" in text:
            try:
                vals = stmt._values
                url_hash = None
                for col, param in vals.items():
                    if hasattr(col, "name") and col.name == "url_hash":
                        url_hash = param.value
                        break
                if url_hash:
                    fa = FakeArticle(self._next_id, url_hash, None, "")
                    self._articles[url_hash] = fa
                    self._next_id += 1
            except Exception:
                pass
            class Result:
                pass
            return Result()
        # Select news_articles by url_hash
        if "news_articles" in text and "url_hash" in text:
            class Result:
                def scalar_one_or_none(_):
                    if self._articles:
                        return list(self._articles.values())[-1]
                    return None
            return Result()
        # NewsAnalysis lookup
        if "news_analysis" in text:
            class Result:
                def scalar_one_or_none(_):
                    return None
            return Result()
        class Result:
            def scalar_one_or_none(_):
                return None
        return Result()

    def flush(self):
        pass

    def commit(self):
        self._committed = True

    def add(self, obj):
        if hasattr(obj, "news_id"):
            self._analysis.append(obj)


class TestSECNewsService:
    def test_pre_sec_date_returns_zero(self):
        """Dates before 2001 should return 0 (SEC EDGAR limit)."""
        session = FakeSession()
        svc = SECNewsService(session)
        result = svc.ingest_ticker("AAPL", date(1995, 1, 1), date(1995, 1, 31))
        assert result == 0

    def test_no_cik_returns_zero(self):
        """If CIK lookup fails, should return 0 gracefully."""
        session = FakeSession()
        svc = SECNewsService(session)

        with patch("app.services.sec_news.get_cik", return_value=None):
            result = svc.ingest_ticker("AAPL", date(2024, 1, 1), date(2024, 1, 31))

        assert result == 0

    def test_filing_creates_article(self):
        """Valid 8-K filing should create NewsArticle + NewsAnalysis."""
        session = FakeSession()
        svc = SECNewsService(session)

        mock_hit = {
            "_id": "0000320193-24-000001",
            "_source": {
                "filed": "2024-01-15",
                "form": "8-K",
                "description": "Apple reports Q1 earnings",
                "entity_name": "Apple Inc.",
            },
        }

        with patch("app.services.sec_news.get_cik", return_value="0000320193"):
            with patch("requests.get") as mock_get:
                mock_get.return_value.json.return_value = {"hits": {"hits": [mock_hit]}}
                mock_get.return_value.raise_for_status = MagicMock()

                result = svc.ingest_ticker("AAPL", date(2024, 1, 1), date(2024, 1, 31))

        assert result == 1
        assert session._committed
        assert len(session._articles) == 1
        assert len(session._analysis) == 1

    def test_published_at_is_filing_date(self):
        """published_at must be SEC filing date, never datetime.now()."""
        session = FakeSession()
        svc = SECNewsService(session)

        mock_hit = {
            "_id": "0000320193-24-000002",
            "_source": {
                "filed": "2020-03-15",
                "form": "8-K",
                "description": "CEO change",
                "entity_name": "Apple Inc.",
            },
        }

        with patch("app.services.sec_news.get_cik", return_value="0000320193"):
            with patch("requests.get") as mock_get:
                mock_get.return_value.json.return_value = {"hits": {"hits": [mock_hit]}}
                mock_get.return_value.raise_for_status = MagicMock()

                svc.ingest_ticker("AAPL", date(2020, 1, 1), date(2020, 3, 31))

        assert len(session._articles) >= 1
        assert session._committed

    def test_earnings_keyword_classification(self):
        """8-K with earnings keywords should set is_earnings=True."""
        session = FakeSession()
        svc = SECNewsService(session)

        mock_hit = {
            "_id": "0000320193-24-000003",
            "_source": {
                "filed": "2024-01-15",
                "form": "8-K",
                "description": "Quarterly earnings release",
                "entity_name": "Apple Inc.",
            },
        }

        with patch("app.services.sec_news.get_cik", return_value="0000320193"):
            with patch("requests.get") as mock_get:
                mock_get.return_value.json.return_value = {"hits": {"hits": [mock_hit]}}
                mock_get.return_value.raise_for_status = MagicMock()

                svc.ingest_ticker("AAPL", date(2024, 1, 1), date(2024, 1, 31))

        assert len(session._analysis) == 1
        analysis = session._analysis[0]
        assert analysis.is_earnings is True

    def test_management_keyword_classification(self):
        """8-K with CEO keywords should set is_management_change=True."""
        session = FakeSession()
        svc = SECNewsService(session)

        mock_hit = {
            "_id": "0000320193-24-000004",
            "_source": {
                "filed": "2024-01-15",
                "form": "8-K",
                "description": "Chief executive officer appointed",
                "entity_name": "Apple Inc.",
            },
        }

        with patch("app.services.sec_news.get_cik", return_value="0000320193"):
            with patch("requests.get") as mock_get:
                mock_get.return_value.json.return_value = {"hits": {"hits": [mock_hit]}}
                mock_get.return_value.raise_for_status = MagicMock()

                svc.ingest_ticker("AAPL", date(2024, 1, 1), date(2024, 1, 31))

        assert len(session._analysis) == 1
        analysis = session._analysis[0]
        assert analysis.is_management_change is True
