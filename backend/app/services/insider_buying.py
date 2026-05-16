from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.smallcap_signals import InsiderTransaction
from app.models.stock import Stock
from app.services.sec_edgar import _SEC_HEADERS, _load_cik_map, get_cik

logger = logging.getLogger(__name__)

SEC_HEADERS = _SEC_HEADERS

_TITLE_SCORES = {
    "chief executive": 40,
    "ceo": 40,
    "chief financial": 25,
    "cfo": 25,
    "chief operating": 25,
    "coo": 25,
    "chief technology": 25,
    "cto": 25,
    "chief": 25,
    "president": 25,
    "director": 15,
    "chair": 15,
}

_SALARY_ESTIMATES = {
    "chief executive": 1_000_000,
    "ceo": 1_000_000,
    "chief financial": 600_000,
    "cfo": 600_000,
    "chief operating": 600_000,
    "coo": 600_000,
    "chief technology": 500_000,
    "cto": 500_000,
    "chief": 500_000,
    "president": 500_000,
    "director": 150_000,
    "chair": 300_000,
}


def _title_score(title: str | None) -> int:
    text = (title or "").lower()
    for key, score in _TITLE_SCORES.items():
        if key in text:
            return score
    return 5


def _salary_estimate(title: str | None) -> int:
    text = (title or "").lower()
    for key, value in _SALARY_ESTIMATES.items():
        if key in text:
            return value
    return 100_000


def _is_open_market(transaction_code: str | None) -> bool:
    return transaction_code == "P"


def _is_sell(transaction_code: str | None) -> bool:
    return transaction_code == "S"


def _tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first_descendant(element: ET.Element, name: str) -> ET.Element | None:
    for child in element.iter():
        if _tag_name(child.tag) == name:
            return child
    return None


def _text(element: ET.Element | None, name: str) -> str | None:
    if element is None:
        return None
    child = _first_descendant(element, name)
    if child is None or child.text is None:
        return None
    return child.text.strip()


def _nested_text(element: ET.Element, parent: str, child_name: str = "value") -> str | None:
    parent_element = _first_descendant(element, parent)
    return _text(parent_element, child_name)


def _float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


