from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock import Stock, CorporateAction
from app.models.price import PriceDaily, PriceWeekly
from app.models.feature import FeatureWeekly
from app.models.financial import FinancialMetric
from app.models.news import NewsArticle, NewsAnalysis
from app.models.macro import MacroIndicator
from app.models.data_quality_score import DataQualityScore


class DataQualityScorer:
    """Computes per-stock per-week data quality scores (0-100)."""

    # Weights for overall score
    WEIGHTS = {
        "price": 0.30,
        "feature": 0.25,
        "financial": 0.20,
        "news": 0.15,
        "macro": 0.10,
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
        return max(low, min(high, value))

    @staticmethod
    def _flag(score: float) -> str:
        return "poor_quality" if score < 50 else "ok"

    # ------------------------------------------------------------------
    # Price score
    # ------------------------------------------------------------------
    async def compute_price_score(self, stock_id: int, week: date) -> tuple[float, dict[str, Any]]:
        """Check missing prices, volume anomalies, and split/dividend errors."""
        details: dict[str, Any] = {}

        # --- missing weekly prices in the last 52 weeks ---
        year_ago = week - timedelta(days=364)
        weekly_count = (
            await self.db.execute(
                select(func.count()).where(
                    and_(
                        PriceWeekly.stock_id == stock_id,
                        PriceWeekly.week_ending >= year_ago,
                        PriceWeekly.week_ending <= week,
                    )
                )
            )
        ).scalar() or 0
        expected_weeks = 52
        missing_weeks = max(0, expected_weeks - weekly_count)
        missing_penalty = min(100, missing_weeks * 5)  # 5 pts per missing week

        # --- missing daily prices in the target week ---
        week_start = week - timedelta(days=6)
        daily_count = (
            await self.db.execute(
                select(func.count()).where(
                    and_(
                        PriceDaily.stock_id == stock_id,
                        PriceDaily.date >= week_start,
                        PriceDaily.date <= week,
                    )
                )
            )
        ).scalar() or 0
        expected_days = 5
        missing_days = max(0, expected_days - daily_count)
        daily_penalty = missing_days * 10  # 10 pts per missing day

        # --- volume anomaly: zero or extremely low volume vs median ---
        vol_stats = (
            await self.db.execute(
                select(func.avg(PriceDaily.volume).label("avg_vol"), func.max(PriceDaily.volume).label("max_vol"))
                .where(
                    and_(
                        PriceDaily.stock_id == stock_id,
                        PriceDaily.date >= year_ago,
                        PriceDaily.date <= week,
                    )
                )
            )
        ).one_or_none()
        avg_vol = vol_stats.avg_vol if vol_stats and vol_stats.avg_vol else 0.0
        max_vol = vol_stats.max_vol if vol_stats and vol_stats.max_vol else 0.0

        zero_vol_days = (
            await self.db.execute(
                select(func.count()).where(
                    and_(
                        PriceDaily.stock_id == stock_id,
                        PriceDaily.date >= week_start,
                        PriceDaily.date <= week,
                        or_(PriceDaily.volume == 0, PriceDaily.volume.is_(None)),
                    )
                )
            )
        ).scalar() or 0
        vol_penalty = zero_vol_days * 8  # 8 pts per zero-volume day

        # --- split / dividend error check via corporate actions ---
        ca_count = (
            await self.db.execute(
                select(func.count()).where(
                    and_(
                        CorporateAction.stock_id == stock_id,
                        CorporateAction.action_date >= week_start,
                        CorporateAction.action_date <= week,
                        CorporateAction.action_type.in_(["split", "dividend"]),
                    )
                )
            )
        ).scalar() or 0
        # Presence of corporate actions is neutral; we flag if price gap is suspicious
        suspicious_gap = False
        if daily_count >= 2:
            prices = (
                await self.db.execute(
                    select(PriceDaily.close)
                    .where(
                        and_(
                            PriceDaily.stock_id == stock_id,
                            PriceDaily.date >= week_start,
                            PriceDaily.date <= week,
                            PriceDaily.close.isnot(None),
                        )
                    )
                    .order_by(PriceDaily.date)
                )
            ).scalars().all()
            if len(prices) >= 2:
                for i in range(1, len(prices)):
                    if prices[i - 1] and prices[i - 1] > 0:
                        change = abs(prices[i] - prices[i - 1]) / prices[i - 1]
                        if change > 0.30 and ca_count == 0:
                            suspicious_gap = True
                            break
        gap_penalty = 15 if suspicious_gap else 0

        score = self._clamp(100.0 - missing_penalty - daily_penalty - vol_penalty - gap_penalty)

        details["missing_weeks_52w"] = missing_weeks
        details["missing_days_week"] = missing_days
        details["zero_volume_days"] = zero_vol_days
        details["avg_volume_52w"] = round(avg_vol, 2) if avg_vol else None
        details["max_volume_52w"] = round(max_vol, 2) if max_vol else None
        details["suspicious_gap_no_ca"] = suspicious_gap
        details["penalties"] = {
            "missing_weeks": missing_penalty,
            "missing_days": daily_penalty,
            "volume": vol_penalty,
            "gap": gap_penalty,
        }
        return score, details

    # ------------------------------------------------------------------
    # Feature score
    # ------------------------------------------------------------------
    async def compute_feature_score(self, stock_id: int, week: date) -> tuple[float, dict[str, Any]]:
        """Check NaN ratio and outlier count in features for the week."""
        details: dict[str, Any] = {}

        rows = (
            await self.db.execute(
                select(FeatureWeekly.value).where(
                    and_(
                        FeatureWeekly.stock_id == stock_id,
                        FeatureWeekly.week_ending == week,
                    )
                )
            )
        ).scalars().all()

        total = len(rows)
        if total == 0:
            return 0.0, {"total_features": 0, "nan_count": 0, "outlier_count": 0, "note": "no_features"}

        nan_count = sum(1 for v in rows if v is None or (isinstance(v, float) and math.isnan(v)))
        nan_ratio = nan_count / total

        # Outliers: values beyond 5 std of the week's feature distribution
        valid = [v for v in rows if v is not None and not (isinstance(v, float) and math.isnan(v))]
        outlier_count = 0
        if len(valid) >= 2:
            mean = sum(valid) / len(valid)
            variance = sum((x - mean) ** 2 for x in valid) / len(valid)
            std = math.sqrt(variance)
            if std > 0:
                outlier_count = sum(1 for x in valid if abs(x - mean) > 5 * std)

        nan_penalty = nan_ratio * 60  # up to 60 pts
        outlier_penalty = min(20, outlier_count * 2)

        score = self._clamp(100.0 - nan_penalty - outlier_penalty)

        details["total_features"] = total
        details["nan_count"] = nan_count
        details["nan_ratio"] = round(nan_ratio, 4)
        details["outlier_count"] = outlier_count
        details["penalties"] = {
            "nan": round(nan_penalty, 2),
            "outliers": outlier_penalty,
        }
        return score, details

    # ------------------------------------------------------------------
    # Financial score
    # ------------------------------------------------------------------
    async def compute_financial_score(self, stock_id: int, week: date) -> tuple[float, dict[str, Any]]:
        """Check data freshness and as_of_date validity."""
        details: dict[str, Any] = {}

        # Count financial metrics for this stock
        total_metrics = (
            await self.db.execute(
                select(func.count()).where(FinancialMetric.stock_id == stock_id)
            )
        ).scalar() or 0

        if total_metrics == 0:
            return 0.0, {"total_metrics": 0, "note": "no_financial_data"}

        # Metrics with valid as_of_date
        with_as_of = (
            await self.db.execute(
                select(func.count()).where(
                    and_(
                        FinancialMetric.stock_id == stock_id,
                        FinancialMetric.as_of_date.isnot(None),
                    )
                )
            )
        ).scalar() or 0

        as_of_ratio = with_as_of / total_metrics if total_metrics else 0.0

        # Latest as_of_date
        latest_as_of = (
            await self.db.execute(
                select(func.max(FinancialMetric.as_of_date)).where(
                    FinancialMetric.stock_id == stock_id
                )
            )
        ).scalar()

        freshness_penalty = 0.0
        if latest_as_of is None:
            freshness_penalty = 30.0
        else:
            days_old = (week - latest_as_of).days
            if days_old > 180:
                freshness_penalty = 30.0
            elif days_old > 90:
                freshness_penalty = 15.0
            elif days_old > 30:
                freshness_penalty = 5.0

        as_of_penalty = (1.0 - as_of_ratio) * 40  # up to 40 pts if none have as_of

        score = self._clamp(100.0 - freshness_penalty - as_of_penalty)

        details["total_metrics"] = total_metrics
        details["with_as_of_date"] = with_as_of
        details["as_of_ratio"] = round(as_of_ratio, 4)
        details["latest_as_of_date"] = str(latest_as_of) if latest_as_of else None
        details["days_old"] = (week - latest_as_of).days if latest_as_of else None
        details["penalties"] = {
            "freshness": freshness_penalty,
            "as_of_coverage": round(as_of_penalty, 2),
        }
        return score, details

    # ------------------------------------------------------------------
    # News score
    # ------------------------------------------------------------------
    async def compute_news_score(self, stock_id: int, week: date) -> tuple[float, dict[str, Any]]:
        """Check news age and volume for the week."""
        details: dict[str, Any] = {}

        week_start_dt = datetime.combine(week - timedelta(days=6), datetime.min.time())
        week_end_dt = datetime.combine(week, datetime.max.time())

        # Count news analyses for this stock in the week
        news_count = (
            await self.db.execute(
                select(func.count(NewsAnalysis.id))
                .join(NewsArticle, NewsAnalysis.news_id == NewsArticle.id)
                .where(
                    and_(
                        NewsAnalysis.stock_id == stock_id,
                        NewsArticle.published_at >= week_start_dt,
                        NewsArticle.published_at <= week_end_dt,
                    )
                )
            )
        ).scalar() or 0

        if news_count == 0:
            # No news is not necessarily bad — check for older news
            older_count = (
                await self.db.execute(
                    select(func.count(NewsAnalysis.id))
                    .join(NewsArticle, NewsAnalysis.news_id == NewsArticle.id)
                    .where(
                        and_(
                            NewsAnalysis.stock_id == stock_id,
                            NewsArticle.published_at <= week_end_dt,
                        )
                    )
                )
            ).scalar() or 0
            if older_count == 0:
                return 50.0, {"news_count": 0, "note": "no_news_ever"}
            return 70.0, {"news_count": 0, "note": "no_news_this_week"}

        # Average age of news in the week
        avg_age_days = (
            await self.db.execute(
                select(
                    func.avg(
                        func.extract("epoch", week_end_dt - NewsArticle.published_at) / 86400
                    )
                )
                .join(NewsAnalysis, NewsAnalysis.news_id == NewsArticle.id)
                .where(
                    and_(
                        NewsAnalysis.stock_id == stock_id,
                        NewsArticle.published_at >= week_start_dt,
                        NewsArticle.published_at <= week_end_dt,
                    )
                )
            )
        ).scalar()
        avg_age_days = float(avg_age_days) if avg_age_days else 7.0

        # Penalize if news is very old on average (>5 days)
        age_penalty = max(0, (avg_age_days - 3.5)) * 3  # linear penalty after 3.5 days
        volume_bonus = min(10, news_count * 0.5)  # small bonus for volume

        score = self._clamp(100.0 - age_penalty + volume_bonus)

        details["news_count"] = news_count
        details["avg_age_days"] = round(avg_age_days, 2)
        details["penalties"] = {"age": round(age_penalty, 2)}
        details["bonuses"] = {"volume": round(volume_bonus, 2)}
        return score, details

    # ------------------------------------------------------------------
    # Macro score
    # ------------------------------------------------------------------
    async def compute_macro_score(self, week: date) -> tuple[float, dict[str, Any]]:
        """Check macro data completeness for the week."""
        details: dict[str, Any] = {}

        expected_indicators = {
            "VIX",
            "TNX_10Y",
            "SP500",
            "NASDAQ",
            "FED_RATE",
            "CPI_YOY",
            "YIELD_CURVE",
            "CREDIT_SPREAD_BBB",
            "OECD_CLI_USA",
        }
        week_start = week - timedelta(days=6)

        present = (
            await self.db.execute(
                select(MacroIndicator.indicator_code)
                .where(
                    and_(
                        MacroIndicator.date >= week_start,
                        MacroIndicator.date <= week,
                    )
                )
                .distinct()
            )
        ).scalars().all()
        present_set = set(present)

        missing = expected_indicators - present_set
        missing_penalty = len(missing) * 15  # 15 pts per missing indicator

        # Check latest available date for each indicator
        latest_rows = (
            await self.db.execute(
                select(MacroIndicator.indicator_code, func.max(MacroIndicator.date).label("latest"))
                .group_by(MacroIndicator.indicator_code)
            )
        ).all()
        latest_map = {r.indicator_code: r.latest for r in latest_rows}

        stale_count = 0
        for code, latest in latest_map.items():
            if latest and (week - latest).days > 30:
                stale_count += 1
        stale_penalty = stale_count * 5

        score = self._clamp(100.0 - missing_penalty - stale_penalty)

        details["expected_indicators"] = sorted(expected_indicators)
        details["present_indicators"] = sorted(present_set)
        details["missing_indicators"] = sorted(missing)
        details["latest_by_indicator"] = {k: str(v) for k, v in latest_map.items()}
        details["penalties"] = {
            "missing": missing_penalty,
            "stale": stale_penalty,
        }
        return score, details

    # ------------------------------------------------------------------
    # Overall score
    # ------------------------------------------------------------------
    def compute_overall_score(
        self,
        price_score: float,
        feature_score: float,
        financial_score: float,
        news_score: float,
        macro_score: float,
    ) -> float:
        """Weighted average of all scores (0-100)."""
        overall = (
            price_score * self.WEIGHTS["price"]
            + feature_score * self.WEIGHTS["feature"]
            + financial_score * self.WEIGHTS["financial"]
            + news_score * self.WEIGHTS["news"]
            + macro_score * self.WEIGHTS["macro"]
        )
        return self._clamp(overall)

    # ------------------------------------------------------------------
    # Single stock scoring
    # ------------------------------------------------------------------
    async def score_stock(self, stock_id: int, week: date) -> DataQualityScore:
        """Compute and return a full DataQualityScore row (not committed)."""
        price_score, price_details = await self.compute_price_score(stock_id, week)
        feature_score, feature_details = await self.compute_feature_score(stock_id, week)
        financial_score, financial_details = await self.compute_financial_score(stock_id, week)
        news_score, news_details = await self.compute_news_score(stock_id, week)
        macro_score, macro_details = await self.compute_macro_score(week)

        overall = self.compute_overall_score(
            price_score, feature_score, financial_score, news_score, macro_score
        )

        details = {
            "price": price_details,
            "feature": feature_details,
            "financial": financial_details,
            "news": news_details,
            "macro": macro_details,
            "flag": self._flag(overall),
        }

        return DataQualityScore(
            stock_id=stock_id,
            week_ending=week,
            overall_score=round(overall, 2),
            price_score=round(price_score, 2),
            feature_score=round(feature_score, 2),
            financial_score=round(financial_score, 2),
            news_score=round(news_score, 2),
            macro_score=round(macro_score, 2),
            details=details,
        )

    # ------------------------------------------------------------------
    # Batch scoring
    # ------------------------------------------------------------------
    async def score_all_stocks_for_week(self, week: date) -> list[DataQualityScore]:
        """Batch score all active stocks for a given week and persist results."""
        stocks = (
            await self.db.execute(select(Stock).where(Stock.is_active == True))
        ).scalars().all()

        results: list[DataQualityScore] = []
        for stock in stocks:
            score_row = await self.score_stock(stock.id, week)
            results.append(score_row)
            await self.db.merge(score_row)

        await self.db.commit()
        return results


import logging as _dqs_log
_dqs_logger = _dqs_log.getLogger(__name__)


class DataQualityScorerSync:
    """Sync wrapper for DataQualityScorer — use in Celery tasks (not async context)."""

    def __init__(self, session):
        self.session = session

    def score_stock_sync(self, stock_id: int, week: date) -> dict:
        from app.models.price import PriceDaily, PriceWeekly
        from app.models.feature import FeatureWeekly

        year_ago = week - timedelta(days=364)
        week_start = week - timedelta(days=6)

        weekly_count = self.session.execute(
            select(func.count()).where(
                PriceWeekly.stock_id == stock_id,
                PriceWeekly.week_ending >= year_ago,
                PriceWeekly.week_ending <= week,
            )
        ).scalar() or 0

        daily_count = self.session.execute(
            select(func.count()).where(
                PriceDaily.stock_id == stock_id,
                PriceDaily.date >= week_start,
                PriceDaily.date <= week,
            )
        ).scalar() or 0

        missing_weeks = max(0, 52 - weekly_count)
        missing_days = max(0, 5 - daily_count)
        price_score = max(0.0, 100.0 - missing_weeks * 5 - missing_days * 10)

        feat_rows = self.session.execute(
            select(FeatureWeekly.value).where(
                FeatureWeekly.stock_id == stock_id,
                FeatureWeekly.week_ending == week,
            )
        ).scalars().all()

        total_feat = len(feat_rows)
        if total_feat == 0:
            feature_score = 0.0
        else:
            nan_count = sum(
                1 for v in feat_rows
                if v is None or (isinstance(v, float) and math.isnan(v))
            )
            feature_score = max(0.0, 100.0 - (nan_count / total_feat) * 60)

        overall = price_score * 0.40 + feature_score * 0.35 + 70.0 * 0.25

        return {
            "stock_id": stock_id,
            "week_ending": str(week),
            "overall_score": round(overall, 2),
            "price_score": round(price_score, 2),
            "feature_score": round(feature_score, 2),
            "flag": "poor_quality" if overall < 50 else "ok",
        }

    def score_all_stocks_sync(self, week: date, min_score: float = 50.0) -> dict:
        from app.models.stock import Stock

        stocks = self.session.execute(
            select(Stock).where(Stock.is_active == True)
        ).scalars().all()

        results = []
        poor_quality = []
        for stock in stocks:
            score = self.score_stock_sync(stock.id, week)
            results.append(score)
            if score["overall_score"] < min_score:
                poor_quality.append(stock.ticker)

        _dqs_logger.info(
            "Data quality scoring: %d hisse, %d poor quality (<%d)",
            len(results), len(poor_quality), min_score,
        )
        return {
            "week": str(week),
            "total_scored": len(results),
            "poor_quality_tickers": poor_quality,
            "scores": results,
        }
