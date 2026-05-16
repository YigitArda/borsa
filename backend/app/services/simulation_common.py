from __future__ import annotations

from datetime import date

import pandas as pd


def to_date(value) -> date:
    if isinstance(value, date):
        return value
    return pd.to_datetime(value).date()


def build_price_lookup(price_df: pd.DataFrame) -> dict[tuple[str, date], dict]:
    lookup: dict[tuple[str, date], dict] = {}
    if price_df is None or price_df.empty:
        return lookup
    for _, row in price_df.iterrows():
        d = to_date(row["date"])
        lookup[(row["ticker"], d)] = row.to_dict()
    return lookup
