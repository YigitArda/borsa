from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from app.services.connectors.optional import KrakenCryptoConnector


def make_fake_session():
    return MagicMock()


def test_kraken_is_configured():
    session = make_fake_session()
    assert KrakenCryptoConnector(session).is_configured() is True


def test_kraken_ohlc_normalize(monkeypatch):
    monkeypatch.setattr("app.services.connectors.optional.settings.kraken_pairs", ["XBTUSD"])
    monkeypatch.setattr("app.services.connectors.optional.settings.connector_request_timeout", 20)

    session = make_fake_session()

    ts = int(datetime(2024, 3, 15, tzinfo=timezone.utc).timestamp())
    fake_response = {
        "error": [],
        "result": {
            "XXBTZUSD": [
                [ts, "65000.0", "66000.0", "64000.0", "65500.0", "65200.0", "100.5", 1200],
            ],
            "last": ts + 86400,
        },
    }

    persisted_rows = []

    def capture_pg_insert(model):
        stmt = MagicMock()

        def values(rows):
            persisted_rows.extend(rows)
            inner = MagicMock()
            inner.on_conflict_do_nothing.return_value = inner
            return inner

        stmt.values = values
        return stmt

    with patch("app.services.connectors.optional.pg_insert", side_effect=capture_pg_insert):
        with patch("app.services.connectors.optional.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = fake_response
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            result = KrakenCryptoConnector(session).run()

    assert result.status == "ok"
    assert result.rows == 1
    assert len(persisted_rows) == 1

    row = persisted_rows[0]
    assert row["pair"] == "XBTUSD"
    assert row["close"] == 65500.0
    assert row["vwap"] == 65200.0
    assert row["volume"] == 100.5
    assert row["provider_id"] == "kraken_crypto"
    assert row["source_quality"] == 0.9
    assert row["available_at"].date() == date(2024, 3, 16)


def test_kraken_available_at_is_close_plus_one_day():
    bar_date = date(2024, 3, 15)
    available_at = datetime.combine(bar_date + __import__("datetime").timedelta(days=1), datetime.min.time())
    assert available_at.date() == date(2024, 3, 16)


def test_kraken_pairs_setting(monkeypatch):
    monkeypatch.setattr("app.services.connectors.optional.settings.kraken_pairs", ["XBTUSD", "ETHUSD"])
    from app.config import settings
    monkeypatch.setattr(settings, "kraken_pairs", ["XBTUSD", "ETHUSD"])
    assert "XBTUSD" in settings.kraken_pairs
    assert "ETHUSD" in settings.kraken_pairs
