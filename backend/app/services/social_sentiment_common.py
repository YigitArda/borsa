from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from functools import lru_cache

import numpy as np
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.news import SocialSentiment


class _FallbackSentimentIntensityAnalyzer:
    POSITIVE_WORDS = {
        "beat", "beats", "bull", "bullish", "growth", "gain", "gains", "good", "great",
        "improve", "improves", "improved", "positive", "record", "strong", "up", "win",
    }
    NEGATIVE_WORDS = {
        "bear", "bearish", "bad", "decline", "declines", "drop", "drops", "fall", "falls",
        "loss", "negative", "risk", "weak", "down", "miss", "misses", "warn", "warning",
    }

    def polarity_scores(self, text: str) -> dict[str, float]:
        import re

        tokens = re.findall(r"[a-z']+", text.lower())
        if not tokens:
            return {"compound": 0.0}
        pos = sum(token in self.POSITIVE_WORDS for token in tokens)
        neg = sum(token in self.NEGATIVE_WORDS for token in tokens)
        total = pos + neg
        compound = 0.0 if total == 0 else (pos - neg) / total
        return {"compound": max(-1.0, min(1.0, compound))}


@lru_cache(maxsize=1)
def get_vader_analyzer():
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        return SentimentIntensityAnalyzer()
    except ImportError:
        return _FallbackSentimentIntensityAnalyzer()


def upsert_social_weekly_rows(
    session: Session,
    *,
    stock_id: int,
    week_data: dict[date, list[float]],
    source: str,
    source_used: str,
) -> int:
    sorted_weeks = sorted(week_data.keys())
    mention_counts = [len(week_data[w]) for w in sorted_weeks]
    avg_mentions = sum(mention_counts) / max(len(mention_counts), 1)
    std_mentions = float(np.std(mention_counts)) or 1.0

    rows = []
    for i, week in enumerate(sorted_weeks):
        scores = week_data[week]
        n = len(scores)
        avg_sentiment = sum(scores) / max(n, 1)
        prev_n = mention_counts[i - 1] if i > 0 else n
        momentum = (n - prev_n) / max(prev_n, 1)
        abnormal = (n - avg_mentions) / std_mentions
        hype_risk = 1.0 if (n > avg_mentions + 2 * std_mentions and avg_sentiment > 0.3) else 0.0
        rows.append({
            "stock_id": stock_id,
            "week_ending": str(week),
            "mention_count": n,
            "mention_momentum": round(momentum, 4),
            "sentiment_polarity": round(avg_sentiment, 4),
            "hype_risk": hype_risk,
            "abnormal_attention": round(abnormal, 4),
            "source": source,
            "source_used": source_used,
        })

    if not rows:
        return 0

    stmt = pg_insert(SocialSentiment).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["stock_id", "week_ending", "source"],
        set_={
            "mention_count": stmt.excluded.mention_count,
            "mention_momentum": stmt.excluded.mention_momentum,
            "sentiment_polarity": stmt.excluded.sentiment_polarity,
            "hype_risk": stmt.excluded.hype_risk,
            "abnormal_attention": stmt.excluded.abnormal_attention,
            "source_used": stmt.excluded.source_used,
        },
    )
    session.execute(stmt)
    session.commit()
    return len(rows)
