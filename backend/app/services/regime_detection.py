"""
Market Regime Detection Engine.

Classifies each week into a market regime using:
- SPY vs 200-day moving average (trend)
- VIX level and weekly change (volatility / risk sentiment)
- Nasdaq / SPY ratio (growth vs value / risk-on vs risk-off)
- Market breadth proxy (advancing vs declining participation)
- 10Y yield trend (rates regime)
- Sector rotation dispersion (sector performance dispersion)
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Sequence

import numpy as np
import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models.macro import MacroIndicator
from app.models.price import PriceDaily, PriceWeekly
from app.models.regime import MarketRegime
from app.models.stock import Stock
from app.models.backtest import WalkForwardResult

logger = logging.getLogger(__name__)

SPY_TICKER = "SPY"
QQQ_TICKER = "QQQ"  # Nasdaq proxy
TNX_CODE = "TNX_10Y"
VIX_CODE = "VIX"

SECTOR_CODES = [
    "SECTOR_XLK",
    "SECTOR_XLF",
    "SECTOR_XLE",
    "SECTOR_XLV",
    "SECTOR_XLI",
    "SECTOR_XLP",
    "SECTOR_XLY",
    "SECTOR_XLU",
    "SECTOR_XLRE",
    "SECTOR_XLB",
]


class RegimeDetector:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_regime_for_week(self, week_ending: date) -> MarketRegime | None:
        """Analyze all indicators for the week ending on *week_ending* and persist."""
        spy_200ma = self.compute_spy_200ma_ratio(week_ending)
        vix_level, vix_change = self.compute_vix_regime(week_ending)
        nasdaq_spy = self.compute_nasdaq_spy_ratio(week_ending)
        breadth = self.compute_market_breadth(week_ending)
        yield_trend = self.compute_yield_trend(week_ending)
        sector_rot = self.compute_sector_rotation(week_ending)

        regime, confidence = self.classify_regime(
            spy_200ma_ratio=spy_200ma,
            vix_level=vix_level,
            vix_change=vix_change,
            nasdaq_spy_ratio=nasdaq_spy,
            market_breadth=breadth,
            yield_trend=yield_trend,
            sector_rotation_score=sector_rot,
        )

        week_starting = week_ending - timedelta(days=4)
        mr = MarketRegime(
            week_starting=week_starting,
            week_ending=week_ending,
            regime_type=regime,
            spy_200ma_ratio=round(spy_200ma, 4) if spy_200ma is not None else None,
            vix_level=round(vix_level, 4) if vix_level is not None else None,
            vix_change=round(vix_change, 4) if vix_change is not None else None,
            nasdaq_spy_ratio=round(nasdaq_spy, 4) if nasdaq_spy is not None else None,
            market_breadth=round(breadth, 4) if breadth is not None else None,
            yield_trend=round(yield_trend, 4) if yield_trend is not None else None,
            sector_rotation_score=round(sector_rot, 4) if sector_rot is not None else None,
            confidence=round(confidence, 4),
        )
        self.session.add(mr)
        self.session.commit()
        logger.info(f"Detected regime {regime} for week {week_ending} (confidence={confidence:.2f})")
        return mr

    def get_regime_for_period(
        self, start: date, end: date
    ) -> list[MarketRegime]:
        """Return persisted regimes for a date range, ordered chronologically."""
        rows = self.session.execute(
            select(MarketRegime)
            .where(MarketRegime.week_ending >= start, MarketRegime.week_ending <= end)
            .order_by(MarketRegime.week_ending)
        ).scalars().all()
        return list(rows)

    def analyze_strategy_by_regime(self, strategy_id: int) -> dict:
        """Return strategy walk-forward performance segmented by regime type."""
        folds = self.session.execute(
            select(WalkForwardResult)
            .where(WalkForwardResult.strategy_id == strategy_id)
            .order_by(WalkForwardResult.fold)
        ).scalars().all()
        if not folds:
            return {"strategy_id": strategy_id, "regimes": {}}

        # Build regime map keyed by week_ending
        regime_rows = self.session.execute(
            select(MarketRegime).order_by(MarketRegime.week_ending)
        ).scalars().all()
        regime_map = {r.week_ending: r.regime_type for r in regime_rows}

        buckets: dict[str, list[dict]] = {}
        for fold in folds:
            # Assign fold to the regime of its test_end week
            reg = regime_map.get(fold.test_end, "unknown")
            buckets.setdefault(reg, []).append({
                "fold": fold.fold,
                "test_start": str(fold.test_start),
                "test_end": str(fold.test_end),
                **{k: v for k, v in (fold.metrics or {}).items()},
            })

        summary = {}
        for reg, items in buckets.items():
            sharpes = [i.get("sharpe", 0) for i in items if i.get("sharpe") is not None]
            summary[reg] = {
                "n_folds": len(items),
                "avg_sharpe": round(float(np.mean(sharpes)), 4) if sharpes else None,
                "folds": items,
            }
        return {"strategy_id": strategy_id, "regimes": summary}

    # ------------------------------------------------------------------
    # Indicator computations
    # ------------------------------------------------------------------

    def compute_spy_200ma_ratio(self, as_of: date) -> float | None:
        """SPY close vs its 200-day simple moving average."""
        spy = self._get_stock_id(SPY_TICKER)
        if not spy:
            return None
        start = as_of - timedelta(days=300)
        rows = self.session.execute(
            select(PriceDaily)
            .where(
                PriceDaily.stock_id == spy,
                PriceDaily.date >= start,
                PriceDaily.date <= as_of,
            )
            .order_by(PriceDaily.date)
        ).scalars().all()
        if len(rows) < 200:
            return None
        closes = pd.Series([r.close for r in rows if r.close is not None])
        if closes.empty or len(closes) < 200:
            return None
        ma200 = closes.rolling(200).mean().iloc[-1]
        latest = closes.iloc[-1]
        return float(latest / ma200) if ma200 and ma200 > 0 else None

    def compute_vix_regime(self, as_of: date) -> tuple[float | None, float | None]:
        """Return (latest VIX level, weekly pct change)."""
        rows = self.session.execute(
            select(MacroIndicator)
            .where(MacroIndicator.indicator_code == VIX_CODE, MacroIndicator.date <= as_of)
            .order_by(MacroIndicator.date.desc())
            .limit(10)
        ).scalars().all()
        if not rows:
            return None, None
        df = pd.DataFrame([{"date": r.date, "vix": r.value} for r in rows])
        df = df.sort_values("date")
        level = df["vix"].iloc[-1]
        if len(df) >= 2:
            prev = df["vix"].iloc[-2]
            change = float((level - prev) / prev) if prev and prev != 0 else None
        else:
            change = None
        return (float(level) if level is not None else None), change

    def compute_nasdaq_spy_ratio(self, as_of: date) -> float | None:
        """QQQ / SPY ratio — proxy for growth/risk-on vs value/risk-off."""
        spy_id = self._get_stock_id(SPY_TICKER)
        qqq_id = self._get_stock_id(QQQ_TICKER)
        if not spy_id or not qqq_id:
            return None
        spy_price = self._latest_close(spy_id, as_of)
        qqq_price = self._latest_close(qqq_id, as_of)
        if spy_price and spy_price > 0 and qqq_price:
            return float(qqq_price / spy_price)
        return None

    def compute_market_breadth(self, as_of: date) -> float | None:
        """Proxy: fraction of MVP stocks above their 20-week MA."""
        from app.config import settings
        tickers = settings.mvp_tickers
        total = 0
        above = 0
        for ticker in tickers:
            stock_id = self._get_stock_id(ticker)
            if not stock_id:
                continue
            start = as_of - timedelta(days=180)
            rows = self.session.execute(
                select(PriceWeekly)
                .where(
                    PriceWeekly.stock_id == stock_id,
                    PriceWeekly.week_ending >= start,
                    PriceWeekly.week_ending <= as_of,
                )
                .order_by(PriceWeekly.week_ending)
            ).scalars().all()
            closes = [r.close for r in rows if r.close is not None]
            if len(closes) < 10:
                continue
            total += 1
            ma20 = sum(closes[-20:]) / min(20, len(closes))
            if closes[-1] > ma20:
                above += 1
        return float(above / total) if total > 0 else None

    def compute_yield_trend(self, as_of: date) -> float | None:
        """10Y yield 20-week pct change."""
        rows = self.session.execute(
            select(MacroIndicator)
            .where(MacroIndicator.indicator_code == TNX_CODE, MacroIndicator.date <= as_of)
            .order_by(MacroIndicator.date.desc())
            .limit(30)
        ).scalars().all()
        if len(rows) < 10:
            return None
        df = pd.DataFrame([{"date": r.date, "yield": r.value} for r in rows])
        df = df.sort_values("date")
        weekly = df.set_index("date").resample("W-FRI").last()["yield"].dropna()
        if len(weekly) < 5:
            return None
        latest = weekly.iloc[-1]
        prev = weekly.iloc[-5] if len(weekly) >= 5 else weekly.iloc[0]
        if prev and prev != 0:
            return float((latest - prev) / prev)
        return None

    def compute_sector_rotation(self, as_of: date) -> float | None:
        """Sector performance dispersion: std of 4-week returns across sector ETFs."""
        returns = []
        for code in SECTOR_CODES:
            ret = self._sector_4w_return(code, as_of)
            if ret is not None:
                returns.append(ret)
        if len(returns) < 4:
            return None
        return float(np.std(returns))

    def classify_regime(
        self,
        spy_200ma_ratio: float | None,
        vix_level: float | None,
        vix_change: float | None,
        nasdaq_spy_ratio: float | None,
        market_breadth: float | None,
        yield_trend: float | None,
        sector_rotation_score: float | None,
    ) -> tuple[str, float]:
        """Classify regime and return confidence score (0-1)."""
        scores: dict[str, float] = {
            "bull": 0.0,
            "bear": 0.0,
            "sideways": 0.0,
            "high_vol": 0.0,
            "low_vol": 0.0,
            "risk_on": 0.0,
            "risk_off": 0.0,
        }

        # Trend
        if spy_200ma_ratio is not None:
            if spy_200ma_ratio > 1.05:
                scores["bull"] += 0.25
                scores["risk_on"] += 0.10
            elif spy_200ma_ratio < 0.95:
                scores["bear"] += 0.25
                scores["risk_off"] += 0.10
            else:
                scores["sideways"] += 0.20

        # VIX level
        if vix_level is not None:
            if vix_level > 25:
                scores["high_vol"] += 0.25
                scores["risk_off"] += 0.15
            elif vix_level < 15:
                scores["low_vol"] += 0.20
                scores["risk_on"] += 0.10
            else:
                scores["sideways"] += 0.10

        # VIX change
        if vix_change is not None:
            if vix_change > 0.20:
                scores["high_vol"] += 0.15
                scores["risk_off"] += 0.10
            elif vix_change < -0.15:
                scores["low_vol"] += 0.10
                scores["risk_on"] += 0.05

        # Nasdaq/SPY
        if nasdaq_spy_ratio is not None:
            # Use 20-week baseline — simplistic: just compare to 1.0 scaled
            if nasdaq_spy_ratio > 1.0:
                scores["risk_on"] += 0.15
                scores["bull"] += 0.05
            else:
                scores["risk_off"] += 0.15
                scores["bear"] += 0.05

        # Breadth
        if market_breadth is not None:
            if market_breadth > 0.65:
                scores["bull"] += 0.15
            elif market_breadth < 0.35:
                scores["bear"] += 0.15
            else:
                scores["sideways"] += 0.10

        # Yield trend
        if yield_trend is not None:
            if yield_trend > 0.10:
                scores["risk_off"] += 0.10
            elif yield_trend < -0.10:
                scores["risk_on"] += 0.10

        # Sector rotation
        if sector_rotation_score is not None:
            if sector_rotation_score > 0.05:
                scores["high_vol"] += 0.10
            else:
                scores["low_vol"] += 0.05

        # Pick winner
        best_regime = max(scores, key=scores.get)  # type: ignore[arg-type]
        best_score = scores[best_regime]
        total = sum(scores.values()) or 1.0
        confidence = best_score / total
        return best_regime, confidence

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_stock_id(self, ticker: str) -> int | None:
        stock = self.session.execute(
            select(Stock).where(Stock.ticker == ticker)
        ).scalars().first()
        return stock.id if stock else None

    def _latest_close(self, stock_id: int, as_of: date) -> float | None:
        row = self.session.execute(
            select(PriceDaily)
            .where(PriceDaily.stock_id == stock_id, PriceDaily.date <= as_of)
            .order_by(PriceDaily.date.desc())
            .limit(1)
        ).scalars().first()
        return row.close if row else None

    def _sector_4w_return(self, indicator_code: str, as_of: date) -> float | None:
        rows = self.session.execute(
            select(MacroIndicator)
            .where(
                MacroIndicator.indicator_code == indicator_code,
                MacroIndicator.date <= as_of,
            )
            .order_by(MacroIndicator.date.desc())
            .limit(30)
        ).scalars().all()
        if len(rows) < 5:
            return None
        df = pd.DataFrame([{"date": r.date, "val": r.value} for r in rows])
        df = df.sort_values("date")
        weekly = df.set_index("date").resample("W-FRI").last()["val"].dropna()
        if len(weekly) < 2:
            return None
        latest = weekly.iloc[-1]
        prev = weekly.iloc[-min(4, len(weekly) - 1)]
        if prev and prev != 0:
            return float((latest - prev) / prev)
        return None
