from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.financial import FinancialMetric
from app.models.news import NewsArticle
from app.models.price import PriceDaily
from app.models.regime import MarketRegime
from app.models.short_interest import ShortInterestData
from app.models.smallcap_signals import InsiderTransaction, SmallCapRadarResult
from app.models.stock import Stock
from app.services.government_contracts import GovernmentContractsService
from app.services.insider_buying import InsiderBuyingService
from app.services.institutional_tracker import InstitutionalTrackerService
from app.services.regime_detection import RegimeDetector
from app.services.short_interest_factor import ShortInterestService

logger = logging.getLogger(__name__)

SECTOR_MULTIPLIERS = {
    "Industrials": 1.4,
    "Energy": 1.3,
    "Technology": 1.1,
    "Healthcare": 0.7,
    "Consumer Cyclical": 0.8,
    "Basic Materials": 0.6,
}

REGIME_MULTIPLIERS = {
    "BULL": 1.0,
    "NEUTRAL": 0.85,
    "BEAR": 0.5,
}

_US_EXCHANGES = {"NASDAQ", "NYSE", "NYSEARCA", "AMEX", "NYSEAMERICAN", "NMS", "NYQ", "ASE"}


class SmallCapScreener:
    def __init__(self, session: Session):
        self.session = session
        self.insider = InsiderBuyingService(session)
        self.contracts = GovernmentContractsService(session)
        self.institutions = InstitutionalTrackerService(session)
        self.short_interest = ShortInterestService(session)
        self.regime = RegimeDetector(session)

    def scan_universe(self) -> list[str]:
        yf_symbols = self._scan_yfinance_universe()
        query = select(Stock).where(
            Stock.is_active == True,
            Stock.delisting_date.is_(None),
        )
        if yf_symbols:
            query = query.where(Stock.ticker.in_(yf_symbols))
        else:
            query = query.where(Stock.exchange.in_(_US_EXCHANGES))
        rows = self.session.execute(query.order_by(Stock.ticker).limit(500)).scalars().all()
        return [row.ticker for row in rows]

    def _scan_yfinance_universe(self) -> list[str]:
        try:
            import yfinance as yf

            equity_query = getattr(yf, "EquityQuery", None)
            screen = getattr(yf, "screen", None)
            if equity_query is None or screen is None:
                return []
            query = equity_query(
                "and",
                [
                    equity_query("is-in", ["exchange", "NMS", "NYQ", "ASE"]),
                    equity_query("btwn", ["intradaymarketcap", 50_000_000, 5_000_000_000]),
                ],
            )
            response = screen(query, count=500)
            quotes = response.get("quotes", []) if isinstance(response, dict) else []
            symbols = []
            for quote in quotes:
                symbol = quote.get("symbol")
                market_cap = quote.get("intradaymarketcap") or quote.get("marketCap")
                price = quote.get("regularMarketPrice") or quote.get("regularMarketPreviousClose")
                volume = quote.get("regularMarketVolume") or quote.get("averageDailyVolume3Month")
                dollar_volume = price * volume if price and volume else None
                if not symbol:
                    continue
                if market_cap is not None and not 50_000_000 <= market_cap <= 5_000_000_000:
                    continue
                if dollar_volume is not None and dollar_volume < 200_000:
                    continue
                symbols.append(symbol)
            return symbols
        except Exception as exc:
            logger.debug("yfinance small-cap universe scan failed: %s", exc)
            return []

    def is_eliminated(self, ticker: str, as_of_date: date) -> tuple[bool, str | None]:
        stock = self._stock(ticker)
        if not stock:
            return True, "stock_not_found"

        dollar_volume = self._average_dollar_volume(stock.id, as_of_date)
        if dollar_volume is not None and dollar_volume < 300_000:
            return True, "insufficient_liquidity"

        market_cap = self._latest_metric(stock.id, "market_cap", as_of_date)
        if market_cap is not None and market_cap < 50_000_000:
            return True, "too_small"
        if market_cap is not None and market_cap > 5_000_000_000:
            return True, "too_large"

        buy_value, sell_value = self._insider_buy_sell_values(stock.id, as_of_date)
        if sell_value > buy_value * 0.5:
            return True, "insider_selling"

        dilution = self._dilution_pct(stock.id, as_of_date)
        if dilution is not None and dilution > 15:
            return True, "dilution_risk"

        if self._has_regulatory_risk(stock, as_of_date):
            return True, "regulatory_risk"

        if self._has_bankruptcy_risk(stock.id, as_of_date):
            return True, "bankruptcy_risk"

        concentration = self._customer_concentration(stock.id, as_of_date)
        if concentration is not None and concentration > 70:
            return True, "customer_concentration"

        return False, None

    def score_ticker(self, ticker: str, as_of_date: date) -> SmallCapRadarResult:
        stock = self._stock(ticker)
        if not stock:
            raise ValueError(f"unknown ticker: {ticker}")

        regime_label, regime_multiplier, _ = self.get_regime_context(as_of_date)
        eliminated, reason = self.is_eliminated(ticker, as_of_date)
        if eliminated:
            return self._persist_result(
                stock=stock,
                as_of_date=as_of_date,
                total_score=0.0,
                insider_score=0.0,
                smart_money_score=0.0,
                business_score=0.0,
                structural_score=0.0,
                sector_multiplier=SECTOR_MULTIPLIERS.get(stock.sector or "", 1.0),
                regime_multiplier=regime_multiplier,
                signals=[],
                eliminated=True,
                reason=reason,
            )

        insider = self.insider.get_insider_score(stock.id, as_of_date)
        smart_money = self.institutions.get_smart_money_score(stock.id, as_of_date)
        business = self.contracts.get_contract_score(stock.id, as_of_date)
        structural_score, structural_signals = self._structural_score(stock.id, as_of_date)

        sector_multiplier = SECTOR_MULTIPLIERS.get(stock.sector or "", 1.0)
        raw_score = (
            insider["score"]
            + smart_money["score"]
            + business["score"]
            + structural_score
        )
        total_score = min(100.0, raw_score * sector_multiplier * regime_multiplier)

        signals = []
        if insider["buys"] > 0:
            signals.append({"type": "insider", "detail": insider["detail"]})
        if smart_money["new_positions"] > 0 or smart_money["increased"] > 0:
            signals.append({"type": "smart_money", "detail": smart_money["detail"]})
        if business["contract_count"] > 0:
            signals.append({"type": "government_contracts", "detail": business["detail"]})
        signals.extend(structural_signals)

        return self._persist_result(
            stock=stock,
            as_of_date=as_of_date,
            total_score=round(float(total_score), 2),
            insider_score=round(float(insider["score"]), 2),
            smart_money_score=round(float(smart_money["score"]), 2),
            business_score=round(float(business["score"]), 2),
            structural_score=round(float(structural_score), 2),
            sector_multiplier=sector_multiplier,
            regime_multiplier=regime_multiplier,
            signals=signals,
            eliminated=False,
            reason=None,
        )

    def run_scan(
        self,
        as_of_date: date,
        top_n: int = 5,
        tickers: list[str] | None = None,
    ) -> list[dict]:
        regime_label, _, vix = self.get_regime_context(as_of_date)
        if vix is not None and vix > 30:
            return []

        results = []
        for ticker in tickers or self.scan_universe():
            try:
                result = self.score_ticker(ticker, as_of_date)
            except Exception as exc:
                logger.warning("Small-cap score failed for %s: %s", ticker, exc)
                continue
            if result.eliminated or (result.total_score or 0.0) < 50:
                continue
            if regime_label == "BEAR" and (result.total_score or 0.0) <= 90:
                continue
            results.append(result)

        results.sort(key=lambda item: item.total_score or 0.0, reverse=True)
        return [
            self._report_row(rank, result, regime_label, as_of_date)
            for rank, result in enumerate(results[:top_n], start=1)
        ]

    def get_regime_context(self, as_of_date: date) -> tuple[str, float, float | None]:
        vix, _ = self.regime.compute_vix_regime(as_of_date)
        row = self.session.execute(
            select(MarketRegime).where(
                MarketRegime.week_ending <= as_of_date,
            ).order_by(MarketRegime.week_ending.desc())
        ).scalars().first()
        if row:
            label = _normalize_regime(row.regime_type)
            return label, REGIME_MULTIPLIERS.get(label, 0.85), vix if vix is not None else row.vix_level

        try:
            regime_type, _ = self.regime.classify_regime(
                spy_200ma_ratio=self.regime.compute_spy_200ma_ratio(as_of_date),
                vix_level=vix,
                vix_change=self.regime.compute_vix_regime(as_of_date)[1],
                nasdaq_spy_ratio=self.regime.compute_nasdaq_spy_ratio(as_of_date),
                market_breadth=self.regime.compute_market_breadth(as_of_date),
                yield_trend=self.regime.compute_yield_trend(as_of_date),
                sector_rotation_score=self.regime.compute_sector_rotation(as_of_date),
            )
            label = _normalize_regime(regime_type)
        except Exception as exc:
            logger.debug("Regime context fallback for %s: %s", as_of_date, exc)
            label = "NEUTRAL"
        return label, REGIME_MULTIPLIERS.get(label, 0.85), vix

    def _persist_result(
        self,
        stock: Stock,
        as_of_date: date,
        total_score: float,
        insider_score: float,
        smart_money_score: float,
        business_score: float,
        structural_score: float,
        sector_multiplier: float,
        regime_multiplier: float,
        signals: list,
        eliminated: bool,
        reason: str | None,
    ) -> SmallCapRadarResult:
        row = self.session.execute(
            select(SmallCapRadarResult).where(
                SmallCapRadarResult.stock_id == stock.id,
                SmallCapRadarResult.scan_date == as_of_date,
            )
        ).scalar_one_or_none()
        values = {
            "stock_id": stock.id,
            "scan_date": as_of_date,
            "total_score": total_score,
            "insider_score": insider_score,
            "smart_money_score": smart_money_score,
            "business_score": business_score,
            "structural_score": structural_score,
            "sector_multiplier": sector_multiplier,
            "regime_multiplier": regime_multiplier,
            "signals_triggered": signals,
            "eliminated": eliminated,
            "elimination_reason": reason,
        }
        if row:
            for key, value in values.items():
                setattr(row, key, value)
        else:
            row = SmallCapRadarResult(**values)
            self.session.add(row)
        self.session.flush()
        return row

    def _report_row(self, rank: int, result: SmallCapRadarResult, regime: str, scan_date: date) -> dict:
        stock = self.session.get(Stock, result.stock_id)
        return {
            "rank": rank,
            "ticker": stock.ticker if stock else None,
            "company_name": stock.name if stock else None,
            "sector": stock.sector if stock else None,
            "market_cap": self._latest_metric(result.stock_id, "market_cap", scan_date),
            "total_score": result.total_score,
            "insider_score": result.insider_score,
            "smart_money_score": result.smart_money_score,
            "business_score": result.business_score,
            "structural_score": result.structural_score,
            "signals": result.signals_triggered,
            "elimination_reason": None,
            "regime": regime,
            "scan_date": scan_date.isoformat(),
        }

    def _stock(self, ticker: str) -> Stock | None:
        return self.session.execute(
            select(Stock).where(Stock.ticker == ticker.upper())
        ).scalar_one_or_none()

    def _average_dollar_volume(self, stock_id: int, as_of_date: date, lookback_days: int = 20) -> float | None:
        rows = self.session.execute(
            select(PriceDaily).where(
                PriceDaily.stock_id == stock_id,
                PriceDaily.date <= as_of_date,
                PriceDaily.date >= as_of_date - timedelta(days=lookback_days * 2),
            ).order_by(PriceDaily.date.desc()).limit(lookback_days)
        ).scalars().all()
        values = [
            (row.close or row.adj_close or 0.0) * (row.volume or 0)
            for row in rows
            if (row.close or row.adj_close) and row.volume
        ]
        return sum(values) / len(values) if values else None

    def _latest_metric(self, stock_id: int, metric_name: str, as_of_date: date) -> float | None:
        row = self.session.execute(
            select(FinancialMetric).where(
                FinancialMetric.stock_id == stock_id,
                FinancialMetric.metric_name == metric_name,
                FinancialMetric.as_of_date <= as_of_date,
            ).order_by(FinancialMetric.as_of_date.desc(), FinancialMetric.fiscal_period_end.desc())
        ).scalars().first()
        return row.value if row else None

    def _metric_history(self, stock_id: int, metric_name: str, as_of_date: date, limit: int = 2) -> list[FinancialMetric]:
        return list(
            self.session.execute(
                select(FinancialMetric).where(
                    FinancialMetric.stock_id == stock_id,
                    FinancialMetric.metric_name == metric_name,
                    FinancialMetric.as_of_date <= as_of_date,
                ).order_by(FinancialMetric.as_of_date.desc(), FinancialMetric.fiscal_period_end.desc()).limit(limit)
            ).scalars().all()
        )

    def _insider_buy_sell_values(self, stock_id: int, as_of_date: date) -> tuple[float, float]:
        cutoff = as_of_date - timedelta(days=90)
        rows = self.session.execute(
            select(InsiderTransaction).where(
                InsiderTransaction.stock_id == stock_id,
                InsiderTransaction.filed_date <= as_of_date,
                InsiderTransaction.filed_date >= cutoff,
            )
        ).scalars().all()
        buy_value = sum(row.total_value or 0.0 for row in rows if row.transaction_type == "buy")
        sell_value = sum(row.total_value or 0.0 for row in rows if row.transaction_type == "sell")
        return buy_value, sell_value

    def _dilution_pct(self, stock_id: int, as_of_date: date) -> float | None:
        latest = self._latest_metric(stock_id, "shares_outstanding", as_of_date)
        old_row = self.session.execute(
            select(FinancialMetric).where(
                FinancialMetric.stock_id == stock_id,
                FinancialMetric.metric_name == "shares_outstanding",
                FinancialMetric.as_of_date <= as_of_date - timedelta(days=180),
            ).order_by(FinancialMetric.as_of_date.desc())
        ).scalars().first()
        if latest is None or old_row is None or not old_row.value:
            return None
        return (latest - old_row.value) / old_row.value * 100.0

    def _has_regulatory_risk(self, stock: Stock, as_of_date: date) -> bool:
        start = datetime.combine(as_of_date - timedelta(days=180), time.min)
        end = datetime.combine(as_of_date, time.max)
        rows = self.session.execute(
            select(NewsArticle).where(
                NewsArticle.published_at >= start,
                NewsArticle.published_at <= end,
            ).limit(500)
        ).scalars().all()
        keywords = ("sec enforcement", "wells notice", "subpoena", "investigation")
        ticker = stock.ticker.upper()
        for row in rows:
            mentions = [str(item).upper() for item in (row.ticker_mentions or [])]
            text = f"{row.headline or ''} {row.body_excerpt or ''}".lower()
            if ticker in mentions and any(keyword in text for keyword in keywords):
                return True
        return False

    def _has_bankruptcy_risk(self, stock_id: int, as_of_date: date) -> bool:
        cash = self._latest_metric(stock_id, "total_cash", as_of_date)
        free_cashflow = self._latest_metric(stock_id, "free_cashflow", as_of_date)
        operating_cashflow = self._latest_metric(stock_id, "operating_cashflow", as_of_date)
        burn = free_cashflow if free_cashflow is not None else operating_cashflow
        if cash is None or burn is None or burn >= 0:
            return False
        return cash < abs(burn) / 12.0 * 6.0

    def _customer_concentration(self, stock_id: int, as_of_date: date) -> float | None:
        return (
            self._latest_metric(stock_id, "customer_concentration", as_of_date)
            or self._latest_metric(stock_id, "top_customer_revenue_pct", as_of_date)
        )

    def _structural_score(self, stock_id: int, as_of_date: date) -> tuple[float, list]:
        score = 0.0
        signals = []

        latest_short = self.session.execute(
            select(ShortInterestData).where(
                ShortInterestData.stock_id == stock_id,
                ShortInterestData.report_date <= as_of_date,
            ).order_by(ShortInterestData.report_date.desc())
        ).scalars().first()
        prior_short = self.session.execute(
            select(ShortInterestData).where(
                ShortInterestData.stock_id == stock_id,
                ShortInterestData.report_date <= as_of_date - timedelta(days=28),
            ).order_by(ShortInterestData.report_date.desc())
        ).scalars().first()
        if latest_short and prior_short and latest_short.short_pct_float is not None and prior_short.short_pct_float is not None:
            short_change = latest_short.short_pct_float - prior_short.short_pct_float
            if short_change < -0.15:
                score += 10
                signals.append({"type": "structural", "signal": "short_interest_decline", "change": round(short_change, 4)})

        gross_margin = self._metric_history(stock_id, "gross_margin", as_of_date)
        if len(gross_margin) >= 2 and gross_margin[0].value is not None and gross_margin[1].value is not None:
            if gross_margin[0].value > gross_margin[1].value:
                score += 7
                signals.append({"type": "structural", "signal": "gross_margin_improving"})

        ocf = self._metric_history(stock_id, "operating_cashflow", as_of_date)
        if len(ocf) >= 2 and ocf[0].value is not None and ocf[1].value is not None:
            if ocf[1].value < 0 < ocf[0].value:
                score += 10
                signals.append({"type": "structural", "signal": "operating_cashflow_inflection"})

        return min(score, 10.0), signals


SmallCapRadarService = SmallCapScreener
_SECTOR_MULTIPLIERS = SECTOR_MULTIPLIERS
_REGIME_MULTIPLIERS = REGIME_MULTIPLIERS


def _normalize_regime(regime_type: str | None) -> str:
    text = (regime_type or "").upper()
    if text in {"BULL", "RISK_ON", "LOW_VOL"}:
        return "BULL"
    if text in {"BEAR", "RISK_OFF", "HIGH_VOL"}:
        return "BEAR"
    return "NEUTRAL"
