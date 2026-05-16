"""pytest tests for the smoke test / verification system."""

from __future__ import annotations

import pytest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from app.services.verification import (
    SmokeTestRunner,
    SmokeTestReport,
    SmokeCheckResult,
    run_smoke_test_sync,
)
from app.time_utils import utcnow


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def runner() -> SmokeTestRunner:
    return SmokeTestRunner(base_url="http://test")


class _FakeResult:
    """Fake SQLAlchemy result whose .all() returns a fixed list."""

    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDB:
    """Fake async DB session that supports `async with`."""

    def __init__(self, execute_results=None):
        self._execute_results = list(execute_results) if execute_results else []
        self._call_idx = 0

    async def execute(self, query):
        if self._call_idx < len(self._execute_results):
            res = self._execute_results[self._call_idx]
            self._call_idx += 1
            return res
        return _FakeResult([])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _make_db(rows_or_results):
    """Return a coroutine that yields a _FakeDB."""
    if rows_or_results and not isinstance(rows_or_results[0], _FakeResult):
        results = [_FakeResult(r) for r in rows_or_results]
    else:
        results = rows_or_results

    async def _coro():
        return _FakeDB(results)

    return _coro


# ------------------------------------------------------------------
# Unit tests for individual checks
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_stocks_in_db_pass(runner, monkeypatch):
    """All MVP tickers present → pass."""
    tickers = [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
        "META", "TSLA", "BRK-B", "JPM", "V",
        "UNH", "XOM", "JNJ", "MA", "PG",
        "HD", "CVX", "MRK", "LLY", "ABBV",
    ]
    monkeypatch.setattr(runner, "_get_db", _make_db([[(t,) for t in tickers]]))
    res = await runner.check_stocks_in_db()
    assert res.status == "pass"
    assert "All 20 MVP tickers present" in res.message


@pytest.mark.asyncio
async def test_check_stocks_in_db_fail(runner, monkeypatch):
    """Missing tickers → fail."""
    monkeypatch.setattr(runner, "_get_db", _make_db([[("AAPL",), ("MSFT",)]]))
    res = await runner.check_stocks_in_db()
    assert res.status == "fail"
    assert "Missing tickers" in res.message


@pytest.mark.asyncio
async def test_check_prices_daily_pass(runner, monkeypatch):
    tickers = [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
        "META", "TSLA", "BRK-B", "JPM", "V",
        "UNH", "XOM", "JNJ", "MA", "PG",
        "HD", "CVX", "MRK", "LLY", "ABBV",
    ]
    monkeypatch.setattr(runner, "_get_db", _make_db([[(t, 500) for t in tickers]]))
    res = await runner.check_prices_daily()
    assert res.status == "pass"


@pytest.mark.asyncio
async def test_check_prices_daily_warn(runner, monkeypatch):
    # Provide all 20 tickers with low counts so only the "low" branch triggers
    tickers = [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
        "META", "TSLA", "BRK-B", "JPM", "V",
        "UNH", "XOM", "JNJ", "MA", "PG",
        "HD", "CVX", "MRK", "LLY", "ABBV",
    ]
    monkeypatch.setattr(runner, "_get_db", _make_db([[(t, 50) for t in tickers]]))
    res = await runner.check_prices_daily()
    assert res.status == "warn"


@pytest.mark.asyncio
async def test_check_prices_weekly_pass(runner, monkeypatch):
    tickers = [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
        "META", "TSLA", "BRK-B", "JPM", "V",
        "UNH", "XOM", "JNJ", "MA", "PG",
        "HD", "CVX", "MRK", "LLY", "ABBV",
    ]
    monkeypatch.setattr(runner, "_get_db", _make_db([[(t, 100) for t in tickers]]))
    res = await runner.check_prices_weekly()
    assert res.status == "pass"


