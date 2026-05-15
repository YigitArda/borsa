"""
Data ingestion service — yfinance → PostgreSQL.

Point-in-time note: yfinance fundamentals are NOT point-in-time;
they return today's restated values. Price/OHLCV data is reliable.
"""
import logging
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models.stock import CorporateAction, Stock, StockUniverseSnapshot, TickerAlias
from app.models.price import PriceDaily, PriceWeekly
from app.services.price_adjustments import adjusted_ohlc

try:
    import yfinance as yf
except ImportError:  # pragma: no cover - optional dependency guard
    yf = None

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
        rows = [
            {"snapshot_date": snapshot_date, "index_name": index_name, "ticker": ticker}
            for ticker in tickers
        ]
        if not rows:
            return 0
        stmt = pg_insert(StockUniverseSnapshot).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["snapshot_date", "index_name", "ticker"],
            set_={"weight": stmt.excluded.weight},
        )
        self.session.execute(stmt)
        return len(rows)

    def import_universe_snapshots_csv(self, path: str, index_name: str = "SP500") -> int:
        """Import historical index membership snapshots.

        CSV columns: snapshot_date,ticker[,weight,index_name]
        This is the hook for survivorship-free historical universes from a
        licensed or manually curated source.
        """
        df = pd.read_csv(path)
        required = {"snapshot_date", "ticker"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"missing columns: {', '.join(sorted(missing))}")

        rows = []
        for _, row in df.iterrows():
            rows.append({
                "snapshot_date": pd.to_datetime(row["snapshot_date"]).date(),
                "index_name": row.get("index_name") or index_name,
                "ticker": str(row["ticker"]).upper(),
                "weight": float(row["weight"]) if "weight" in df.columns and pd.notna(row.get("weight")) else None,
            })
        if not rows:
            return 0
        stmt = pg_insert(StockUniverseSnapshot).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["snapshot_date", "index_name", "ticker"],
            set_={"weight": stmt.excluded.weight},
        )
        self.session.execute(stmt)
        self.session.commit()
        return len(rows)

    def import_ticker_aliases_csv(self, path: str) -> int:
        """Import ticker changes.

        CSV columns: old_ticker,new_ticker,effective_date[,reason]
        """
        df = pd.read_csv(path)
        required = {"old_ticker", "new_ticker", "effective_date"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"missing columns: {', '.join(sorted(missing))}")

        rows = []
        for _, row in df.iterrows():
            rows.append({
                "old_ticker": str(row["old_ticker"]).upper(),
                "new_ticker": str(row["new_ticker"]).upper(),
                "effective_date": pd.to_datetime(row["effective_date"]).date(),
                "reason": row.get("reason") if pd.notna(row.get("reason")) else None,
            })
        if not rows:
            return 0
        stmt = pg_insert(TickerAlias).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["old_ticker", "new_ticker", "effective_date"],
            set_={"reason": stmt.excluded.reason},
        )
        self.session.execute(stmt)
        self.session.commit()
        return len(rows)

    def import_corporate_actions_csv(self, path: str, data_source: str = "csv") -> int:
        """Import split/dividend/merger/ticker-change audit events.

        CSV columns: ticker,action_date,action_type[,value,description,data_source]
        """
        df = pd.read_csv(path)
        required = {"ticker", "action_date", "action_type"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"missing columns: {', '.join(sorted(missing))}")

        rows = []
        for _, row in df.iterrows():
            ticker = str(row["ticker"]).upper()
            stock = self.upsert_stock(ticker)
            rows.append({
                "stock_id": stock.id,
                "action_date": pd.to_datetime(row["action_date"]).date(),
                "action_type": str(row["action_type"]),
                "value": float(row["value"]) if "value" in df.columns and pd.notna(row.get("value")) else None,
                "description": row.get("description") if pd.notna(row.get("description")) else None,
                "data_source": row.get("data_source") if pd.notna(row.get("data_source")) else data_source,
            })
        if not rows:
            return 0
        stmt = pg_insert(CorporateAction).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["stock_id", "action_date", "action_type"],
            set_={
                "value": stmt.excluded.value,
                "description": stmt.excluded.description,
                "data_source": stmt.excluded.data_source,
            },
        )
        self.session.execute(stmt)
        self.session.commit()
        return len(rows)

    # ------------------------------------------------------------------
    # Daily prices
    # ------------------------------------------------------------------

    def ingest_daily_prices(self, ticker: str, start: str = "2010-01-01", end: str | None = None) -> int:
        if yf is None:
            raise RuntimeError("yfinance is required for daily price ingestion")

        stock = self.upsert_stock(ticker)
        df = yf.download(ticker, start=start, end=end, auto_adjust=False, progress=False)
        if df.empty:
            logger.warning(f"No data for {ticker}")
            return 0

        rows = self._build_daily_price_rows(stock.id, df)
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

    def _build_daily_price_rows(self, stock_id: int, df: pd.DataFrame) -> list[dict]:
        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.reset_index()
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]
        df = df.rename(columns={"date": "date_", "adj_close": "adj_close"})

        rows = []
        for _, row in df.iterrows():
            rows.append({
                "stock_id": stock_id,
                "date": row.get("date_", row.get("date")).date() if hasattr(row.get("date_", row.get("date")), "date") else row.get("date_", row.get("date")),
                "open": float(row["open"]) if pd.notna(row.get("open")) else None,
                "high": float(row["high"]) if pd.notna(row.get("high")) else None,
                "low": float(row["low"]) if pd.notna(row.get("low")) else None,
                "close": float(row["close"]) if pd.notna(row.get("close")) else None,
                "adj_close": float(row["adj_close"]) if pd.notna(row.get("adj_close")) else (
                    float(row["close"]) if pd.notna(row.get("close")) else None
                ),
                "volume": int(row["volume"]) if pd.notna(row.get("volume")) else None,
            })
        return rows

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
            **adjusted_ohlc(r.open, r.high, r.low, r.close, r.adj_close),
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

        # Max drawdown and max rise within each week (intra-week high/low vs open)
        weekly["max_drawdown_in_week"] = ((weekly["low"] - weekly["open"]) / weekly["open"]).where(weekly["open"] > 0)
        weekly["max_rise_in_week"] = ((weekly["high"] - weekly["open"]) / weekly["open"]).where(weekly["open"] > 0)

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
                "max_drawdown_in_week": row["max_drawdown_in_week"] if pd.notna(row.get("max_drawdown_in_week")) else None,
                "max_rise_in_week": row["max_rise_in_week"] if pd.notna(row.get("max_rise_in_week")) else None,
            })

        if not insert_rows:
            return 0

        stmt = pg_insert(PriceWeekly).values(insert_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["stock_id", "week_ending"],
            set_={k: getattr(stmt.excluded, k) for k in [
                "open", "high", "low", "close", "volume",
                "weekly_return", "realized_volatility",
                "max_drawdown_in_week", "max_rise_in_week",
            ]},
        )
        self.session.execute(stmt)
        self.session.commit()
        return len(insert_rows)

    # ------------------------------------------------------------------

    def _get_stock(self, ticker: str) -> Stock | None:
        return self.session.execute(select(Stock).where(Stock.ticker == ticker)).scalar_one_or_none()

    def liquidity_filter(self, tickers: list[str], min_daily_volume_usd: float = 5_000_000) -> list[str]:
        """Remove tickers where recent avg daily dollar volume < min_daily_volume_usd.

        Uses the last 63 trading days (~3 months) of data already stored in the DB.
        Tickers with no data at all are kept (not yet ingested).
        """
        filtered = []
        for ticker in tickers:
            stock = self._get_stock(ticker)
            if stock is None:
                filtered.append(ticker)
                continue
            rows = self.session.execute(
                select(PriceDaily)
                .where(PriceDaily.stock_id == stock.id)
                .order_by(PriceDaily.date.desc())
                .limit(63)
            ).scalars().all()
            if not rows:
                filtered.append(ticker)
                continue
            dollar_vols = [
                (r.close or 0) * (r.volume or 0)
                for r in rows
                if r.close and r.volume
            ]
            if not dollar_vols:
                filtered.append(ticker)
                continue
            avg_dollar_vol = sum(dollar_vols) / len(dollar_vols)
            if avg_dollar_vol >= min_daily_volume_usd:
                filtered.append(ticker)
            else:
                logger.info(f"Liquidity filter: excluded {ticker} (avg ${avg_dollar_vol:,.0f}/day)")
        return filtered

    def run_full_ingest(self, tickers: list[str] | None = None, start: str = "2010-01-01"):
        tickers = tickers or settings.mvp_tickers
        for ticker in tickers:
            logger.info(f"Ingesting {ticker}...")
            try:
                self.ingest_daily_prices(ticker, start=start)
                self.resample_weekly(ticker)
            except Exception as e:
                logger.error(f"Failed {ticker}: {e}")
