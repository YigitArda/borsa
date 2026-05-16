"""PEAD plus optional NLP sentiment strategy."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
import numpy as np
import pandas as pd

from app.time_utils import utcnow

logger = logging.getLogger(__name__)


@dataclass
class EarningsEvent:
    ticker: str
    report_date: datetime
    expected_eps: float
    actual_eps: float | None = None
    surprise_pct: float | None = None
    transcript_text: str | None = None
    finbert_score: float | None = None
    sue_score: float | None = None
    volume_anomaly: float | None = None


class FinBERTAnalyzer:
    """Lazy FinBERT scorer with keyword fallback when transformers is unavailable."""

    def __init__(self, model_name: str = "yiyanghkust/finbert-tone", use_transformers: bool = False):
        self.model_name = model_name
        self._model = None
        self._tokenizer = None
        self._torch = None
        self._fallback = not use_transformers

    def load(self) -> None:
        if self._model is not None or self._fallback:
            return
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            self._torch = torch
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
        except Exception as exc:
            logger.info("FinBERT unavailable, using keyword fallback: %s", exc)
            self._fallback = True

    def score(self, text: str) -> float:
        if not text:
            return 0.0
        self.load()
        if self._fallback or self._model is None:
            return self._keyword_score(text)
        try:
            inputs = self._tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
            with self._torch.no_grad():
                outputs = self._model(**inputs)
                probs = self._torch.softmax(outputs.logits, dim=1)
            return float((probs[0][-1] - probs[0][0]).item())
        except Exception as exc:
            logger.warning("FinBERT inference failed: %s", exc)
            return self._keyword_score(text)

    def _keyword_score(self, text: str) -> float:
        positive = {"beat", "strong", "growth", "exceeded", "record", "robust", "raise"}
        negative = {"miss", "weak", "decline", "challenging", "headwinds", "soft", "cut"}
        words = text.lower()
        pos = sum(1 for word in positive if word in words)
        neg = sum(1 for word in negative if word in words)
        total = pos + neg
        return float((pos - neg) / total) if total else 0.0


class PEADNLPStrategy:
    """Post-earnings-announcement-drift strategy with optional transcript tone."""

    def __init__(
        self,
        finbert: FinBERTAnalyzer | None = None,
        sue_lookback: int = 8,
        hold_days: int = 60,
        finbert_threshold: float = 0.6,
        sue_threshold: float = 1.5,
        volume_threshold: float = 2.0,
    ):
        self.finbert = finbert or FinBERTAnalyzer()
        self.sue_lookback = sue_lookback
        self.hold_days = hold_days
        self.finbert_thresh = finbert_threshold
        self.sue_thresh = sue_threshold
        self.volume_thresh = volume_threshold
        self.earnings_cache: dict[str, list[EarningsEvent]] = {}

    def fetch_earnings_calendar(
        self,
        tickers: list[str],
        start_date: datetime,
        end_date: datetime,
        fmp_api_key: str | None = None,
    ) -> dict[str, list[EarningsEvent]]:
        if not fmp_api_key:
            self.earnings_cache = {ticker: [] for ticker in tickers}
            return self.earnings_cache

        events: dict[str, list[EarningsEvent]] = {}
        for ticker in tickers:
            try:
                url = f"https://financialmodelingprep.com/api/v3/earnings/{ticker}"
                with httpx.Client(timeout=10.0) as client:
                    response = client.get(
                        url, params={"limit": self.sue_lookback, "apikey": fmp_api_key}
                    )
                response.raise_for_status()
                ticker_events = []
                for item in response.json():
                    report_date = datetime.strptime(item["date"], "%Y-%m-%d")
                    if not (start_date <= report_date <= end_date):
                        continue
                    ticker_events.append(
                        EarningsEvent(
                            ticker=ticker,
                            report_date=report_date,
                            expected_eps=float(item.get("epsEstimated") or 0.0),
                            actual_eps=float(item["eps"]) if item.get("eps") else None,
                            surprise_pct=float(item["surprise"])
                            if item.get("surprise") is not None
                            else None,
                        )
                    )
                events[ticker] = ticker_events
            except Exception as exc:
                logger.warning("Failed to fetch earnings for %s: %s", ticker, exc)
                events[ticker] = []
        self.earnings_cache = events
        return events

    def compute_sue(self, events: list[EarningsEvent]) -> pd.DataFrame:
        rows = [
            {
                "date": event.report_date,
                "actual": event.actual_eps,
                "expected": event.expected_eps,
                "surprise": event.actual_eps - event.expected_eps
                if event.actual_eps is not None
                else np.nan,
            }
            for event in events
            if event.actual_eps is not None
        ]
        df = pd.DataFrame(rows)
        if len(df) < 2:
            return df
        std = df["surprise"].rolling(self.sue_lookback, min_periods=2).std()
        df["sue"] = (df["surprise"] / std.replace(0, np.nan)).fillna(0.0)
        return df

    def analyze_transcripts(
        self, ticker: str, events: list[EarningsEvent], transcripts: dict[datetime, str] | None = None
    ) -> list[EarningsEvent]:
        transcripts = transcripts or {}
        for event in events:
            text = event.transcript_text or transcripts.get(event.report_date)
            if text:
                event.transcript_text = text
                event.finbert_score = self.finbert.score(text)
        return events

    def generate_signals(
        self,
        tickers: list[str],
        price_data: dict[str, pd.DataFrame],
        fmp_api_key: str | None = None,
        earnings_events: dict[str, list[EarningsEvent]] | None = None,
    ) -> pd.DataFrame:
        start = utcnow() - timedelta(days=365)
        end = utcnow() + timedelta(days=30)
        self.earnings_cache = earnings_events or self.fetch_earnings_calendar(
            tickers, start, end, fmp_api_key
        )

        signals = []
        for ticker in tickers:
            events = self.earnings_cache.get(ticker, [])
            if not events:
                continue
            events = self.analyze_transcripts(ticker, events)
            sue_df = self.compute_sue(events)
            latest_sue = float(sue_df["sue"].iloc[-1]) if "sue" in sue_df and len(sue_df) else 0.0
            latest_event = sorted(events, key=lambda item: item.report_date)[-1]
            volume_anomaly = self._volume_anomaly(price_data.get(ticker))

            signal = "HOLD"
            confidence = 0.0
            if latest_event.finbert_score is not None and latest_event.finbert_score > self.finbert_thresh:
                signal = "LONG"
                confidence = abs(float(latest_event.finbert_score))
            elif latest_sue > self.sue_thresh and volume_anomaly > self.volume_thresh:
                signal = "LONG"
                confidence = min(latest_sue / 3.0, 1.0)
            elif latest_sue < -self.sue_thresh:
                signal = "SHORT"
                confidence = min(abs(latest_sue) / 3.0, 1.0)

            signals.append(
                {
                    "ticker": ticker,
                    "report_date": latest_event.report_date,
                    "signal": signal,
                    "confidence": float(confidence),
                    "expected_hold_days": self.hold_days,
                    "sue_score": float(latest_sue),
                    "finbert_score": float(latest_event.finbert_score or 0.0),
                    "volume_anomaly": float(volume_anomaly),
                    "rationale": (
                        f"SUE: {latest_sue:.2f}, NLP: {float(latest_event.finbert_score or 0.0):.2f}, "
                        f"Vol: {volume_anomaly:.1f}x"
                    ),
                }
            )
        return pd.DataFrame(signals)

    def apply_meta_label(
        self, signals: pd.DataFrame, historical_win_rate: float = 0.55
    ) -> pd.DataFrame:
        if signals.empty:
            return signals
        out = signals.copy()
        out["meta_prob"] = (out["confidence"].astype(float) * historical_win_rate).clip(0, 1)
        out["kelly_fraction"] = out.apply(
            lambda row: self._kelly(float(row["meta_prob"]), float(row["confidence"]) * 2),
            axis=1,
        )
        out["take_trade"] = out["meta_prob"] > 0.60
        return out

    def _volume_anomaly(self, df: pd.DataFrame | None) -> float:
        if df is None or df.empty or "volume" not in df or len(df) < 20:
            return 1.0
        vol_20d = df["volume"].rolling(20, min_periods=5).mean().iloc[-1]
        vol_5d = df["volume"].rolling(5, min_periods=2).mean().iloc[-1]
        return float(vol_5d / vol_20d) if vol_20d and vol_20d > 0 else 1.0

    def _kelly(self, p: float, b: float) -> float:
        if b <= 0:
            return 0.0
        q = 1.0 - p
        return float(max(0.0, min((b * p - q) / b, 0.10)))


class PEADNLPBacktester:
    """Simple event backtester for PEAD/NLP signals."""

    def __init__(self, strategy: PEADNLPStrategy):
        self.strategy = strategy

    def run(
        self,
        tickers: list[str],
        price_data: dict[str, pd.DataFrame],
        fmp_api_key: str | None,
        start_date: datetime,
        end_date: datetime,
        earnings_events: dict[str, list[EarningsEvent]] | None = None,
    ) -> pd.DataFrame:
        signals = self.strategy.generate_signals(
            tickers, price_data, fmp_api_key, earnings_events=earnings_events
        )
        if signals.empty:
            return pd.DataFrame()
        mask = (signals["report_date"] >= start_date) & (signals["report_date"] <= end_date)
        period_signals = signals[mask].copy()

        rows = []
        for _, row in period_signals.iterrows():
            ticker = row["ticker"]
            if row["signal"] not in {"LONG", "SHORT"} or ticker not in price_data:
                continue
            df = price_data[ticker].sort_index()
            future = df[df.index >= row["report_date"]]
            if future.empty:
                continue
            entry_date = future.index[0]
            entry_price = float(future.iloc[0]["close"])
            exit_target = entry_date + pd.Timedelta(days=self.strategy.hold_days)
            exit_window = df[df.index >= exit_target]
            if exit_window.empty or entry_price <= 0:
                continue
            exit_date = exit_window.index[0]
            exit_price = float(exit_window.iloc[0]["close"])
            direction = 1.0 if row["signal"] == "LONG" else -1.0
            net_return = (exit_price / entry_price - 1.0) * direction - 0.002
            rows.append(
                {
                    "ticker": ticker,
                    "entry": entry_date,
                    "exit": exit_date,
                    "signal": row["signal"],
                    "return": float(net_return),
                    "sue": float(row["sue_score"]),
                    "confidence": float(row["confidence"]),
                }
            )
        return pd.DataFrame(rows)