@pytest.mark.asyncio
async def test_check_features_pass(runner, monkeypatch):
    class _ScalarDB(_FakeDB):
        call_idx = 0
        async def execute(self, query):
            vals = {0: 10000, 1: 100, 2: 200}
            class R:
                def scalar(self):
                    v = vals[_ScalarDB.call_idx]
                    _ScalarDB.call_idx += 1
                    return v
            return R()

    async def _coro():
        _ScalarDB.call_idx = 0
        return _ScalarDB()

    monkeypatch.setattr(runner, "_get_db", _coro)
    res = await runner.check_features()
    assert res.status == "pass"


@pytest.mark.asyncio
async def test_check_features_fail_no_rows(runner, monkeypatch):
    class _ScalarDB(_FakeDB):
        async def execute(self, query):
            class R:
                def scalar(self):
                    return 0
            return R()

    async def _coro():
        return _ScalarDB()

    monkeypatch.setattr(runner, "_get_db", _coro)
    res = await runner.check_features()
    assert res.status == "fail"
    assert "No feature rows" in res.message


@pytest.mark.asyncio
async def test_check_labels_pass(runner, monkeypatch):
    class _ScalarDB(_FakeDB):
        call_idx = 0
        async def execute(self, query):
            class R:
                def scalar(self):
                    val = {0: 5000, 1: 0, 2: 3}[_ScalarDB.call_idx]
                    _ScalarDB.call_idx += 1
                    return val
            return R()

    async def _coro():
        return _ScalarDB()

    monkeypatch.setattr(runner, "_get_db", _coro)
    res = await runner.check_labels()
    assert res.status == "pass"
    assert "no lookahead" in res.message


@pytest.mark.asyncio
async def test_check_labels_fail_lookahead(runner, monkeypatch):
    class _ScalarDB(_FakeDB):
        call_idx = 0
        async def execute(self, query):
            class R:
                def scalar(self):
                    val = {0: 5000, 1: 10, 2: 3}[_ScalarDB.call_idx]
                    _ScalarDB.call_idx += 1
                    return val
            return R()

    async def _coro():
        return _ScalarDB()

    monkeypatch.setattr(runner, "_get_db", _coro)
    res = await runner.check_labels()
    assert res.status == "fail"
    assert "lookahead" in res.message


@pytest.mark.asyncio
async def test_check_model_trained_pass_dir(runner, monkeypatch, tmp_path):
    model_file = tmp_path / "model_v1.pkl"
    model_file.write_text("dummy")
    monkeypatch.setattr("app.services.verification.settings.models_dir", str(tmp_path))
    res = await runner.check_model_trained()
    assert res.status == "pass"


@pytest.mark.asyncio
async def test_check_model_trained_pass_db(runner, monkeypatch):
    monkeypatch.setattr("app.services.verification.settings.models_dir", "/nonexistent")

    class _ScalarDB(_FakeDB):
        async def execute(self, query):
            class R:
                def scalar(self):
                    return 5
            return R()

    async def _coro():
        return _ScalarDB()

    monkeypatch.setattr(runner, "_get_db", _coro)
    res = await runner.check_model_trained()
    assert res.status == "pass"
    assert "model version(s) in DB" in res.message


@pytest.mark.asyncio
async def test_check_model_trained_fail(runner, monkeypatch):
    monkeypatch.setattr("app.services.verification.settings.models_dir", "/nonexistent")

    class _ScalarDB(_FakeDB):
        async def execute(self, query):
            class R:
                def scalar(self):
                    return 0
            return R()

    async def _coro():
        return _ScalarDB()

    monkeypatch.setattr(runner, "_get_db", _coro)
    res = await runner.check_model_trained()
    assert res.status == "fail"


