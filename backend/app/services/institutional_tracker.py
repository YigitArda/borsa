from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.smallcap_signals import InstitutionalPosition
from app.models.stock import Stock
from app.services.sec_edgar import _SEC_HEADERS

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"


class InstitutionalTrackerService:
    def __init__(self, session: Session):
        self.session = session

    def ingest_ticker(
        self,
        ticker: str,
        lookback_days: int = 120,
        as_of_date: date | None = None,
    ) -> int:
        as_of_date = as_of_date or datetime.now(timezone.utc).date()
        start = as_of_date - timedelta(days=lookback_days)
        stock = self.session.execute(
            select(Stock).where(Stock.ticker == ticker.upper())
        ).scalar_one_or_none()
        if not stock:
            return 0

        try:
            time.sleep(0.15)
            response = requests.get(
                _SEARCH_URL,
                params={
                    "q": f'"{ticker.upper()}"',
                    "forms": "13F-HR",
                    "dateRange": "custom",
                    "startdt": start.isoformat(),
                    "enddt": as_of_date.isoformat(),
                },
                headers=_SEC_HEADERS,
                timeout=20,
            )
            response.raise_for_status()
            hits = list(_iter_hits(response.json()))
        except Exception as exc:
            logger.warning("SEC 13F search failed for %s: %s", ticker, exc)
            return 0

        rows_written = 0
        parsed_rows = []
        for source in sorted(hits, key=lambda item: _hit_filed_date(item) or date.min):
            filed_date = _hit_filed_date(source)
            if filed_date is None:
                continue
            accession = _hit_accession(source)
            filer_cik = _hit_cik(source)
            if not accession or not filer_cik:
                continue
            time.sleep(0.15)
            row = self._parse_13f(filer_cik, accession, stock, filed_date, source)
            if row:
                parsed_rows.append(row)

        for row in parsed_rows:
            self._set_position_change(row)
            self._upsert(row)
            rows_written += 1

        self.session.commit()
        return rows_written

    def _parse_13f(
        self,
        filer_cik: str,
        accession: str,
        stock: Stock,
        report_date: date,
        source: dict,
    ) -> dict | None:
        accession_no_dash = accession.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{int(filer_cik)}/{accession_no_dash}/{accession}.txt"
        try:
            response = requests.get(url, headers=_SEC_HEADERS, timeout=20)
            response.raise_for_status()
        except Exception as exc:
            logger.debug("SEC 13F filing fetch failed for %s/%s: %s", filer_cik, accession, exc)
            return None

        text = response.text
        start = text.find("<informationTable")
        if start < 0:
            start = text.find("<?xml")
        if start < 0:
            return None

        try:
            root = ET.fromstring(text[start:])
        except ET.ParseError:
            return None

        for table in root.iter():
            if _tag_name(table.tag) != "infoTable":
                continue
            issuer = _text(table, "nameOfIssuer") or ""
            cusip = _text(table, "cusip") or ""
            if not _matches_stock(stock, issuer, cusip):
                continue
            shares = _float(_text(_first_descendant(table, "shrsOrPrnAmt"), "sshPrnamt")) or 0.0
            value = (_float(_text(table, "value")) or 0.0) * 1000.0
            return {
                "stock_id": stock.id,
                "filer_cik": str(filer_cik).zfill(10),
                "filer_name": _hit_filer_name(source),
                "report_date": report_date,
                "shares_held": shares,
                "market_value": value,
                "is_new_position": False,
                "prev_shares": None,
                "change_pct": None,
            }
        return None

    def _set_position_change(self, row: dict) -> None:
        previous = self.session.execute(
            select(InstitutionalPosition).where(
                InstitutionalPosition.stock_id == row["stock_id"],
                InstitutionalPosition.filer_cik == row["filer_cik"],
                InstitutionalPosition.report_date < row["report_date"],
            ).order_by(InstitutionalPosition.report_date.desc())
        ).scalars().first()
        prev_shares = previous.shares_held if previous else None
        row["prev_shares"] = prev_shares
        row["is_new_position"] = previous is None or not prev_shares
        if prev_shares and prev_shares > 0:
            row["change_pct"] = round(((row["shares_held"] or 0.0) - prev_shares) / prev_shares * 100.0, 2)

    def _upsert(self, row: dict) -> None:
        existing = self.session.execute(
            select(InstitutionalPosition).where(
                InstitutionalPosition.stock_id == row["stock_id"],
                InstitutionalPosition.filer_cik == row["filer_cik"],
                InstitutionalPosition.report_date == row["report_date"],
            )
        ).scalar_one_or_none()
        if existing:
            for key, value in row.items():
                setattr(existing, key, value)
            return
        self.session.add(InstitutionalPosition(**row))
        self.session.flush()

    def get_smart_money_score(self, stock_id: int, as_of_date: date) -> dict:
        cutoff = as_of_date - timedelta(days=120)
        rows = self.session.execute(
            select(InstitutionalPosition).where(
                InstitutionalPosition.stock_id == stock_id,
                InstitutionalPosition.report_date <= as_of_date,
                InstitutionalPosition.report_date >= cutoff,
            )
        ).scalars().all()

        score = 0.0
        new_positions = 0
        increased = 0
        detail = []
        for row in rows:
            if row.is_new_position:
                score += 30
                new_positions += 1
                detail.append({"filer": row.filer_name, "signal": "new_position", "value": row.market_value or 0.0})
            elif row.change_pct is not None and row.change_pct > 50:
                score += 20
                increased += 1
                detail.append({"filer": row.filer_name, "signal": "increase_50", "change_pct": row.change_pct})
            elif row.change_pct is not None and row.change_pct > 25:
                score += 12
                increased += 1
                detail.append({"filer": row.filer_name, "signal": "increase_25", "change_pct": row.change_pct})

        if new_positions >= 2:
            score *= 1.3
            detail.append({"signal": "multiple_new_positions"})

        return {
            "score": min(round(float(score), 2), 30.0),
            "new_positions": new_positions,
            "increased": increased,
            "detail": detail,
        }

    def run_all(
        self,
        tickers: list[str],
        lookback_days: int = 120,
        as_of_date: date | None = None,
    ) -> dict[str, int]:
        results = {}
        for ticker in tickers:
            try:
                results[ticker] = self.ingest_ticker(ticker, lookback_days=lookback_days, as_of_date=as_of_date)
            except Exception as exc:
                logger.warning("Institutional ingest failed for %s: %s", ticker, exc)
                results[ticker] = 0
        return results


