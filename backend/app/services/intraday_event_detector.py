"""
Intraday Spike / Crash Event Detector.

For each (stock, week) pair, detects whether an unusually large intraday move
occurred, attributes a probable cause (earnings, news, macro), records which
pipeline features changed most (before vs after), and trains a lightweight
spike predictor that feeds position-sizing back into the backtester.

Detection threshold: max intraday move >= SPIKE_THRESHOLD (default 4%)
Cause attribution priority: earnings > news spike > macro event > unknown
"""
from __future__ import annotations

import logging
import pickle
from datetime import date, timedelta
from typing import Sequence

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.intraday_event import IntradayEvent
from app.models.news import NewsArticle, NewsAnalysis
from app.models.price import PriceDaily, PriceWeekly
from app.models.macro import MacroIndicator
from app.models.stock import Stock

logger = logging.getLogger(__name__)

SPIKE_THRESHOLD = 0.04        # 4% intraday move = spike
FEATURE_DELTA_TOP_N = 10      # top N most-changed features to record
MIN_EVENTS_TO_TRAIN = 200     # minimum events before training spike predictor
PREDICTOR_CACHE_PATH = "models_store/spike_predictor.pkl"


class IntradayEventDetector:
    """Detect, record and learn from intraday spike / crash events."""

    def __init__(self, session: Session):
        self.session = session
        self._predictor: object | None = None  # cached trained model
        self._scaler: object | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_for_week(self, stock_id: int, week_ending: date) -> IntradayEvent | None:
        """Compute and upsert an IntradayEvent for one stock/week."""
        prices = self._load_week_prices(stock_id, week_ending)
        if prices.empty:
            return None

        metrics = self._compute_spike_metrics(prices)
        if metrics is None:
            return None

        causes = self._attribute_causes(stock_id, week_ending, prices)
        feature_delta = self._compute_feature_delta(stock_id, week_ending)

        vix_level, vix_change = self._get_vix(week_ending)
        actual_return = self._compute_actual_return(prices)

        # Upsert
        existing = self.session.execute(
            select(IntradayEvent).where(
                IntradayEvent.stock_id == stock_id,
                IntradayEvent.week_ending == week_ending,
            )
        ).scalars().first()

        if existing is None:
            event = IntradayEvent(stock_id=stock_id, week_ending=week_ending)
            self.session.add(event)
        else:
            event = existing

        event.max_intraday_up_pct = metrics["max_up"]
        event.max_intraday_down_pct = metrics["max_down"]
        event.high_low_range_pct = metrics["hl_range"]
        event.spike_type = metrics["spike_type"]
        event.spike_day = metrics["spike_day"]
        event.has_earnings = causes["has_earnings"]
        event.has_news_spike = causes["has_news_spike"]
        event.has_macro_event = causes["has_macro_event"]
        event.news_sentiment_delta = causes.get("news_sentiment_delta")
        event.vix_level = vix_level
        event.vix_change = vix_change
        event.feature_delta = feature_delta
        event.actual_return = actual_return

        self.session.flush()
        return event

    def run_for_tickers(self, tickers: list[str], weeks_back: int = 52) -> int:
        """Batch scan recent history for all tickers. Returns events recorded."""
        stocks = {
            s.ticker: s.id
            for s in self.session.execute(
                select(Stock).where(Stock.ticker.in_(tickers))
            ).scalars().all()
        }
        today = date.today()
        start_week = today - timedelta(weeks=weeks_back)

        # All Fridays in range
        friday = start_week
        while friday.weekday() != 4:
            friday += timedelta(days=1)
        fridays = []
        while friday <= today:
            fridays.append(friday)
            friday += timedelta(weeks=1)

        count = 0
        for ticker, stock_id in stocks.items():
            for week_end in fridays:
                try:
                    ev = self.run_for_week(stock_id, week_end)
                    if ev is not None:
                        count += 1
                except Exception as exc:
                    logger.warning("IntradayEventDetector: %s %s failed: %s", ticker, week_end, exc)

        self.session.commit()
        logger.info("IntradayEventDetector: recorded %d events for %d tickers", count, len(stocks))
        return count

    def train_spike_predictor(self) -> bool:
        """Train a LightGBM classifier: will this stock spike (>=SPIKE_THRESHOLD) this week?

        Returns True if training succeeded.
        """
        events = self.session.execute(
            select(IntradayEvent).where(IntradayEvent.actual_return.isnot(None))
        ).scalars().all()

        if len(events) < MIN_EVENTS_TO_TRAIN:
            logger.info(
                "Spike predictor: only %d events, need %d to train",
                len(events), MIN_EVENTS_TO_TRAIN,
            )
            return False

        rows = []
        for ev in events:
            up = ev.max_intraday_up_pct or 0.0
            down = ev.max_intraday_down_pct or 0.0
            label = 1 if max(up, down) >= SPIKE_THRESHOLD else 0
            rows.append({
                "max_up": up,
                "max_down": down,
                "has_earnings": int(ev.has_earnings),
                "has_news_spike": int(ev.has_news_spike),
                "has_macro_event": int(ev.has_macro_event),
                "news_sentiment_delta": ev.news_sentiment_delta or 0.0,
                "vix_level": ev.vix_level or 20.0,
                "vix_change": ev.vix_change or 0.0,
                "label": label,
            })

        df = pd.DataFrame(rows)
        feature_cols = [c for c in df.columns if c != "label"]
        X = df[feature_cols].fillna(0).values
        y = df["label"].values

        from sklearn.preprocessing import StandardScaler
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        try:
            import lightgbm as lgb
            model = lgb.LGBMClassifier(
                n_estimators=100, max_depth=3, num_leaves=7,
                learning_rate=0.05, random_state=42, verbose=-1,
                scale_pos_weight=(y == 0).sum() / max((y == 1).sum(), 1),
            )
        except ImportError:
            from sklearn.linear_model import LogisticRegression
            model = LogisticRegression(C=0.5, max_iter=500, random_state=42)

        model.fit(X_scaled, y)
        self._predictor = model
        self._scaler = scaler
        self._feature_cols = feature_cols

        import os
        os.makedirs("models_store", exist_ok=True)
        with open(PREDICTOR_CACHE_PATH, "wb") as f:
            pickle.dump({"model": model, "scaler": scaler, "feature_cols": feature_cols}, f)

        pos_count = y.sum()
        logger.info(
            "Spike predictor trained on %d events (%d spikes, %.1f%%). Saved to %s",
            len(rows), pos_count, 100 * pos_count / len(rows), PREDICTOR_CACHE_PATH,
        )
        return True

    def load_spike_predictor(self) -> bool:
        """Load predictor from disk. Returns True if loaded."""
        import os
        if not os.path.exists(PREDICTOR_CACHE_PATH):
            return False
        try:
            with open(PREDICTOR_CACHE_PATH, "rb") as f:
                payload = pickle.load(f)
            self._predictor = payload["model"]
            self._scaler = payload["scaler"]
            self._feature_cols = payload["feature_cols"]
            return True
        except Exception as exc:
            logger.warning("Failed to load spike predictor: %s", exc)
            return False

    def spike_probability(
        self,
        stock_id: int,
        week_ending: date,
    ) -> float:
        """Return probability of a spike this week for this stock. 0.0 if predictor not ready."""
        if self._predictor is None:
            if not self.load_spike_predictor():
                return 0.0

        # Fetch recent event (same week or most recent prior week)
        recent = self.session.execute(
            select(IntradayEvent)
            .where(
                IntradayEvent.stock_id == stock_id,
                IntradayEvent.week_ending <= week_ending,
            )
            .order_by(IntradayEvent.week_ending.desc())
            .limit(1)
        ).scalars().first()

        vix_level, vix_change = self._get_vix(week_ending)
        row = {
            "max_up": recent.max_intraday_up_pct if recent else 0.0,
            "max_down": recent.max_intraday_down_pct if recent else 0.0,
            "has_earnings": 0,
            "has_news_spike": int(recent.has_news_spike) if recent else 0,
            "has_macro_event": 0,
            "news_sentiment_delta": recent.news_sentiment_delta if recent else 0.0,
            "vix_level": vix_level or 20.0,
            "vix_change": vix_change or 0.0,
        }

        X = np.array([[row.get(c, 0.0) for c in self._feature_cols]])
        X_scaled = self._scaler.transform(X)
        try:
            prob = float(self._predictor.predict_proba(X_scaled)[0, 1])
        except Exception:
            prob = 0.0
        return prob

    def get_spike_summary(self, stock_id: int, weeks_back: int = 12) -> dict:
        """Return spike statistics for a stock over recent weeks. Used as a feature."""
        cutoff = date.today() - timedelta(weeks=weeks_back)
        events = self.session.execute(
            select(IntradayEvent).where(
                IntradayEvent.stock_id == stock_id,
                IntradayEvent.week_ending >= cutoff,
                IntradayEvent.max_intraday_up_pct.isnot(None),
            )
        ).scalars().all()

        if not events:
            return {
                "spike_count": 0, "avg_up": 0.0, "avg_down": 0.0,
                "spike_freq": 0.0, "last_spike_magnitude": 0.0,
                "earnings_spike_count": 0,
            }

        ups = [e.max_intraday_up_pct or 0.0 for e in events]
        downs = [e.max_intraday_down_pct or 0.0 for e in events]
        spikes = [e for e in events if max(e.max_intraday_up_pct or 0, e.max_intraday_down_pct or 0) >= SPIKE_THRESHOLD]
        sorted_events = sorted(events, key=lambda e: e.week_ending)
        last = sorted_events[-1]
        last_mag = max(last.max_intraday_up_pct or 0, last.max_intraday_down_pct or 0)

        return {
            "spike_count": len(spikes),
            "avg_up": float(np.mean(ups)),
            "avg_down": float(np.mean(downs)),
            "spike_freq": len(spikes) / max(len(events), 1),
            "last_spike_magnitude": last_mag,
            "earnings_spike_count": sum(1 for e in spikes if e.has_earnings),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_week_prices(self, stock_id: int, week_ending: date) -> pd.DataFrame:
        """Load daily prices for the week containing week_ending."""
        monday = week_ending - timedelta(days=4)
        rows = self.session.execute(
            select(PriceDaily).where(
                PriceDaily.stock_id == stock_id,
                PriceDaily.date >= monday,
                PriceDaily.date <= week_ending,
            ).order_by(PriceDaily.date)
        ).scalars().all()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([{
            "date": r.date, "open": r.open, "high": r.high,
            "low": r.low, "close": r.close, "volume": r.volume,
        } for r in rows])

    def _compute_spike_metrics(self, prices: pd.DataFrame) -> dict | None:
        """Compute intraday range metrics from daily OHLC for the week."""
        prices = prices.dropna(subset=["open", "high", "low", "close"])
        if prices.empty or prices["open"].eq(0).any():
            return None

        prices = prices.copy()
        prices["up_pct"] = (prices["high"] - prices["open"]) / prices["open"]
        prices["down_pct"] = (prices["open"] - prices["low"]) / prices["open"]

        max_up = float(prices["up_pct"].max())
        max_down = float(prices["down_pct"].max())
        hl_range = float(
            (prices["high"].max() - prices["low"].min()) / prices["low"].min()
        ) if prices["low"].min() > 0 else 0.0

        spike_type = "normal"
        if max_up >= SPIKE_THRESHOLD and max_down >= SPIKE_THRESHOLD:
            spike_type = "both"
        elif max_up >= SPIKE_THRESHOLD:
            spike_type = "up"
        elif max_down >= SPIKE_THRESHOLD:
            spike_type = "down"

        # Day of largest move
        max_move_idx = prices[["up_pct", "down_pct"]].max(axis=1).idxmax()
        spike_day = prices.loc[max_move_idx, "date"] if max_move_idx in prices.index else None

        return {
            "max_up": max_up,
            "max_down": max_down,
            "hl_range": hl_range,
            "spike_type": spike_type,
            "spike_day": spike_day,
        }

    def _attribute_causes(self, stock_id: int, week_ending: date, prices: pd.DataFrame) -> dict:
        """Check for known causes of intraday volatility this week."""
        from datetime import datetime
        monday = week_ending - timedelta(days=4)
        monday_dt = datetime(monday.year, monday.month, monday.day)
        week_end_dt = datetime(week_ending.year, week_ending.month, week_ending.day, 23, 59, 59)

        # --- Earnings: news articles flagged as earnings this week ---
        earnings_articles = self.session.execute(
            select(NewsAnalysis)
            .join(NewsArticle, NewsAnalysis.news_id == NewsArticle.id)
            .where(
                NewsAnalysis.stock_id == stock_id,
                NewsAnalysis.is_earnings == True,
                NewsArticle.published_at >= monday_dt,
                NewsArticle.published_at <= week_end_dt,
            )
        ).scalars().all()
        has_earnings = len(earnings_articles) > 0

        # --- News spike: unusually high article count or sentiment swing ---
        news_this_week = self.session.execute(
            select(NewsAnalysis)
            .join(NewsArticle, NewsAnalysis.news_id == NewsArticle.id)
            .where(
                NewsAnalysis.stock_id == stock_id,
                NewsArticle.published_at >= monday_dt,
                NewsArticle.published_at <= week_end_dt,
            )
        ).scalars().all()
        prior_week_start = monday - timedelta(weeks=1)
        prior_week_dt = datetime(prior_week_start.year, prior_week_start.month, prior_week_start.day)
        news_prior_week = self.session.execute(
            select(NewsAnalysis)
            .join(NewsArticle, NewsAnalysis.news_id == NewsArticle.id)
            .where(
                NewsAnalysis.stock_id == stock_id,
                NewsArticle.published_at >= prior_week_dt,
                NewsArticle.published_at < monday_dt,
            )
        ).scalars().all()

        sentiments_now = [n.sentiment_score for n in news_this_week if n.sentiment_score is not None]
        sentiments_prev = [n.sentiment_score for n in news_prior_week if n.sentiment_score is not None]
        avg_now = float(np.mean(sentiments_now)) if sentiments_now else 0.0
        avg_prev = float(np.mean(sentiments_prev)) if sentiments_prev else 0.0
        sentiment_delta = avg_now - avg_prev

        volume_ratio = len(news_this_week) / max(len(news_prior_week), 1)
        has_news_spike = abs(sentiment_delta) > 0.3 or volume_ratio > 2.5

        # --- Macro event: VIX weekly change > 15% or large SP500 move ---
        vix_level, vix_change = self._get_vix(week_ending)
        has_macro_event = (vix_change is not None and abs(vix_change) > 0.15)

        return {
            "has_earnings": has_earnings,
            "has_news_spike": has_news_spike,
            "has_macro_event": has_macro_event,
            "news_sentiment_delta": round(sentiment_delta, 4),
        }

    def _compute_feature_delta(self, stock_id: int, week_ending: date) -> dict | None:
        """Compare feature values this week vs prior week. Return top changed features."""
        from app.models.feature import FeatureWeekly
        prior_week = week_ending - timedelta(weeks=1)

        def _load(week: date) -> dict[str, float]:
            rows = self.session.execute(
                select(FeatureWeekly).where(
                    FeatureWeekly.stock_id == stock_id,
                    FeatureWeekly.week_ending == week,
                )
            ).scalars().all()
            return {r.feature_name: r.value for r in rows if r.value is not None}

        now = _load(week_ending)
        prev = _load(prior_week)

        if not now or not prev:
            return None

        deltas: dict[str, dict] = {}
        for feat, val_now in now.items():
            val_prev = prev.get(feat)
            if val_prev is None or val_prev == 0:
                continue
            delta_pct = (val_now - val_prev) / abs(val_prev)
            if abs(delta_pct) > 0.01:  # only record meaningful changes
                deltas[feat] = {
                    "before": round(float(val_prev), 6),
                    "after": round(float(val_now), 6),
                    "delta_pct": round(float(delta_pct), 4),
                }

        # Keep top N by absolute delta
        top = sorted(deltas.items(), key=lambda x: abs(x[1]["delta_pct"]), reverse=True)
        return dict(top[:FEATURE_DELTA_TOP_N]) if top else None

    def _compute_actual_return(self, prices: pd.DataFrame) -> float | None:
        """Week return = (Friday close - Monday open) / Monday open."""
        if prices.empty:
            return None
        monday_open = prices.iloc[0]["open"]
        friday_close = prices.iloc[-1]["close"]
        if not monday_open or monday_open == 0:
            return None
        return round(float((friday_close - monday_open) / monday_open), 6)

    def _get_vix(self, week_ending: date) -> tuple[float | None, float | None]:
        """Fetch VIX level and weekly change at week_ending."""
        rows = self.session.execute(
            select(MacroIndicator).where(
                MacroIndicator.indicator_code == "VIX",
                MacroIndicator.date <= week_ending,
            ).order_by(MacroIndicator.date.desc()).limit(10)
        ).scalars().all()
        if not rows:
            return None, None
        df = pd.DataFrame([{"date": r.date, "vix": r.value} for r in rows]).sort_values("date")
        level = float(df["vix"].iloc[-1])
        change = None
        if len(df) >= 2:
            prev = df["vix"].iloc[-2]
            if prev and prev != 0:
                change = float((level - prev) / prev)
        return level, change
