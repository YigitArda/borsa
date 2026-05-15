"""
Data ingestion service — yfinance → PostgreSQL.

Point-in-time note: yfinance fundamentals are NOT point-in-time;
they return today's restated values. Price/OHLCV data is reliable.
"""
import logging
from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models.stock import Stock, StockUniverseSnapshot
from app.models.price import PriceDaily, PriceWeekly

logger = logging.getLogger(__name__)


class DataIngestionService:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------
    # Universe
    # ------------------------------------------------------------------

    def upsert_stock(self, ticker: str, info: dict | None = None) -> Stock:
        stmt = select(Stock).where(Stock.ticker == ticker)
        stock = self.session.execute(stmt).scalar_one_or_none()
        if stock is None:
            stock = Stock(ticker=ticker)
            if info:
                stock.name = info.get("longName") or info.get("shortName")
                stock.sector = info.get("sector")
                stock.industry = info.get("industry")
                stock.exchange = info.get("exchange")
            self.session.add(stock)
            self.session.flush()
        return stock

    def record_universe_snapshot(self, snapshot_date: date, tickers: list[str], index_name: str = "SP500"):
        for ticker in tickers:
            snap = StockUniverseSnapshot(
                snapshot_date=snapshot_date,
                index_name=index_name,
                ticker=ticker,
            )
            self.session.merge(snap)

    # ------------------------------------------------------------------
    # Daily prices
    # ------------------------------------------------------------------

    def ingest_daily_prices(self, ticker: str, start: str = "2010-01-01", end: str | None = None) -> int:
        stock = self.upsert_stock(ticker)
        df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
        if df.empty:
            logger.warning(f"No data for {ticker}")
            return 0

        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.reset_index()
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]
        df = df.rename(columns={"date": "date_", "adj_close": "adj_close"})

        rows = []
        for _, row in df.iterrows():
            rows.append({
                "stock_id": stock.id,
                "date": row.get("date_", row.get("date")).date() if hasattr(row.get("date_", row.get("date")), "date") else row.get("date_", row.get("date")),
                "open": float(row["open"]) if pd.notna(row.get("open")) else None,
                "high": float(row["high"]) if pd.notna(row.get("high")) else None,
                "low": float(row["low"]) if pd.notna(row.get("low")) else None,
                "close": float(row["close"]) if pd.notna(row.get("close")) else None,
                "adj_close": float(row["close"]) if pd.notna(row.get("close")) else None,
                "volume": int(row["volume"]) if pd.notna(row.get("volume")) else None,
            })

        if not rows:
            return 0

        stmt = pg_insert(PriceDaily).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["stock_id", "date"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "adj_close": stmt.excluded.adj_close,
                "volume": stmt.excluded.volume,
            },
        )
        self.session.execute(stmt)
        self.session.commit()
        logger.info(f"Ingested {len(rows)} daily rows for {ticker}")
        return len(rows)

    # ------------------------------------------------------------------
    # Weekly resample
    # ------------------------------------------------------------------

    def resample_weekly(self, ticker: str) -> int:
        stock = self._get_stock(ticker)
        if stock is None:
            return 0

        stmt = select(PriceDaily).where(PriceDaily.stock_id == stock.id).order_by(PriceDaily.date)
        rows = self.session.execute(stmt).scalars().all()
        if not rows:
            return 0

        df = pd.DataFrame([{
            "date": r.date,
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
        } for r in rows])
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()

        weekly = df.resample("W-FRI").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna(subset=["close"])

        weekly["weekly_return"] = weekly["close"].pct_change()
        weekly["realized_volatility"] = df["close"].pct_change().resample("W-FRI").std() * (5 ** 0.5)

        insert_rows = []
        for week_end, row in weekly.iterrows():
            insert_rows.append({
                "stock_id": stock.id,
                "week_ending": week_end.date(),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": int(row["volume"]) if pd.notna(row["volume"]) else None,
                "weekly_return": row["weekly_return"] if pd.notna(row["weekly_return"]) else None,
                "realized_volatility": row["realized_volatility"] if pd.notna(row["realized_volatility"]) else None,
            })

        if not insert_rows:
            return 0

        stmt = pg_insert(PriceWeekly).values(insert_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["stock_id", "week_ending"],
            set_={k: getattr(stmt.excluded, k) for k in ["open", "high", "low", "close", "volume", "weekly_return", "realized_volatility"]},
        )
        self.session.execute(stmt)
        self.session.commit()
        return len(insert_rows)

    # ------------------------------------------------------------------

    def _get_stock(self, ticker: str) -> Stock | None:
        return self.session.execute(select(Stock).where(Stock.ticker == ticker)).scalar_one_or_none()

    def run_full_ingest(self, tickers: list[str] | None = None, start: str = "2010-01-01"):
        tickers = tickers or settings.mvp_tickers
        for ticker in tickers:
            logger.info(f"Ingesting {ticker}...")
            try:
                self.ingest_daily_prices(ticker, start=start)
                self.resample_weekly(ticker)
            except Exception as e:
                logger.error(f"Failed {ticker}: {e}")