def _iter_hits(data: dict):
    hits = data.get("hits", {})
    if isinstance(hits, dict):
        for item in hits.get("hits", []):
            yield item.get("_source", item)
    elif isinstance(hits, list):
        for item in hits:
            yield item.get("_source", item) if isinstance(item, dict) else {}


def _hit_filed_date(source: dict) -> date | None:
    value = source.get("file_date") or source.get("filedAt") or source.get("filingDate") or source.get("filed")
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _hit_accession(source: dict) -> str | None:
    value = source.get("adsh") or source.get("accessionNo") or source.get("accession_number") or source.get("accessionNumber")
    return str(value).strip() if value else None


def _hit_cik(source: dict) -> str | None:
    value = source.get("ciks") or source.get("cik") or source.get("cik_str")
    if isinstance(value, list):
        value = value[0] if value else None
    return str(value).zfill(10) if value else None


def _hit_filer_name(source: dict) -> str | None:
    value = source.get("display_names") or source.get("companyName") or source.get("entity") or source.get("name")
    if isinstance(value, list):
        value = value[0] if value else None
    return str(value) if value else None


def _tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first_descendant(element: ET.Element | None, name: str) -> ET.Element | None:
    if element is None:
        return None
    for child in element.iter():
        if _tag_name(child.tag) == name:
            return child
    return None


def _text(element: ET.Element | None, name: str) -> str | None:
    child = _first_descendant(element, name)
    if child is None or child.text is None:
        return None
    return child.text.strip()


def _float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _matches_stock(stock: Stock, issuer: str, cusip: str) -> bool:
    ticker = (stock.ticker or "").upper()
    issuer_text = issuer.upper()
    if ticker and (ticker in issuer_text or ticker in cusip.upper()):
        return True
    name = (stock.name or "").upper()
    if not name:
        return False
    words = [word for word in name.replace(".", " ").replace(",", " ").split() if len(word) > 2]
    if len(words) >= 2 and all(word in issuer_text for word in words[:2]):
        return True
    return bool(words and words[0] in issuer_text and ticker in issuer_text)
