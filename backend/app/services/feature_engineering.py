"""
Feature engineering service.

All features are computed from data available BEFORE the week_ending date
to prevent lookahead bias. Features are stored in long format.
"""
import logging
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.price import PriceDaily, PriceWeekly
from app.models.feature import FeatureWeekly, LabelWeekly
from app.services.financial_data import FinancialDataService
from app.services.macro_data import MacroDataService, SECTOR_TO_ETF_CODE
from app.services.news_service import NewsService

logger = logging.getLogger(__name__)

FEATURE_SET_VERSION = "v2"  # bumped: now includes financial, macro, news features

TECHNICAL_FEATURES = [
    "rsi_14", "macd", "macd_signal", "macd_hist",
    "sma_20", "sma_50", "sma_200",
    "ema_12", "ema_26",
    "bb_position",
    "atr_14",
    "volume_zscore",
    "return_1w", "return_4w", "return_12w",
    "high_52w_distance",
    "low_52w_distance",
    "trend_strength",
    "price_to_sma50",
    "price_to_sma200",
    "realized_vol",
]

FINANCIAL_FEATURES = [
    "pe_ratio", "forward_pe", "price_to_sales", "price_to_book",
    "ev_to_ebitda", "gross_margin", "operating_margin", "net_margin",
    "roe", "roa", "revenue_growth", "earnings_growth",
    "debt_to_equity", "current_ratio", "beta",
]

MACRO_FEATURES = [
    "VIX", "VIX_WEEKLY", "VIX_CHANGE_W", "TNX_10Y",
    "RISK_ON_SCORE", "sp500_trend_20w", "nasdaq_trend_20w",
    "cpi_proxy_trend_26w",
    "sector_xlk_trend20w", "sector_xlf_trend20w", "sector_xle_trend20w",
    "sector_xlv_trend20w", "sector_xli_trend20w", "sector_xlp_trend20w",
    "sector_xly_trend20w", "sector_xlu_trend20w", "sector_xlre_trend20w",
    "sector_xlb_trend20w",
]

VALUATION_PERCENTILE_FEATURES = [
    "pe_percentile_sector",
    "pb_percentile_sector",
    "ev_ebitda_percentile_sector",
]

NEWS_FEATURES = [
    "news_sentiment_score", "news_volume",
    "news_positive_count", "news_negative_count",
    "news_earnings_flag", "news_legal_flag", "news_product_flag",
    "news_analyst_flag", "news_mgmt_flag", "news_recency_impact",
]

ALL_FEATURES = TECHNICAL_FEATURES + FINANCIAL_FEATURES + MACRO_FEATURES + NEWS_FEATURES + VALUATION_PERCENTILE_FEATURES

TARGET_NAMES = [
    "target_2pct_1w",      # next week return >= 2%
    "target_3pct_1w",      # next week return >= 3%
    "risk_target_1w",      # next week return <= -2%
    "risk_target_3pct_1w", # next week return <= -3%
    "next_week_return",
    "next_2week_return",
    "next_4week_return",
]


