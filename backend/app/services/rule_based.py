"""
Rule-based strategy implementations.

Four strategies from the spec:
1. RSI + trend + volume
2. Financial score + technical score
3. News score + breakout
4. Low valuation + positive earnings surprise
"""
import numpy as np
import pandas as pd


class RuleBasedStrategy:
    """Base class — takes a wide feature DataFrame, returns signal series (0/1)."""

    name: str = "base"

    def signal(self, df: pd.DataFrame) -> pd.Series:
        raise NotImplementedError

    def evaluate(self, df: pd.DataFrame, label_col: str = "label") -> dict:
        sig = self.signal(df).astype(int)
        y = df[label_col].fillna(0).astype(int)
        tp = ((sig == 1) & (y == 1)).sum()
        fp = ((sig == 1) & (y == 0)).sum()
        fn = ((sig == 0) & (y == 1)).sum()
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        n_signals = int(sig.sum())
        avg_return = float(df.loc[sig == 1, "next_week_return"].mean()) if "next_week_return" in df.columns and n_signals > 0 else 0.0
        win_rate = float((df.loc[sig == 1, "next_week_return"] > 0).mean()) if "next_week_return" in df.columns and n_signals > 0 else 0.0
        return {
            "strategy": self.name,
            "n_signals": n_signals,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "avg_return": round(avg_return, 4),
            "win_rate": round(win_rate, 4),
        }


class RSITrendVolumeStrategy(RuleBasedStrategy):
    """
    Entry when:
    - RSI 14 < 50 (not overbought)
    - price_to_sma50 > 0 (above 50-week SMA — uptrend)
    - volume_zscore > 1.0 (volume spike)
    """
    name = "rsi_trend_volume"

    def signal(self, df: pd.DataFrame) -> pd.Series:
        cond = (
            (df.get("rsi_14", pd.Series(np.nan, index=df.index)) < 50) &
            (df.get("price_to_sma50", pd.Series(np.nan, index=df.index)) > 0) &
            (df.get("volume_zscore", pd.Series(np.nan, index=df.index)) > 1.0)
        )
        return cond.fillna(False).astype(int)


class FinancialTechnicalStrategy(RuleBasedStrategy):
    """
    Composite score: financial quality + technical momentum.
    Financial score = ROE > 0.15 AND debt_to_equity < 1.0 AND revenue_growth > 0
    Technical score = RSI > 40 AND price_to_sma200 > 0 AND return_4w > 0
    Signal when both scores are positive.
    """
    name = "financial_technical_score"

    def signal(self, df: pd.DataFrame) -> pd.Series:
        fin_score = (
            (df.get("roe", pd.Series(0.0, index=df.index)).fillna(0) > 0.15) &
            (df.get("debt_to_equity", pd.Series(999, index=df.index)).fillna(999) < 1.0) &
            (df.get("revenue_growth", pd.Series(0.0, index=df.index)).fillna(0) > 0)
        )
        tech_score = (
            (df.get("rsi_14", pd.Series(50, index=df.index)).fillna(50) > 40) &
            (df.get("price_to_sma200", pd.Series(0.0, index=df.index)).fillna(0) > 0) &
            (df.get("return_4w", pd.Series(0.0, index=df.index)).fillna(0) > 0)
        )
        return (fin_score & tech_score).astype(int)


class NewsBreakoutStrategy(RuleBasedStrategy):
    """
    Signal when:
    - News sentiment positive (score > 0.1)
    - Price breaking above 4-week high (return_4w > 5%)
    - Volume confirmation (volume_zscore > 0.5)
    """
    name = "news_breakout"

    def signal(self, df: pd.DataFrame) -> pd.Series:
        cond = (
            (df.get("news_sentiment_score", pd.Series(0.0, index=df.index)).fillna(0) > 0.1) &
            (df.get("return_4w", pd.Series(0.0, index=df.index)).fillna(0) > 0.05) &
            (df.get("volume_zscore", pd.Series(0.0, index=df.index)).fillna(0) > 0.5)
        )
        return cond.fillna(False).astype(int)


class LowValuationEarningsSurpriseStrategy(RuleBasedStrategy):
    """
    Low valuation + positive earnings surprise:
    - P/E < 20 (or NaN — no data = skip via fillna high value)
    - EV/EBITDA < 15
    - news_earnings_flag = 1 AND news_sentiment_score > 0.2
    """
    name = "low_valuation_earnings_surprise"

    def signal(self, df: pd.DataFrame) -> pd.Series:
        low_val = (
            (df.get("pe_ratio", pd.Series(999, index=df.index)).fillna(999) < 20) &
            (df.get("ev_to_ebitda", pd.Series(999, index=df.index)).fillna(999) < 15)
        )
        earnings_beat = (
            (df.get("news_earnings_flag", pd.Series(0, index=df.index)).fillna(0) == 1) &
            (df.get("news_sentiment_score", pd.Series(0.0, index=df.index)).fillna(0) > 0.2)
        )
        return (low_val & earnings_beat).fillna(False).astype(int)


ALL_RULE_STRATEGIES = [
    RSITrendVolumeStrategy(),
    FinancialTechnicalStrategy(),
    NewsBreakoutStrategy(),
    LowValuationEarningsSurpriseStrategy(),
]


def evaluate_all_rules(df: pd.DataFrame, label_col: str = "label") -> list[dict]:
    results = []
    for strategy in ALL_RULE_STRATEGIES:
        try:
            result = strategy.evaluate(df, label_col)
            results.append(result)
        except Exception as e:
            results.append({"strategy": strategy.name, "error": str(e)})
    return results
