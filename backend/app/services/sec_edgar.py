"""
SEC EDGAR filing date lookup.

For each quarterly/annual report, the actual public filing date is fetched from
SEC EDGAR's free API. This gives us true point-in-time dates so the backtest
never uses financial data before it was publicly available.

Rate limit: SEC asks for <= 10 req/s, we use 0.15s sleep between calls.
"""
import logging
import time
from datetime import date, timedelta
from functools import lru_cache

import requests

logger = logging.getLogger(__name__)

_SEC_HEADERS = {"User-Agent": "BorsaResearch admin@borsaresearch.local"}
_CIK_MAP: dict[str, str] = {}  # ticker -> zero-padded CIK, loaded once
_CIK_MAP_LOADED = False

ANNUAL_FILING_LAG_DAYS = 75    # conservative: large filer 60d, small filer 90d
QUARTERLY_FILING_LAG_DAYS = 45 # conservative: large filer 40d, small filer 45d


def _load_cik_map() -> None:
    global _CIK_MAP_LOADED
    if _CIK_MAP_LOADED:
        return
    try:
        r = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=_SEC_HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        for entry in r.json().values():
            ticker = entry.get("ticker", "").upper()
            cik = str(entry.get("cik_str", "")).zfill(10)
            if ticker:
                _CIK_MAP[ticker] = cik
        _CIK_MAP_LOADED = True
        logger.info("SEC CIK map loaded: %d tickers", len(_CIK_MAP))
    except Exception as exc:
        logger.warning("SEC CIK map load failed: %s", exc)


def get_cik(ticker: str) -> str | None:
    _load_cik_map()
    return _CIK_MAP.get(ticker.upper())


def estimate_filing_date(fiscal_period_end: date, is_annual: bool = False) -> date:
    """
    Conservative heuristic when real filing date is unavailable.
    We add extra buffer to avoid any lookahead — it's better to exclude
    a few valid data points than to leak future information.
    """
    lag = ANNUAL_FILING_LAG_DAYS if is_annual else QUARTERLY_FILING_LAG_DAYS
    return fiscal_period_end + timedelta(days=lag)


def get_filing_dates(ticker: str) -> dict[date, date]:
    """
    Fetch all 10-Q and 10-K filing dates for a ticker from SEC EDGAR.

    Returns:
        {fiscal_period_end: filing_date} — the date the report became public.

    Falls back to empty dict on any error; caller should use estimate_filing_date().
    """
    cik = get_cik(ticker)
    if not cik:
        logger.debug("No CIK found for %s, will use heuristic filing dates", ticker)
        return {}

    try:
        time.sleep(0.15)  # respect SEC rate limit
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        r = requests.get(url, headers=_SEC_HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.warning("SEC EDGAR fetch failed for %s (CIK %s): %s", ticker, cik, exc)
        return {}

    result: dict[date, date] = {}

    def _parse_filings(filings: dict) -> None:
        forms = filings.get("form", [])
        filing_dates = filings.get("filingDate", [])
        report_dates = filings.get("reportDate", [])

        for form, filing_str, report_str in zip(forms, filing_dates, report_dates):
            if form not in ("10-Q", "10-K", "10-K/A", "10-Q/A"):
                continue
            try:
                period_end = date.fromisoformat(report_str)
                filing_date = date.fromisoformat(filing_str)
                # Keep earliest filing date if there's an amendment (10-K/A)
                if period_end not in result or filing_date < result[period_end]:
                    result[period_end] = filing_date
            except (ValueError, TypeError):
                continue

    recent = data.get("filings", {}).get("recent", {})
    _parse_filings(recent)

    # Also check older filings pages if they exist
    for page in data.get("filings", {}).get("files", []):
        try:
            time.sleep(0.15)
            page_url = f"https://data.sec.gov/submissions/{page['name']}"
            pr = requests.get(page_url, headers=_SEC_HEADERS, timeout=15)
            pr.raise_for_status()
            _parse_filings(pr.json())
        except Exception as exc:
            logger.debug("SEC older filings page failed for %s: %s", ticker, exc)

    logger.info("SEC EDGAR: %s → %d filing dates fetched", ticker, len(result))
    return result


def get_as_of_date(
    ticker: str,
    fiscal_period_end: date,
    filing_dates: dict[date, date] | None = None,
    is_annual: bool = False,
) -> date:
    """
    Return the public availability date for a financial report.

    If filing_dates dict is provided (pre-fetched for the ticker), uses it.
    Otherwise falls back to the conservative heuristic.
    """
    if filing_dates:
        # Try exact match first, then ±15 day window
        if fiscal_period_end in filing_dates:
            return filing_dates[fiscal_period_end]
        for d, fd in filing_dates.items():
            if abs((d - fiscal_period_end).days) <= 15:
                return fd

    return estimate_filing_date(fiscal_period_end, is_annual=is_annual)