class FeatureEngineeringService:
    def __init__(self, session: Session):
        self.session = session
        self._macro_cache: dict | None = None  # lazily loaded

    def _get_macro_features(self, week_end) -> dict[str, float]:
        if self._macro_cache is None:
            macro_svc = MacroDataService(self.session)
            self._macro_cache = macro_svc.compute_macro_features_weekly()
        import datetime
        key = week_end.date() if hasattr(week_end, "date") else week_end
        # Find closest week <= key
        candidates = [d for d in self._macro_cache if d <= key]
        if not candidates:
            return {}
        return self._macro_cache[max(candidates)]

    def compute_features_for_stock(self, ticker: str) -> int:
        stock = self._get_stock(ticker)
        if stock is None:
            logger.warning(f"Stock not found: {ticker}")
            return 0

        daily_df = self._load_daily(stock.id)
        weekly_df = self._load_weekly(stock.id)

        if daily_df.empty or weekly_df.empty:
            return 0

        feature_rows = []
        label_rows = []

        for i, (week_end, _) in enumerate(weekly_df.iterrows()):
            # Use daily data available BEFORE this week ends
            avail_daily = daily_df[daily_df.index < pd.Timestamp(week_end)]
            if len(avail_daily) < 50:
                continue

            features = self._compute_technical(avail_daily, weekly_df, week_end)

            # Financial features
            fin_svc = FinancialDataService(self.session)
            fin_features = fin_svc.get_financial_features(stock.id, week_end.date() if hasattr(week_end, "date") else week_end)
            features.update({k: v for k, v in fin_features.items() if k in FINANCIAL_FEATURES})

            # Macro features
            macro_features = self._get_macro_features(week_end)
            features.update({k: v for k, v in macro_features.items() if k in MACRO_FEATURES})

            # News features
            news_svc = NewsService(self.session)
            week_end_date = week_end.date() if hasattr(week_end, "date") else week_end
            news_features = news_svc.get_weekly_news_features(stock.id, week_end_date)
            features.update(news_features)

            for fname, fval in features.items():
                feature_rows.append({
                    "stock_id": stock.id,
                    "week_ending": week_end.date() if hasattr(week_end, "date") else week_end,
                    "feature_name": fname,
                    "value": float(fval) if pd.notna(fval) else None,
                    "feature_set_version": FEATURE_SET_VERSION,
                })

            # Labels — look FORWARD (future data, only valid for training)
            labels = self._compute_labels(weekly_df, week_end)
            for lname, lval in labels.items():
                label_rows.append({
                    "stock_id": stock.id,
                    "week_ending": week_end.date(),
                    "target_name": lname,
                    "value": float(lval) if pd.notna(lval) else None,
                })

        self._upsert_features(feature_rows)
        self._upsert_labels(label_rows)
        return len(feature_rows)

    # ------------------------------------------------------------------
    # Technical feature computation
    # ------------------------------------------------------------------

    def _compute_technical(self, daily: pd.DataFrame, weekly: pd.DataFrame, week_end: pd.Timestamp) -> dict:
        close = daily["close"].dropna()
        volume = daily["volume"].fillna(0)

        features: dict[str, float] = {}

        # RSI 14
        features["rsi_14"] = self._rsi(close, 14)

        # MACD (12, 26, 9)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal = macd_line.ewm(span=9, adjust=False).mean()
        features["macd"] = float(macd_line.iloc[-1]) if len(macd_line) > 0 else np.nan
        features["macd_signal"] = float(signal.iloc[-1]) if len(signal) > 0 else np.nan
        features["macd_hist"] = features["macd"] - features["macd_signal"]

        # SMAs
        for period in [20, 50, 200]:
            sma = close.rolling(period).mean()
            features[f"sma_{period}"] = float(sma.iloc[-1]) if len(sma) >= period else np.nan

        # EMAs
        features["ema_12"] = float(close.ewm(span=12).mean().iloc[-1])
        features["ema_26"] = float(close.ewm(span=26).mean().iloc[-1])

        # Bollinger Bands
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        upper = sma20 + 2 * std20
        lower = sma20 - 2 * std20
        band_range = upper - lower
        if pd.notna(band_range.iloc[-1]) and band_range.iloc[-1] > 0:
            features["bb_position"] = float((close.iloc[-1] - lower.iloc[-1]) / band_range.iloc[-1])
        else:
            features["bb_position"] = np.nan

        # ATR 14
        features["atr_14"] = self._atr(daily, 14)

        # Volume z-score (20-day rolling)
        vol_mean = volume.rolling(20).mean()
        vol_std = volume.rolling(20).std()
        if pd.notna(vol_std.iloc[-1]) and vol_std.iloc[-1] > 0:
            features["volume_zscore"] = float((volume.iloc[-1] - vol_mean.iloc[-1]) / vol_std.iloc[-1])
        else:
            features["volume_zscore"] = np.nan

        # Past returns from weekly data
        avail_weekly = weekly[weekly.index <= week_end]["weekly_return"].dropna()
        features["return_1w"] = float(avail_weekly.iloc[-1]) if len(avail_weekly) >= 1 else np.nan
        features["return_4w"] = float((1 + avail_weekly.iloc[-4:]).prod() - 1) if len(avail_weekly) >= 4 else np.nan
        features["return_12w"] = float((1 + avail_weekly.iloc[-12:]).prod() - 1) if len(avail_weekly) >= 12 else np.nan

        # 52-week high/low distance
        year_close = close.iloc[-252:] if len(close) >= 252 else close
        high_52 = year_close.max()
        low_52 = year_close.min()
        cur = close.iloc[-1]
        features["high_52w_distance"] = float((cur - high_52) / high_52) if high_52 > 0 else np.nan
        features["low_52w_distance"] = float((cur - low_52) / low_52) if low_52 > 0 else np.nan

        # Trend strength (slope of 20-day SMA, normalized)
        sma20_vals = close.rolling(20).mean().iloc[-20:].dropna()
        if len(sma20_vals) >= 10:
            x = np.arange(len(sma20_vals))
            slope = float(np.polyfit(x, sma20_vals.values, 1)[0])
            features["trend_strength"] = slope / float(sma20_vals.mean()) if sma20_vals.mean() != 0 else np.nan
        else:
            features["trend_strength"] = np.nan

        # Price relative to SMAs
        p = close.iloc[-1]
        sma50 = features.get("sma_50")
        sma200 = features.get("sma_200")
        features["price_to_sma50"] = float(p / sma50 - 1) if sma50 and sma50 > 0 else np.nan
        features["price_to_sma200"] = float(p / sma200 - 1) if sma200 and sma200 > 0 else np.nan

        # Realized volatility
        avail_w = weekly[weekly.index <= week_end]["realized_volatility"].dropna()
        features["realized_vol"] = float(avail_w.iloc[-1]) if len(avail_w) > 0 else np.nan

        return features

    # ------------------------------------------------------------------
    # Label computation
    # ------------------------------------------------------------------

    def _compute_labels(self, weekly: pd.DataFrame, week_end: pd.Timestamp) -> dict:
        future = weekly[weekly.index > week_end]["weekly_return"]
        labels: dict[str, float] = {}

        r1 = float(future.iloc[0]) if len(future) >= 1 else np.nan
        r2 = float((1 + future.iloc[:2]).prod() - 1) if len(future) >= 2 else np.nan
        r4 = float((1 + future.iloc[:4]).prod() - 1) if len(future) >= 4 else np.nan

        labels["next_week_return"] = r1
        labels["next_2week_return"] = r2
        labels["next_4week_return"] = r4
        labels["target_2pct_1w"] = 1.0 if pd.notna(r1) and r1 >= 0.02 else (0.0 if pd.notna(r1) else np.nan)
        labels["target_3pct_1w"] = 1.0 if pd.notna(r1) and r1 >= 0.03 else (0.0 if pd.notna(r1) else np.nan)
        labels["risk_target_1w"] = 1.0 if pd.notna(r1) and r1 <= -0.02 else (0.0 if pd.notna(r1) else np.nan)
        labels["risk_target_3pct_1w"] = 1.0 if pd.notna(r1) and r1 <= -0.03 else (0.0 if pd.notna(r1) else np.nan)

        return labels

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _rsi(self, close: pd.Series, period: int = 14) -> float:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else np.nan

    def _atr(self, daily: pd.DataFrame, period: int = 14) -> float:
        high = daily["high"]
        low = daily["low"]
        close = daily["close"]
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        return float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else np.nan

    def _load_daily(self, stock_id: int) -> pd.DataFrame:
        rows = self.session.execute(
            select(PriceDaily).where(PriceDaily.stock_id == stock_id).order_by(PriceDaily.date)
        ).scalars().all()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([{
            "date": r.date, "open": r.open, "high": r.high,
            "low": r.low, "close": r.close, "volume": r.volume,
        } for r in rows])
        df["date"] = pd.to_datetime(df["date"])
        return df.set_index("date")

    def _load_weekly(self, stock_id: int) -> pd.DataFrame:
        rows = self.session.execute(
            select(PriceWeekly).where(PriceWeekly.stock_id == stock_id).order_by(PriceWeekly.week_ending)
        ).scalars().all()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([{
            "week_ending": r.week_ending, "close": r.close,
            "weekly_return": r.weekly_return, "realized_volatility": r.realized_volatility,
        } for r in rows])
        df["week_ending"] = pd.to_datetime(df["week_ending"])
        return df.set_index("week_ending")

    def _get_stock(self, ticker: str) -> Stock | None:
        return self.session.execute(select(Stock).where(Stock.ticker == ticker)).scalar_one_or_none()

    def _upsert_features(self, rows: list[dict]):
        if not rows:
            return
        stmt = pg_insert(FeatureWeekly).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["stock_id", "week_ending", "feature_name", "feature_set_version"],
            set_={"value": stmt.excluded.value},
        )
        self.session.execute(stmt)
        self.session.commit()

    def _upsert_labels(self, rows: list[dict]):
        if not rows:
            return
        stmt = pg_insert(LabelWeekly).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["stock_id", "week_ending", "target_name"],
            set_={"value": stmt.excluded.value},
        )
        self.session.execute(stmt)
        self.session.commit()

    def compute_valuation_percentiles_all(self, tickers: list[str]) -> int:
        """
        Cross-sectional: for each week, rank each stock's valuation metrics
        within its sector and store as percentile features (0..1).
        Must be called after per-stock features are computed.
        """
        # Load stocks with sector info
        stocks = self.session.execute(
            select(Stock).where(Stock.ticker.in_(tickers))
        ).scalars().all()
        stock_by_id = {s.id: s for s in stocks}

        # Load pe_ratio, price_to_book, ev_to_ebitda features for all stocks
        val_metrics = ["pe_ratio", "price_to_book", "ev_to_ebitda"]
        from app.models.feature import FeatureWeekly
        rows = self.session.execute(
            select(FeatureWeekly).where(
                FeatureWeekly.stock_id.in_([s.id for s in stocks]),
                FeatureWeekly.feature_name.in_(val_metrics),
            )
        ).scalars().all()

        if not rows:
            return 0

        df = pd.DataFrame([{
            "stock_id": r.stock_id,
            "week_ending": r.week_ending,
            "feature_name": r.feature_name,
            "value": r.value,
        } for r in rows])

        df["sector"] = df["stock_id"].map(lambda sid: (stock_by_id.get(sid) or Stock()).sector or "Unknown")
        wide = df.pivot_table(index=["stock_id", "week_ending", "sector"], columns="feature_name", values="value").reset_index()

        pct_rows = []
        feature_map = {"pe_ratio": "pe_percentile_sector", "price_to_book": "pb_percentile_sector", "ev_to_ebitda": "ev_ebitda_percentile_sector"}

        for week, wdf in wide.groupby("week_ending"):
            for metric, pct_name in feature_map.items():
                if metric not in wdf.columns:
                    continue
                for sector, sdf in wdf.groupby("sector"):
                    valid = sdf[["stock_id", metric]].dropna(subset=[metric])
                    if valid.empty:
                        continue
                    valid = valid.copy()
                    valid["pct"] = valid[metric].rank(pct=True)
                    for _, vrow in valid.iterrows():
                        pct_rows.append({
                            "stock_id": int(vrow["stock_id"]),
                            "week_ending": week,
                            "feature_name": pct_name,
                            "value": float(vrow["pct"]),
                            "feature_set_version": FEATURE_SET_VERSION,
                        })

        if pct_rows:
            self._upsert_features(pct_rows)
            logger.info(f"Valuation percentiles: {len(pct_rows)} rows")
        return len(pct_rows)

    def run_all(self, tickers: list[str]) -> dict:
        results = {}
        for ticker in tickers:
            logger.info(f"Computing features: {ticker}")
            try:
                n = self.compute_features_for_stock(ticker)
                results[ticker] = n
            except Exception as e:
                logger.error(f"Feature error {ticker}: {e}")
                results[ticker] = 0
        # Cross-sectional valuation percentiles (batch, after per-stock features)
        try:
            self.compute_valuation_percentiles_all(tickers)
        except Exception as e:
            logger.error(f"Valuation percentile error: {e}")
        return results
