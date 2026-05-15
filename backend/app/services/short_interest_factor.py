"""
Short Interest Factor

Factors:
  3A. Short interest change (Asquith et al. 2005, Lamont & Stein 2004)
  3B. Days to Cover (DTC)
  3C. Short Squeeze Composite Score
  3D. Sector Short Heatmap

Data sources:
  Primary:  yfinance info (sharesShort, shortRatio, shortPercentOfFloat, floatShares)
  Secondary: FINRA Reg SHO daily short volume (https://cdn.finra.org/equity/regsho/daily/)

Lookahead rule: features use only data stored before week_end_date.
"""
import io
import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.short_interest import ShortInterestData
from app.models.feature import FeatureWeekly

logger = logging.getLogger(__name__)

SHORT_INTEREST_FEATURES = [
    "short_interest_ratio",
    "short_ratio_change",
    "short_squeeze_risk",
    "days_to_cover",
    "dtc_zscore",
    "dtc_change",
    "squeeze_score",
    "sector_short_zscore",
    "relative_to_sector_short",
]

FEATURE_SET_VERSION = "v4"


class ShortInterestService:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest_from_yfinance(self, ticker: str) -> int:
        """Store current short interest snapshot from yfinance info dict."""
        stock = self.session.execute(
            select(Stock).where(Stock.ticker == ticker)
        ).scalar_one_or_none()
        if not stock:
            return 0

        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            info = t.info
        except Exception as e:
            logger.warning("yfinance info failed %s: %s", ticker, e)
            return 0

        today = date.today()
        row = {
            "stock_id": stock.id,
            "report_date": today,
            "short_shares": info.get("sharesShort"),
            "float_shares": info.get("floatShares"),
            "short_ratio": info.get("shortRatio"),  # days to cover
            "short_pct_float": info.get("shortPercentOfFloat"),
            "avg_daily_volume": info.get("averageDailyVolume10Day") or info.get("averageVolume"),
        }

        # Compute short_interest_ratio from shares if pct not available
        if row["short_pct_float"] is None and row["short_shares"] and row["float_shares"]:
            float_shares = float(row["float_shares"])
            if float_shares > 0:
                row["short_pct_float"] = float(row["short_shares"]) / float_shares

        # Clean None → actual None (not string)
        for k in row:
            if row[k] is not None:
                try:
                    row[k] = float(row[k])
                except (TypeError, ValueError):
                    row[k] = None

        stmt = pg_insert(ShortInterestData).values([row])
        stmt = stmt.on_conflict_do_update(
            index_elements=["stock_id", "report_date"],
            set_={
                "short_shares": stmt.excluded.short_shares,
                "float_shares": stmt.excluded.float_shares,
                "short_ratio": stmt.excluded.short_ratio,
                "short_pct_float": stmt.excluded.short_pct_float,
                "avg_daily_volume": stmt.excluded.avg_daily_volume,
            },
        )
        self.session.execute(stmt)
        self.session.commit()
        return 1

    def ingest_from_finra(self, target_date: date | None = None) -> int:
        """
        Download FINRA Reg SHO daily short volume file and store short_volume_ratio
        for all tracked tickers.

        URL: https://cdn.finra.org/equity/regsho/daily/FNRAshvol{YYYYMMDD}.txt
        Format: Symbol|Date|ShortVolume|ShortExemptVolume|TotalVolume|Market
        """
        if target_date is None:
            target_date = date.today() - timedelta(days=1)

        url = f"https://cdn.finra.org/equity/regsho/daily/FNRAshvol{target_date.strftime('%Y%m%d')}.txt"
        try:
            import requests
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            logger.warning("FINRA SHO download failed for %s: %s", target_date, e)
            return 0

        try:
            df = pd.read_csv(io.StringIO(resp.text), sep="|", dtype=str)
            df.columns = [c.strip() for c in df.columns]
            df["ShortVolume"] = pd.to_numeric(df.get("ShortVolume", pd.Series()), errors="coerce")
            df["TotalVolume"] = pd.to_numeric(df.get("TotalVolume", pd.Series()), errors="coerce")
            df = df[df["TotalVolume"] > 0].copy()
            df["short_volume_ratio"] = df["ShortVolume"] / df["TotalVolume"]
            df["Symbol"] = df["Symbol"].str.strip().str.upper()
        except Exception as e:
            logger.warning("FINRA SHO parse failed: %s", e)
            return 0

        # Get all tracked tickers
        stocks = self.session.execute(select(Stock).where(Stock.is_active == True)).scalars().all()
        ticker_to_id = {s.ticker: s.id for s in stocks}

        finra_df = df[df["Symbol"].isin(ticker_to_id)].copy()
        if finra_df.empty:
            return 0

        rows = []
        for _, frow in finra_df.iterrows():
            sid = ticker_to_id.get(frow["Symbol"])
            if sid and pd.notna(frow["short_volume_ratio"]):
                rows.append({
                    "stock_id": sid,
                    "report_date": target_date,
                    "short_volume_ratio": float(frow["short_volume_ratio"]),
                })

        if not rows:
            return 0

        stmt = pg_insert(ShortInterestData).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["stock_id", "report_date"],
            set_={"short_volume_ratio": stmt.excluded.short_volume_ratio},
        )
        self.session.execute(stmt)
        self.session.commit()
        logger.info("FINRA SHO: stored %d short volume records for %s", len(rows), target_date)
        return len(rows)

    # ------------------------------------------------------------------
    # Feature computation
    # ------------------------------------------------------------------

    def compute_features(self, stock_id: int, week_end_date: date) -> dict:
        """
        Return short interest features for a given stock as of week_end_date.
        Uses only records with report_date <= week_end_date.
        """
        null_out = {k: np.nan for k in SHORT_INTEREST_FEATURES if k not in ("squeeze_score", "sector_short_zscore", "relative_to_sector_short")}

        records = self.session.execute(
            select(ShortInterestData)
            .where(
                ShortInterestData.stock_id == stock_id,
                ShortInterestData.report_date <= week_end_date,
            )
            .order_by(ShortInterestData.report_date.desc())
            .limit(4)
        ).scalars().all()

        if not records:
            return {k: np.nan for k in SHORT_INTEREST_FEATURES}

        latest = records[0]
        out: dict = {}

        # Short interest ratio (% of float)
        si_ratio = latest.short_pct_float or (
            (latest.short_shares / latest.float_shares)
            if latest.short_shares and latest.float_shares and latest.float_shares > 0
            else None
        )
        out["short_interest_ratio"] = float(si_ratio) if si_ratio is not None else np.nan

        # Days to cover
        dtc = latest.short_ratio
        out["days_to_cover"] = float(dtc) if dtc is not None else np.nan

        # Short ratio change: current vs ~2 records ago
        out["short_ratio_change"] = np.nan
        out["dtc_change"] = np.nan
        if len(records) >= 2:
            prev = records[1]
            prev_si = prev.short_pct_float
            if prev_si and prev_si > 1e-6 and si_ratio is not None:
                out["short_ratio_change"] = float((si_ratio - prev_si) / prev_si)
            if prev.short_ratio and dtc is not None:
                out["dtc_change"] = float(dtc - prev.short_ratio)

        out["short_squeeze_risk"] = 1.0 if (
            si_ratio is not None and si_ratio > 0.10 and
            pd.notna(out.get("short_ratio_change")) and out["short_ratio_change"] < -0.10
        ) else 0.0

        # DTC z-score: placeholder (cross-sectional normalized in batch)
        out["dtc_zscore"] = np.nan  # filled in compute_cross_sectional_all

        # Squeeze score components (0-4 additive)
        sq = 0
        if si_ratio is not None and si_ratio > 0.10:
            sq += 1
        if pd.notna(out.get("short_ratio_change")) and out["short_ratio_change"] < -0.10:
            sq += 1
        # momentum_12_1 > 0 check must be done externally — add flag here as NaN
        out["squeeze_score"] = float(sq)  # will be incremented in combiner if momentum positive

        # Sector features filled in batch
        out["sector_short_zscore"] = np.nan
        out["relative_to_sector_short"] = np.nan

        return out

    def run_all(self, tickers: list[str]) -> dict:
        results = {}
        for ticker in tickers:
            try:
                results[ticker] = self.ingest_from_yfinance(ticker)
            except Exception as e:
                logger.error("Short interest ingest failed %s: %s", ticker, e)
                results[ticker] = 0
        return results

    # ------------------------------------------------------------------
    # Cross-sectional batch
    # ------------------------------------------------------------------

    def compute_cross_sectional_all(self, tickers: list[str]) -> int:
        """
        After per-stock short interest features are computed, compute:
          - dtc_zscore (cross-universe Z-score of days_to_cover)
          - sector_short_zscore and relative_to_sector_short

        Writes results back to feature_weekly table.
        """
        stocks = self.session.execute(
            select(Stock).where(Stock.ticker.in_(tickers))
        ).scalars().all()
        if not stocks:
            return 0
        stock_by_id = {s.id: s for s in stocks}
        stock_ids = [s.id for s in stocks]

        rows = self.session.execute(
            select(FeatureWeekly).where(
                FeatureWeekly.stock_id.in_(stock_ids),
                FeatureWeekly.feature_name.in_(["short_interest_ratio", "days_to_cover"]),
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
        df["sector"] = df["stock_id"].map(
            lambda sid: getattr(stock_by_id.get(sid), "sector", None) or "Unknown"
        )
        wide = df.pivot_table(
            index=["stock_id", "week_ending", "sector"],
            columns="feature_name",
            values="value",
        ).reset_index()

        out_rows = []
        for week, wdf in wide.groupby("week_ending"):
            # DTC z-score (universe-wide)
            if "days_to_cover" in wdf.columns:
                dtc_col = wdf["days_to_cover"]
                mu = dtc_col.dropna().mean()
                std = dtc_col.dropna().std()
                if std > 1e-6:
                    zscores = (dtc_col - mu) / std
                    for i, row in wdf.iterrows():
                        if pd.notna(dtc_col.iloc[wdf.index.get_loc(i) if hasattr(wdf.index, 'get_loc') else i]):
                            out_rows.append({
                                "stock_id": int(row["stock_id"]),
                                "week_ending": week,
                                "feature_name": "dtc_zscore",
                                "value": float(zscores.iloc[wdf.index.get_loc(i) if hasattr(wdf.index, 'get_loc') else i]),
                                "feature_set_version": FEATURE_SET_VERSION,
                            })

            # Sector short z-score
            if "short_interest_ratio" in wdf.columns:
                for sector, sdf in wdf.groupby("sector"):
                    valid = sdf[sdf["short_interest_ratio"].notna()]
                    if valid.empty:
                        continue
                    sec_mu = valid["short_interest_ratio"].mean()
                    sec_std = valid["short_interest_ratio"].std()
                    for _, srow in valid.iterrows():
                        si = srow["short_interest_ratio"]
                        relative = si - sec_mu
                        z = (si - sec_mu) / sec_std if sec_std > 1e-6 else 0.0
                        out_rows.append({
                            "stock_id": int(srow["stock_id"]),
                            "week_ending": week,
                            "feature_name": "sector_short_zscore",
                            "value": float(z),
                            "feature_set_version": FEATURE_SET_VERSION,
                        })
                        out_rows.append({
                            "stock_id": int(srow["stock_id"]),
                            "week_ending": week,
                            "feature_name": "relative_to_sector_short",
                            "value": float(relative),
                            "feature_set_version": FEATURE_SET_VERSION,
                        })

        if out_rows:
            stmt = pg_insert(FeatureWeekly).values(out_rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["stock_id", "week_ending", "feature_name", "feature_set_version"],
                set_={"value": stmt.excluded.value},
            )
            self.session.execute(stmt)
            self.session.commit()
            logger.info("ShortInterest cross-sectional: %d rows", len(out_rows))
        return len(out_rows)