@pytest.mark.asyncio
async def test_check_backtest_trades_pass(runner, monkeypatch):
    class _ScalarDB(_FakeDB):
        call_idx = 0
        async def execute(self, query):
            class R:
                def scalar(self):
                    val = {0: 10, 1: 150, 2: 8}[_ScalarDB.call_idx]
                    _ScalarDB.call_idx += 1
                    return val
            return R()

    async def _coro():
        return _ScalarDB()

    monkeypatch.setattr(runner, "_get_db", _coro)
    res = await runner.check_backtest_trades()
    assert res.status == "pass"
    assert res.details["trades"] == 150


@pytest.mark.asyncio
async def test_check_backtest_trades_warn_no_trades(runner, monkeypatch):
    class _ScalarDB(_FakeDB):
        call_idx = 0
        async def execute(self, query):
            class R:
                def scalar(self):
                    val = {0: 5, 1: 0, 2: 0}[_ScalarDB.call_idx]
                    _ScalarDB.call_idx += 1
                    return val
            return R()

    async def _coro():
        return _ScalarDB()

    monkeypatch.setattr(runner, "_get_db", _coro)
    res = await runner.check_backtest_trades()
    assert res.status == "warn"


@pytest.mark.asyncio
async def test_check_weekly_predictions_pass(runner, monkeypatch):
    class _ScalarDB(_FakeDB):
        call_idx = 0
        async def execute(self, query):
            class R:
                def scalar(self):
                    val = {0: 120, 1: date(2024, 1, 5), 2: 2}[_ScalarDB.call_idx]
                    _ScalarDB.call_idx += 1
                    return val
            return R()

    async def _coro():
        return _ScalarDB()

    monkeypatch.setattr(runner, "_get_db", _coro)
    res = await runner.check_weekly_predictions()
    assert res.status == "pass"
    assert res.details["total"] == 120


@pytest.mark.asyncio
async def test_check_weekly_predictions_fail(runner, monkeypatch):
    class _ScalarDB(_FakeDB):
        call_idx = 0
        async def execute(self, query):
            class R:
                def scalar(self):
                    val = {0: 0, 1: None, 2: 0}[_ScalarDB.call_idx]
                    _ScalarDB.call_idx += 1
                    return val
            return R()

    async def _coro():
        return _ScalarDB()

    monkeypatch.setattr(runner, "_get_db", _coro)
    res = await runner.check_weekly_predictions()
    assert res.status == "fail"


@pytest.mark.asyncio
async def test_check_api_endpoints_pass(runner, monkeypatch):
    class FakeResponse:
        status_code = 200

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, path):
            return FakeResponse()

    monkeypatch.setattr("app.services.verification.httpx.AsyncClient", FakeClient)
    res = await runner.check_api_endpoints()
    assert res.status == "pass"


@pytest.mark.asyncio
async def test_check_api_endpoints_fail(runner, monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, path):
            raise ConnectionError("refused")

    monkeypatch.setattr("app.services.verification.httpx.AsyncClient", FakeClient)
    res = await runner.check_api_endpoints()
    assert res.status == "fail"


# ------------------------------------------------------------------
# Orchestrator tests
# ------------------------------------------------------------------

def _make_mock_check(runner, result: SmokeCheckResult):
    async def _check():
        runner._record(result.name, result.status, result.message, result.duration_ms, result.details)
        return result
    return _check


