"""Helpers for adjusted-price analytics with raw OHLCV storage."""

from __future__ import annotations

import math


def as_float(value) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def adjusted_ohlc(open_price, high, low, close, adj_close) -> dict[str, float | None]:
    """Scale OHLC to the adjusted-close basis.

    Daily rows retain raw close and adjusted close separately. Long-history
    analytics should use adjusted prices to avoid split/dividend artifacts.
    """
    raw_close = as_float(close)
    adjusted_close = as_float(adj_close)
    ratio = None
    if raw_close and adjusted_close is not None:
        ratio = adjusted_close / raw_close

    def scale(value) -> float | None:
        numeric = as_float(value)
        if numeric is None:
            return None
        return numeric * ratio if ratio is not None else numeric

    return {
        "open": scale(open_price),
        "high": scale(high),
        "low": scale(low),
        "close": adjusted_close if adjusted_close is not None else raw_close,
    }
