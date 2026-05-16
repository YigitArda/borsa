from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.financial import FinancialMetric
from app.models.smallcap_signals import GovernmentContract
from app.models.stock import Stock

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
_MIN_AWARD_AMOUNT = 1_000_000.0


class GovernmentContractsService:
    def __init__(self, session: Session):
        self.session = session

    def ingest_ticker(self, ticker: str, start: date, end: date) -> int:
        stock = self.session.execute(
            select(Stock).where(Stock.ticker == ticker.upper())
        ).scalar_one_or_none()
        if not stock:
            return 0

        queries = []
        if stock.name:
            queries.append(stock.name)
        queries.append(ticker.upper())

        rows_written = 0
        seen: set[str] = set()
        for query in dict.fromkeys(queries):
            time.sleep(0.5)
            payload = {
                "filters": {
                    "recipient_search_text": [query],
                    "award_type_codes": ["A", "B", "C", "D"],
                    "time_period": [{"start_date": start.isoformat(), "end_date": end.isoformat()}],
                },
                "fields": [
                    "Award ID",
                    "Recipient Name",
                    "Award Amount",
                    "Award Date",
                    "Awarding Agency",
                    "Description",
                    "Period of Performance End Date",
                ],
                "limit": 100,
                "page": 1,
            }
            try:
                response = requests.post(_BASE_URL, json=payload, timeout=30)
                response.raise_for_status()
                results = response.json().get("results", [])
            except Exception as exc:
                logger.warning("USASpending fetch failed for %s/%s: %s", ticker, query, exc)
                continue

            for item in results:
                award_id = str(item.get("Award ID") or "").strip()
                if not award_id or award_id in seen:
                    continue
                amount = _parse_amount(item.get("Award Amount"))
                if amount is None or amount <= _MIN_AWARD_AMOUNT:
                    continue
                award_date = _parse_date(item.get("Award Date") or item.get("Start Date"))
                if award_date is None or award_date < start or award_date > end:
                    continue
                row = {
                    "stock_id": stock.id,
                    "award_id": award_id,
                    "award_date": award_date,
                    "awarding_agency": item.get("Awarding Agency"),
                    "recipient_name": item.get("Recipient Name"),
                    "award_amount": amount,
                    "description": item.get("Description"),
                    "contract_type": "contract",
                    "performance_end_date": _parse_date(item.get("Period of Performance End Date") or item.get("End Date")),
                }
                self._upsert(row)
                seen.add(award_id)
                rows_written += 1

        self.session.commit()
        return rows_written

    def _upsert(self, row: dict) -> None:
        existing = self.session.execute(
            select(GovernmentContract).where(
                GovernmentContract.stock_id == row["stock_id"],
                GovernmentContract.award_id == row["award_id"],
            )
        ).scalar_one_or_none()
        if existing:
            for key, value in row.items():
                setattr(existing, key, value)
            return
        self.session.add(GovernmentContract(**row))

    def get_contract_score(self, stock_id: int, as_of_date: date, lookback_days: int = 90) -> dict:
        cutoff = as_of_date - timedelta(days=lookback_days)
        rows = self.session.execute(
            select(GovernmentContract).where(
                GovernmentContract.stock_id == stock_id,
                GovernmentContract.award_date <= as_of_date,
                GovernmentContract.award_date >= cutoff,
            )
        ).scalars().all()

        total_value = sum(row.award_amount or 0.0 for row in rows)
        market_cap = _latest_metric(self.session, stock_id, "market_cap", as_of_date)
        score = 0.0
        if market_cap and market_cap > 0:
            ratio = total_value / market_cap
            if ratio > 0.10:
                score += 20
            elif ratio > 0.05:
                score += 12
            elif ratio > 0.02:
                score += 6

        new_agencies = 0
        for agency in {row.awarding_agency for row in rows if row.awarding_agency}:
            previous = self.session.execute(
                select(GovernmentContract).where(
                    GovernmentContract.stock_id == stock_id,
                    GovernmentContract.awarding_agency == agency,
                    GovernmentContract.award_date < cutoff,
                ).limit(1)
            ).scalar_one_or_none()
            if previous is None:
                new_agencies += 1
        if new_agencies:
            score += 5

        return {
            "score": min(round(float(score), 2), 20.0),
            "total_value": round(float(total_value), 2),
            "contract_count": len(rows),
            "detail": [
                {
                    "award_id": row.award_id,
                    "agency": row.awarding_agency,
                    "amount": row.award_amount or 0.0,
                    "award_date": row.award_date.isoformat(),
                }
                for row in rows
            ],
        }

    def get_business_score(self, stock_id: int, as_of_date: date, lookback_days: int = 90) -> dict:
        return self.get_contract_score(stock_id, as_of_date, lookback_days)

    def run_all(
        self,
        tickers: list[str],
        lookback_days: int = 90,
        as_of_date: date | None = None,
    ) -> dict[str, int]:
        as_of_date = as_of_date or datetime.now(timezone.utc).date()
        start = as_of_date - timedelta(days=lookback_days)
        results = {}
        for ticker in tickers:
            try:
                results[ticker] = self.ingest_ticker(ticker, start=start, end=as_of_date)
            except Exception as exc:
                logger.warning("USASpending ingest failed for %s: %s", ticker, exc)
                results[ticker] = 0
        return results


GovernmentContractService = GovernmentContractsService


def _latest_metric(session: Session, stock_id: int, metric_name: str, as_of_date: date) -> float | None:
    row = session.execute(
        select(FinancialMetric).where(
            FinancialMetric.stock_id == stock_id,
            FinancialMetric.metric_name == metric_name,
            FinancialMetric.as_of_date <= as_of_date,
        ).order_by(FinancialMetric.as_of_date.desc())
    ).scalars().first()
    return row.value if row else None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19] if "T" in text else text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(value) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None