class InsiderBuyingService:
    def __init__(self, session: Session):
        self.session = session

    def ingest_ticker(
        self,
        ticker: str,
        lookback_days: int = 90,
        as_of_date: date | None = None,
    ) -> int:
        as_of_date = as_of_date or datetime.now(timezone.utc).date()
        cik = get_cik(ticker)
        if not cik:
            return 0

        stock = self.session.execute(
            select(Stock).where(Stock.ticker == ticker.upper())
        ).scalar_one_or_none()
        if not stock:
            return 0

        data = self._fetch_submissions(cik)
        if not data:
            return 0

        recent = data.get("filings", {}).get("recent", {})
        cutoff = as_of_date - timedelta(days=lookback_days)
        rows_written = 0

        for form, filed_raw, accession in zip(
            recent.get("form", []),
            recent.get("filingDate", []),
            recent.get("accessionNumber", []),
        ):
            if form != "4":
                continue
            try:
                filed_date = date.fromisoformat(filed_raw)
            except (TypeError, ValueError):
                continue
            if filed_date < cutoff or filed_date > as_of_date:
                continue
            time.sleep(0.15)
            for row in self._parse_form4(cik, accession, stock.id, filed_date):
                self._upsert(row)
                rows_written += 1

        self.session.commit()
        return rows_written

    def _fetch_submissions(self, cik: str) -> dict | None:
        try:
            time.sleep(0.15)
            url = f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json"
            response = requests.get(url, headers=SEC_HEADERS, timeout=20)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            logger.warning("SEC Form 4 submissions fetch failed for CIK %s: %s", cik, exc)
            return None

    def _parse_form4(self, cik: str, accession: str, stock_id: int, filed_date: date) -> list[dict]:
        accession_no_dash = accession.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_no_dash}/{accession}.txt"
        response = requests.get(url, headers=SEC_HEADERS, timeout=20)
        response.raise_for_status()
        text = response.text
        start = text.find("<?xml")
        if start < 0:
            start = text.find("<ownershipDocument")
        if start < 0:
            return []

        root = ET.fromstring(text[start:])
        owner = _first_descendant(root, "reportingOwner")
        relationship = _first_descendant(owner, "reportingOwnerRelationship") if owner is not None else None
        insider_name = _text(owner, "rptOwnerName") or ""
        insider_title = _text(relationship, "officerTitle")
        if not insider_title and _text(relationship, "isDirector") in {"1", "true", "True"}:
            insider_title = "Director"

        rows = []
        for tx in root.iter():
            if _tag_name(tx.tag) != "nonDerivativeTransaction":
                continue
            code = _text(tx, "transactionCode")
            is_buy = _is_open_market(code)
            is_sell = _is_sell(code)
            if not is_buy and not is_sell:
                continue
            shares = _float(_nested_text(tx, "transactionShares")) or 0.0
            price = _float(_nested_text(tx, "transactionPricePerShare")) or 0.0
            ownership_after = _float(_nested_text(tx, "sharesOwnedFollowingTransaction"))
            rows.append(
                {
                    "stock_id": stock_id,
                    "filed_date": filed_date,
                    "insider_name": insider_name,
                    "insider_title": insider_title,
                    "transaction_type": "buy" if is_buy else "sell",
                    "shares": shares,
                    "price_per_share": price,
                    "total_value": shares * price,
                    "is_open_market": is_buy,
                    "ownership_after": ownership_after,
                    "source": "sec_form4",
                }
            )
        return rows

    def _upsert(self, row: dict) -> None:
        existing = self.session.execute(
            select(InsiderTransaction).where(
                InsiderTransaction.stock_id == row["stock_id"],
                InsiderTransaction.filed_date == row["filed_date"],
                InsiderTransaction.insider_name == row["insider_name"],
                InsiderTransaction.transaction_type == row["transaction_type"],
            )
        ).scalar_one_or_none()
        if existing:
            for key, value in row.items():
                setattr(existing, key, value)
            return
        self.session.add(InsiderTransaction(**row))

    def get_insider_score(self, stock_id: int, as_of_date: date, lookback_days: int = 90) -> dict:
        cutoff = as_of_date - timedelta(days=lookback_days)
        rows = self.session.execute(
            select(InsiderTransaction).where(
                InsiderTransaction.stock_id == stock_id,
                InsiderTransaction.filed_date <= as_of_date,
                InsiderTransaction.filed_date >= cutoff,
            )
        ).scalars().all()

        buys = [row for row in rows if row.transaction_type == "buy"]
        sells = [row for row in rows if row.transaction_type == "sell"]
        buy_value = sum(row.total_value or 0.0 for row in buys)
        sell_value = sum(row.total_value or 0.0 for row in sells)

        if sell_value > buy_value * 0.5:
            return {
                "score": 0.0,
                "buys": len(buys),
                "sells": len(sells),
                "detail": ["insider_selling_dominated"],
            }

        buy_counts = Counter(row.insider_name for row in buys)
        week_to_names: dict[str, set[str]] = defaultdict(set)
        for row in buys:
            week_to_names[row.filed_date.strftime("%G-%V")].add(row.insider_name)

        score = 0.0
        detail = []
        for row in buys:
            row_score = float(_title_score(row.insider_title))
            if row.is_open_market:
                row_score *= 1.3
            if (row.total_value or 0.0) > _salary_estimate(row.insider_title):
                row_score *= 2.0
            if buy_counts[row.insider_name] >= 2:
                row_score *= 1.5
            score += row_score
            detail.append(
                {
                    "insider": row.insider_name,
                    "title": row.insider_title,
                    "filed_date": row.filed_date.isoformat(),
                    "value": row.total_value or 0.0,
                    "score": round(row_score, 2),
                }
            )

        if any(len(names) >= 2 for names in week_to_names.values()):
            score *= 1.4
            detail.append({"signal": "multiple_insiders_same_week"})

        return {
            "score": round(float(score), 2),
            "buys": len(buys),
            "sells": len(sells),
            "detail": detail,
        }

    def run_all(
        self,
        tickers: list[str],
        lookback_days: int = 90,
        as_of_date: date | None = None,
    ) -> dict[str, int]:
        _load_cik_map()
        results = {}
        for ticker in tickers:
            try:
                results[ticker] = self.ingest_ticker(ticker, lookback_days=lookback_days, as_of_date=as_of_date)
            except Exception as exc:
                logger.warning("Insider ingest failed for %s: %s", ticker, exc)
                results[ticker] = 0
        return results
