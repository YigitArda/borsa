"""Smoke test engine for end-to-end pipeline verification.

Verifies the full data pipeline:
    stocks → prices → features → labels → model → backtest → predictions → API
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_sessionmaker
from app.models.stock import Stock
from app.models.price import PriceDaily, PriceWeekly
from app.models.feature import FeatureWeekly, LabelWeekly
from app.models.backtest import BacktestRun, BacktestTrade
from app.models.prediction import WeeklyPrediction
from app.models.strategy import ModelVersion

logger = logging.getLogger(__name__)


@dataclass
class SmokeCheckResult:
    """Result of a single smoke check."""

    name: str
    status: str  # pass | fail | warn | skip
    message: str
    duration_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SmokeTestReport:
    """Aggregated smoke test report."""

    overall: str  # pass | fail | warn
    started_at: datetime
    finished_at: datetime
    checks: list[SmokeCheckResult]
    summary: dict[str, int] = field(default_factory=dict)


class SmokeTestRunner:
    """End-to-end smoke test runner for the borsa pipeline."""

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        self.base_url = base_url.rstrip("/")
        self._results: list[SmokeCheckResult] = []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_db(self) -> AsyncSession:
        session_maker = get_sessionmaker()
        return session_maker()

    def _record(
        self,
        name: str,
        status: str,
        message: str,
        duration_ms: float = 0.0,
        details: dict[str, Any] | None = None,
    ) -> SmokeCheckResult:
        result = SmokeCheckResult(
            name=name,
            status=status,
            message=message,
            duration_ms=round(duration_ms, 2),
            details=details or {},
        )
        self._results.append(result)
        logger.info("[smoke] %s — %s — %s", name, status, message)
        return result

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    async def check_stocks_in_db(self) -> SmokeCheckResult:
        """Verify all 20 MVP tickers exist in the stocks table."""
        t0 = datetime.utcnow()
        try:
            async with await self._get_db() as db:
                result = await db.execute(
                    select(Stock.ticker).where(Stock.is_active == True)
                )
                tickers = {r[0] for r in result.all()}

            missing = set(settings.mvp_tickers) - tickers
            duration = (datetime.utcnow() - t0).total_seconds() * 1000

            if missing:
                return self._record(
                    "stocks_in_db",
                    "fail",
                    f"Missing tickers: {sorted(missing)}",
                    duration,
                    {"found": len(tickers), "expected": len(settings.mvp_tickers), "missing": sorted(missing)},
                )
            return self._record(
                "stocks_in_db",
                "pass",
                f"All {len(settings.mvp_tickers)} MVP tickers present",
                duration,
                {"found": len(tickers)},
            )
        except Exception as exc:
            duration = (datetime.utcnow() - t0).total_seconds() * 1000
            return self._record("stocks_in_db", "fail", str(exc), duration)

    async def check_prices_daily(self) -> SmokeCheckResult:
        """Verify prices_daily has data for each MVP stock."""
        t0 = datetime.utcnow()
        try:
            async with await self._get_db() as db:
                subq = (
                    select(PriceDaily.stock_id, func.count().label("cnt"))
                    .group_by(PriceDaily.stock_id)
                    .subquery()
                )
                result = await db.execute(
                    select(Stock.ticker, subq.c.cnt)
                    .join(subq, Stock.id == subq.c.stock_id)
                    .where(Stock.ticker.in_(settings.mvp_tickers))
                )
                counts = {r[0]: r[1] for r in result.all()}

            missing = [t for t in settings.mvp_tickers if t not in counts]
            low = [t for t, c in counts.items() if c < 100]
            duration = (datetime.utcnow() - t0).total_seconds() * 1000

            if missing:
                return self._record(
                    "prices_daily",
                    "fail",
                    f"{len(missing)} stocks have no daily prices",
                    duration,
                    {"missing": missing},
                )
            if low:
                return self._record(
                    "prices_daily",
                    "warn",
                    f"{len(low)} stocks have <100 daily rows",
                    duration,
                    {"low_data": low},
                )
            return self._record(
                "prices_daily",
                "pass",
                f"All {len(counts)} stocks have daily prices",
                duration,
                {"min_rows": min(counts.values()) if counts else 0},
            )
        except Exception as exc:
            duration = (datetime.utcnow() - t0).total_seconds() * 1000
            return self._record("prices_daily", "fail", str(exc), duration)

    async def check_prices_weekly(self) -> SmokeCheckResult:
        """Verify prices_weekly has data for each MVP stock."""
        t0 = datetime.utcnow()
        try:
            async with await self._get_db() as db:
                subq = (
                    select(PriceWeekly.stock_id, func.count().label("cnt"))
                    .group_by(PriceWeekly.stock_id)
                    .subquery()
                )
                result = await db.execute(
                    select(Stock.ticker, subq.c.cnt)
                    .join(subq, Stock.id == subq.c.stock_id)
                    .where(Stock.ticker.in_(settings.mvp_tickers))
                )
                counts = {r[0]: r[1] for r in result.all()}

            missing = [t for t in settings.mvp_tickers if t not in counts]
            low = [t for t, c in counts.items() if c < 20]
            duration = (datetime.utcnow() - t0).total_seconds() * 1000

            if missing:
                return self._record(
                    "prices_weekly",
                    "fail",
                    f"{len(missing)} stocks have no weekly prices",
                    duration,
                    {"missing": missing},
                )
            if low:
                return self._record(
                    "prices_weekly",
                    "warn",
                    f"{len(low)} stocks have <20 weekly rows",
                    duration,
                    {"low_data": low},
                )
            return self._record(
                "prices_weekly",
                "pass",
                f"All {len(counts)} stocks have weekly prices",
                duration,
                {"min_rows": min(counts.values()) if counts else 0},
            )
        except Exception as exc:
            duration = (datetime.utcnow() - t0).total_seconds() * 1000
            return self._record("prices_weekly", "fail", str(exc), duration)

    async def check_features(self) -> SmokeCheckResult:
        """Verify features_weekly has data and no excessive NaN."""
        t0 = datetime.utcnow()
        try:
            async with await self._get_db() as db:
                total = (
                    await db.execute(
                        select(func.count()).where(
                            FeatureWeekly.stock_id.in_(
                                select(Stock.id).where(Stock.ticker.in_(settings.mvp_tickers))
                            )
                        )
                    )
                ).scalar() or 0

                nulls = (
                    await db.execute(
                        select(func.count()).where(
                            FeatureWeekly.value.is_(None),
                            FeatureWeekly.stock_id.in_(
                                select(Stock.id).where(Stock.ticker.in_(settings.mvp_tickers))
                            ),
                        )
                    )
                ).scalar() or 0

                distinct_weeks = (
                    await db.execute(
                        select(func.count(func.distinct(FeatureWeekly.week_ending))).where(
                            FeatureWeekly.stock_id.in_(
                                select(Stock.id).where(Stock.ticker.in_(settings.mvp_tickers))
                            )
                        )
                    )
                ).scalar() or 0

            nan_ratio = nulls / total if total else 1.0
            duration = (datetime.utcnow() - t0).total_seconds() * 1000

            if total == 0:
                return self._record(
                    "features",
                    "fail",
                    "No feature rows found",
                    duration,
                    {"total": 0},
                )
            if nan_ratio > 0.25:
                return self._record(
                    "features",
                    "warn",
                    f"High NaN ratio: {nan_ratio:.2%}",
                    duration,
                    {"total": total, "nulls": nulls, "distinct_weeks": distinct_weeks},
                )
            return self._record(
                "features",
                "pass",
                f"{total} feature rows, {distinct_weeks} weeks, NaN ratio {nan_ratio:.2%}",
                duration,
                {"total": total, "nulls": nulls, "distinct_weeks": distinct_weeks},
            )
        except Exception as exc:
            duration = (datetime.utcnow() - t0).total_seconds() * 1000
            return self._record("features", "fail", str(exc), duration)

    async def check_labels(self) -> SmokeCheckResult:
        """Verify labels_weekly has data and no lookahead (future labels)."""
        t0 = datetime.utcnow()
        try:
            async with await self._get_db() as db:
                total = (
                    await db.execute(
                        select(func.count()).where(
                            LabelWeekly.stock_id.in_(
                                select(Stock.id).where(Stock.ticker.in_(settings.mvp_tickers))
                            )
                        )
                    )
                ).scalar() or 0

                today = date.today()
                future_labels = (
                    await db.execute(
                        select(func.count()).where(
                            LabelWeekly.week_ending > today,
                            LabelWeekly.stock_id.in_(
                                select(Stock.id).where(Stock.ticker.in_(settings.mvp_tickers))
                            ),
                        )
                    )
                ).scalar() or 0

                distinct_targets = (
                    await db.execute(
                        select(func.count(func.distinct(LabelWeekly.target_name)))
                    )
                ).scalar() or 0

            duration = (datetime.utcnow() - t0).total_seconds() * 1000

            if total == 0:
                return self._record(
                    "labels",
                    "fail",
                    "No label rows found",
                    duration,
                    {"total": 0},
                )
            if future_labels > 0:
                return self._record(
                    "labels",
                    "fail",
                    f"{future_labels} future labels detected — possible lookahead",
                    duration,
                    {"future_labels": future_labels, "total": total},
                )
            return self._record(
                "labels",
                "pass",
                f"{total} label rows, {distinct_targets} targets, no lookahead",
                duration,
                {"total": total, "distinct_targets": distinct_targets},
            )
        except Exception as exc:
            duration = (datetime.utcnow() - t0).total_seconds() * 1000
            return self._record("labels", "fail", str(exc), duration)

    async def check_model_trained(self) -> SmokeCheckResult:
        """Verify at least one model file exists in models_store."""
        t0 = datetime.utcnow()
        try:
            models_dir = Path(settings.models_dir)
            if not models_dir.exists():
                # Fallback: check DB for model version records
                async with await self._get_db() as db:
                    count = (
                        await db.execute(select(func.count()).select_from(ModelVersion))
                    ).scalar() or 0
                duration = (datetime.utcnow() - t0).total_seconds() * 1000
                if count > 0:
                    return self._record(
                        "model_trained",
                        "pass",
                        f"Models directory not found, but {count} model version(s) in DB",
                        duration,
                        {"db_versions": count},
                    )
                return self._record(
                    "model_trained",
                    "fail",
                    f"Models directory not found: {models_dir}",
                    duration,
                )

            files = [f for f in models_dir.rglob("*") if f.is_file()]
            duration = (datetime.utcnow() - t0).total_seconds() * 1000

            if not files:
                return self._record(
                    "model_trained",
                    "fail",
                    "Models directory exists but contains no files",
                    duration,
                    {"dir": str(models_dir)},
                )
            return self._record(
                "model_trained",
                "pass",
                f"Found {len(files)} file(s) in models_store",
                duration,
                {"dir": str(models_dir), "files": len(files)},
            )
        except Exception as exc:
            duration = (datetime.utcnow() - t0).total_seconds() * 1000
            return self._record("model_trained", "fail", str(exc), duration)

    async def check_backtest_trades(self) -> SmokeCheckResult:
        """Verify backtest_runs have associated trades."""
        t0 = datetime.utcnow()
        try:
            async with await self._get_db() as db:
                run_count = (
                    await db.execute(select(func.count()).select_from(BacktestRun))
                ).scalar() or 0

                trade_count = (
                    await db.execute(select(func.count()).select_from(BacktestTrade))
                ).scalar() or 0

                runs_with_trades = (
                    await db.execute(
                        select(func.count(func.distinct(BacktestTrade.backtest_run_id)))
                    )
                ).scalar() or 0

            duration = (datetime.utcnow() - t0).total_seconds() * 1000

            if run_count == 0:
                return self._record(
                    "backtest_trades",
                    "fail",
                    "No backtest runs found",
                    duration,
                    {"runs": 0},
                )
            if trade_count == 0:
                return self._record(
                    "backtest_trades",
                    "warn",
                    f"{run_count} backtest runs but zero trades",
                    duration,
                    {"runs": run_count, "trades": 0},
                )
            return self._record(
                "backtest_trades",
                "pass",
                f"{run_count} runs, {trade_count} trades across {runs_with_trades} runs",
                duration,
                {"runs": run_count, "trades": trade_count, "runs_with_trades": runs_with_trades},
            )
        except Exception as exc:
            duration = (datetime.utcnow() - t0).total_seconds() * 1000
            return self._record("backtest_trades", "fail", str(exc), duration)

    async def check_weekly_predictions(self) -> SmokeCheckResult:
        """Verify weekly_predictions table has rows."""
        t0 = datetime.utcnow()
        try:
            async with await self._get_db() as db:
                total = (
                    await db.execute(select(func.count()).select_from(WeeklyPrediction))
                ).scalar() or 0

                latest_week = (
                    await db.execute(select(func.max(WeeklyPrediction.week_starting)))
                ).scalar()

                distinct_strategies = (
                    await db.execute(
                        select(func.count(func.distinct(WeeklyPrediction.strategy_id)))
                    )
                ).scalar() or 0

            duration = (datetime.utcnow() - t0).total_seconds() * 1000

            if total == 0:
                return self._record(
                    "weekly_predictions",
                    "fail",
                    "No weekly predictions found",
                    duration,
                    {"total": 0},
                )
            return self._record(
                "weekly_predictions",
                "pass",
                f"{total} predictions from {distinct_strategies} strategy(ies), latest week {latest_week}",
                duration,
                {"total": total, "latest_week": str(latest_week) if latest_week else None, "strategies": distinct_strategies},
            )
        except Exception as exc:
            duration = (datetime.utcnow() - t0).total_seconds() * 1000
            return self._record("weekly_predictions", "fail", str(exc), duration)

    async def check_api_endpoints(self) -> SmokeCheckResult:
        """Verify key API endpoints respond successfully."""
        t0 = datetime.utcnow()
        endpoints = {
            "health": "/health",
            "stocks": "/stocks",
            "data_quality": "/data-quality",
        }
        results: dict[str, Any] = {}
        all_ok = True

        async with httpx.AsyncClient(base_url=self.base_url, timeout=10.0) as client:
            for name, path in endpoints.items():
                try:
                    resp = await client.get(path)
                    results[name] = {"status_code": resp.status_code, "ok": resp.status_code == 200}
                    if resp.status_code != 200:
                        all_ok = False
                except Exception as exc:
                    results[name] = {"error": str(exc)}
                    all_ok = False

        duration = (datetime.utcnow() - t0).total_seconds() * 1000

        if all_ok:
            return self._record(
                "api_endpoints",
                "pass",
                f"All {len(endpoints)} endpoints responded OK",
                duration,
                results,
            )
        return self._record(
            "api_endpoints",
            "fail",
            "One or more endpoints failed",
            duration,
            results,
        )

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    async def run_full_smoke_test(self) -> SmokeTestReport:
        """Run all checks and return a consolidated report."""
        self._results.clear()
        started_at = datetime.utcnow()
        logger.info("[smoke] Starting full smoke test at %s", started_at.isoformat())

        checks = [
            self.check_stocks_in_db,
            self.check_prices_daily,
            self.check_prices_weekly,
            self.check_features,
            self.check_labels,
            self.check_model_trained,
            self.check_backtest_trades,
            self.check_weekly_predictions,
            self.check_api_endpoints,
        ]

        for check in checks:
            try:
                await check()
            except Exception as exc:
                logger.exception("[smoke] Unexpected error in %s", check.__name__)
                self._record(check.__name__, "fail", f"Unhandled exception: {exc}")

        finished_at = datetime.utcnow()
        summary = {"pass": 0, "fail": 0, "warn": 0, "skip": 0}
        for r in self._results:
            summary[r.status] = summary.get(r.status, 0) + 1

        overall = "pass"
        if summary.get("fail", 0) > 0:
            overall = "fail"
        elif summary.get("warn", 0) > 0:
            overall = "warn"

        logger.info(
            "[smoke] Finished in %.2f ms — overall: %s",
            (finished_at - started_at).total_seconds() * 1000,
            overall,
        )

        return SmokeTestReport(
            overall=overall,
            started_at=started_at,
            finished_at=finished_at,
            checks=list(self._results),
            summary=summary,
        )


# Convenience sync wrapper for CLI / scripting
def run_smoke_test_sync(base_url: str = "http://localhost:8000") -> SmokeTestReport:
    runner = SmokeTestRunner(base_url=base_url)
    return asyncio.run(runner.run_full_smoke_test())
