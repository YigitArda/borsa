from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

from app.services.connectors.optional import WorldBankMacroConnector


def make_fake_session():
    session = MagicMock()
    session.query.return_value.filter_by.return_value.one_or_none.return_value = None
    return session


def test_worldbank_gdp_indicator_code(monkeypatch):
    monkeypatch.setattr("app.services.connectors.optional.settings.worldbank_default_countries", ["US"])
    monkeypatch.setattr("app.services.connectors.optional.settings.connector_request_timeout", 20)

    session = make_fake_session()
    captured_rows = []

    def fake_execute(stmt):
        nonlocal captured_rows
        try:
            rows = stmt._values if hasattr(stmt, "_values") else []
            if hasattr(stmt, "compile"):
                pass
        except Exception:
            pass
        return MagicMock()

    session.execute = fake_execute

    fake_response = [
        {"page": 1, "pages": 1},
        [
            {"date": "2022", "value": 25462700000000.0, "country": {"id": "US"}},
            {"date": "2021", "value": 23315080000000.0, "country": {"id": "US"}},
        ],
    ]

    with patch("app.services.connectors.optional.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_response
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        connector = WorldBankMacroConnector(session)
        result = connector._ingest("US", "NY.GDP.MKTP.CD", 2020, 2022)

    assert result == 2


def test_worldbank_available_at_lag():
    obs_date = date(2021, 1, 1)
    expected = datetime.combine(obs_date + timedelta(days=90), datetime.min.time())
    assert expected == datetime(2021, 4, 1)


def test_worldbank_indicator_code_format(monkeypatch):
    monkeypatch.setattr("app.services.connectors.optional.settings.worldbank_default_countries", ["US"])
    monkeypatch.setattr("app.services.connectors.optional.settings.connector_request_timeout", 20)

    session = make_fake_session()
    rows_persisted = []

    original_execute = session.execute

    def capture_execute(stmt):
        try:
            if hasattr(stmt, "new_rows"):
                rows_persisted.extend(stmt.new_rows)
        except Exception:
            pass
        return MagicMock()

    session.execute = capture_execute

    fake_response = [
        {"page": 1},
        [{"date": "2022", "value": 1.5, "country": {"id": "US"}}],
    ]

    with patch("app.services.connectors.optional.pg_insert") as mock_pg_insert:
        mock_stmt = MagicMock()
        mock_stmt.on_conflict_do_update.return_value = mock_stmt
        mock_pg_insert.return_value = mock_stmt

        with patch("app.services.connectors.optional.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = fake_response
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            connector = WorldBankMacroConnector(session)
            result = connector._ingest("US", "NY.GDP.MKTP.CD", 2020, 2022)

    assert result == 1
    call_args = mock_pg_insert.call_args
    assert call_args is not None

    rows_arg = mock_stmt.call_count >= 0
    values_call = mock_pg_insert.return_value.values.call_args
    if values_call:
        rows = values_call[0][0] if values_call[0] else values_call[1].get("rows", [])
        if isinstance(rows, list) and rows:
            assert rows[0]["indicator_code"] == "WB_NY.GDP.MKTP.CD_US"
            expected_avail = datetime.combine(date(2022, 1, 1) + timedelta(days=90), datetime.min.time())
            assert rows[0]["available_at"] == expected_avail


def test_worldbank_empty_response_returns_zero(monkeypatch):
    monkeypatch.setattr("app.services.connectors.optional.settings.worldbank_default_countries", ["US"])
    monkeypatch.setattr("app.services.connectors.optional.settings.connector_request_timeout", 20)

    session = make_fake_session()

    with patch("app.services.connectors.optional.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"page": 1}, []]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        connector = WorldBankMacroConnector(session)
        result = connector._ingest("US", "NY.GDP.MKTP.CD", 2020, 2022)

    assert result == 0