@pytest.mark.asyncio
async def test_run_full_smoke_test_aggregates_results(runner, monkeypatch):
    """The orchestrator should run all checks and produce a report."""
    monkeypatch.setattr(runner, "check_stocks_in_db", _make_mock_check(runner, SmokeCheckResult("stocks_in_db", "pass", "ok", 1.0, {})))
    monkeypatch.setattr(runner, "check_prices_daily", _make_mock_check(runner, SmokeCheckResult("prices_daily", "pass", "ok", 1.0, {})))
    monkeypatch.setattr(runner, "check_prices_weekly", _make_mock_check(runner, SmokeCheckResult("prices_weekly", "pass", "ok", 1.0, {})))
    monkeypatch.setattr(runner, "check_features", _make_mock_check(runner, SmokeCheckResult("features", "pass", "ok", 1.0, {})))
    monkeypatch.setattr(runner, "check_labels", _make_mock_check(runner, SmokeCheckResult("labels", "pass", "ok", 1.0, {})))
    monkeypatch.setattr(runner, "check_model_trained", _make_mock_check(runner, SmokeCheckResult("model_trained", "pass", "ok", 1.0, {})))
    monkeypatch.setattr(runner, "check_backtest_trades", _make_mock_check(runner, SmokeCheckResult("backtest_trades", "pass", "ok", 1.0, {})))
    monkeypatch.setattr(runner, "check_weekly_predictions", _make_mock_check(runner, SmokeCheckResult("weekly_predictions", "pass", "ok", 1.0, {})))
    monkeypatch.setattr(runner, "check_api_endpoints", _make_mock_check(runner, SmokeCheckResult("api_endpoints", "pass", "ok", 1.0, {})))

    report = await runner.run_full_smoke_test()
    assert report.overall == "pass"
    assert len(report.checks) == 9
    assert report.summary["pass"] == 9


@pytest.mark.asyncio
async def test_run_full_smoke_test_overall_fail(runner, monkeypatch):
    """Any failing check should set overall to fail."""
    monkeypatch.setattr(runner, "check_stocks_in_db", _make_mock_check(runner, SmokeCheckResult("stocks_in_db", "fail", "missing", 1.0, {})))
    for name in [
        "check_prices_daily", "check_prices_weekly", "check_features",
        "check_labels", "check_model_trained", "check_backtest_trades",
        "check_weekly_predictions", "check_api_endpoints",
    ]:
        monkeypatch.setattr(runner, name, _make_mock_check(runner, SmokeCheckResult(name, "pass", "ok", 1.0, {})))

    report = await runner.run_full_smoke_test()
    assert report.overall == "fail"
    assert report.summary["fail"] >= 1


@pytest.mark.asyncio
async def test_run_full_smoke_test_overall_warn(runner, monkeypatch):
    """Warnings without failures → overall warn."""
    monkeypatch.setattr(runner, "check_stocks_in_db", _make_mock_check(runner, SmokeCheckResult("stocks_in_db", "warn", "low", 1.0, {})))
    for name in [
        "check_prices_daily", "check_prices_weekly", "check_features",
        "check_labels", "check_model_trained", "check_backtest_trades",
        "check_weekly_predictions", "check_api_endpoints",
    ]:
        monkeypatch.setattr(runner, name, _make_mock_check(runner, SmokeCheckResult(name, "pass", "ok", 1.0, {})))

    report = await runner.run_full_smoke_test()
    assert report.overall == "warn"


@pytest.mark.asyncio
async def test_run_full_smoke_test_graceful_exception(runner, monkeypatch):
    """Unhandled exceptions in a check should be caught and recorded as fail."""
    async def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(runner, "check_stocks_in_db", _boom)
    for name in [
        "check_prices_daily", "check_prices_weekly", "check_features",
        "check_labels", "check_model_trained", "check_backtest_trades",
        "check_weekly_predictions", "check_api_endpoints",
    ]:
        monkeypatch.setattr(runner, name, _make_mock_check(runner, SmokeCheckResult(name, "pass", "ok", 1.0, {})))

    report = await runner.run_full_smoke_test()
    assert report.overall == "fail"
    # The exception handler uses check.__name__ which for a plain function is '_boom'
    assert any(c.name == "_boom" and c.status == "fail" for c in report.checks)


# ------------------------------------------------------------------
# Sync wrapper test
# ------------------------------------------------------------------

def test_run_smoke_test_sync():
    with patch.object(SmokeTestRunner, "run_full_smoke_test", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = SmokeTestReport(
            overall="pass",
            started_at=utcnow(),
            finished_at=utcnow(),
            checks=[],
            summary={"pass": 1},
        )
        report = run_smoke_test_sync()
        assert report.overall == "pass"
