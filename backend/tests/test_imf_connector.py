from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from app.services.connectors.optional import IMFMacroConnector


def make_fake_session():
    session = MagicMock()
    return session


def test_imf_persist_macro_indicator(monkeypatch):
    monkeypatch.setattr("app.services.connectors.optional.settings.imf_default_countries", ["USA"])
    monkeypatch.setattr("app.services.connectors.optional.settings.connector_request_timeout", 20)

    session = make_fake_session()

    fake_response = {
        "values": {
            "NGDP_RPCH": {
                "USA": {
                    "2020": -3.4,
                    "2021": 5.9,
                    "2022": 2.1,
                }
            }
        }
    }

    with patch("app.services.connectors.optional.pg_insert") as mock_pg_insert:
        mock_stmt = MagicMock()
        mock_stmt.on_conflict_do_update.return_value = mock_stmt
        mock_pg_insert.return_value = mock_stmt

        with patch("app.services.connectors.optional.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = fake_response
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            result = IMFMacroConnector(session)._ingest("NGDP_RPCH", "USA")

    assert result == 3

    values_call = mock_pg_insert.return_value.values.call_args
    if values_call:
        rows = values_call[0][0] if values_call[0] else []
        if rows:
            row_2021 = next((r for r in rows if r["date"] == date(2021, 1, 1)), None)
            if row_2021:
                assert row_2021["indicator_code"] == "IMF_NGDP_RPCH_USA"
                assert row_2021["value"] == 5.9
                assert row_2021["source_quality"] == 0.85
                assert row_2021["available_at"] == datetime(2022, 1, 1)


def test_imf_available_at_is_year_plus_one():
    year = 2021
    obs_date = date(year, 1, 1)
    available_at = datetime(year + 1, 1, 1)
    assert available_at == datetime(2022, 1, 1)


def test_imf_unreachable_returns_failed(monkeypatch):
    monkeypatch.setattr("app.services.connectors.optional.settings.imf_default_countries", ["USA"])
    monkeypatch.setattr("app.services.connectors.optional.settings.connector_request_timeout", 20)

    session = make_fake_session()

    import requests as _req
    with patch("app.services.connectors.optional.requests.get", side_effect=_req.exceptions.ConnectionError("unreachable")):
        result = IMFMacroConnector(session).run()

    assert result.status == "failed"
    assert result.rows == 0


def test_imf_empty_values_returns_zero(monkeypatch):
    monkeypatch.setattr("app.services.connectors.optional.settings.imf_default_countries", ["USA"])
    monkeypatch.setattr("app.services.connectors.optional.settings.connector_request_timeout", 20)

    session = make_fake_session()
    fake_response = {"values": {"NGDP_RPCH": {"USA": {}}}}

    with patch("app.services.connectors.optional.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_response
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = IMFMacroConnector(session)._ingest("NGDP_RPCH", "USA")

    assert result == 0
