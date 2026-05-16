"""Scientific research endpoints for Trinity and hypothesis-first workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.backtest.hypothesis_registry import HypothesisEntry, HypothesisRegistry
from app.risk.alpha_decay import AlphaDecayMonitor
from app.services.core_satellite import CoreSatelliteAllocator
from app.services.trinity_screener import TrinityScreener
from app.strategies.meta_selector import MetaStrategySelector
from app.strategies.pead_nlp import EarningsEvent, PEADNLPStrategy
from app.time_utils import utcnow

router = APIRouter(tags=["scientific"])


class HypothesisPayload(BaseModel):
    id: str
    name: str
    mechanism: str
    expected_edge: float
    asset_universe: str
    timeframe: str
    features: list[str] = Field(default_factory=list)
    entry_rules: str = ""
    exit_rules: str = ""
    max_drawdown_tolerance: float = 0.20
    min_sharpe: float = 1.0
    min_win_rate: float = 0.35
    max_correlation_to_existing: float = 0.70
    notes: str = ""


class StatusPayload(BaseModel):
    status: str
    results: list[dict[str, Any]] | None = None


class TrinityPayload(BaseModel):
    price_data: dict[str, list[dict[str, Any]]]
    fundamentals: dict[str, dict[str, Any]] | None = None
    pre_explosion_only: bool = False


class AllocationPayload(BaseModel):
    total_capital: float = 180000.0
    regime: str = "NORMAL"
    core_signals: list[dict[str, Any]] | None = None
    satellite_signals: list[dict[str, Any]] | None = None
    explosion_signals: list[dict[str, Any]] | None = None


class MetaSelectPayload(BaseModel):
    strategies: list[dict[str, Any]]
    market_data: list[dict[str, Any]]
    decay_results: list[dict[str, Any]] | None = None


class DecayPayload(BaseModel):
    strategy_id: str
    strategy_name: str
    baseline_returns: list[float]
    live_returns: list[float]
    baseline_sharpe: float | None = None


class WeeklyPipelinePayload(BaseModel):
    price_data: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    market_data: list[dict[str, Any]] = Field(default_factory=list)
    strategies: list[dict[str, Any]] = Field(default_factory=list)
    earnings_events: dict[str, list[dict[str, Any]]] | None = None
    fmp_api_key: str | None = None
    total_capital: float = 180000.0


def _registry() -> HypothesisRegistry:
    return HypothesisRegistry()


def _frames(price_data: dict[str, list[dict[str, Any]]]) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for ticker, rows in price_data.items():
        df = pd.DataFrame(rows)
        if df.empty:
            continue
        if "date" in df:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
        frames[ticker] = df.sort_index()
    return frames


def _df(rows: list[dict[str, Any]] | None) -> pd.DataFrame | None:
    if not rows:
        return None
    return pd.DataFrame(rows)


def _earnings_events(
    raw: dict[str, list[dict[str, Any]]] | None,
) -> dict[str, list[EarningsEvent]] | None:
    if not raw:
        return None
    out: dict[str, list[EarningsEvent]] = {}
    for ticker, rows in raw.items():
        events = []
        for row in rows:
            report_date = row.get("report_date") or row.get("date")
            if not report_date:
                continue
            events.append(
                EarningsEvent(
                    ticker=ticker,
                    report_date=pd.to_datetime(report_date).to_pydatetime(),
                    expected_eps=float(row.get("expected_eps", 0.0)),
                    actual_eps=float(row["actual_eps"])
                    if row.get("actual_eps") is not None
                    else None,
                    surprise_pct=float(row["surprise_pct"])
                    if row.get("surprise_pct") is not None
                    else None,
                    transcript_text=row.get("transcript_text"),
                )
            )
        out[ticker] = events
    return out


@router.get("/scientific/hypotheses")
async def list_hypotheses(status: str | None = None):
    return [entry.to_dict() for entry in _registry().list(status=status)]


@router.post("/scientific/hypotheses")
async def register_hypothesis(payload: HypothesisPayload):
    entry = HypothesisEntry(**payload.model_dump())
    created = _registry().register(entry)
    return {"created": created, "hypothesis": entry.to_dict()}


@router.patch("/scientific/hypotheses/{hypothesis_id}/status")
async def update_hypothesis_status(hypothesis_id: str, payload: StatusPayload):
    ok = _registry().update_status(hypothesis_id, payload.status, payload.results)
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid hypothesis id or status transition")
    return {"updated": True, "hypothesis_id": hypothesis_id, "status": payload.status}


@router.post("/scientific/trinity/screen")
async def trinity_screen(payload: TrinityPayload):
    price_data = _frames(payload.price_data)
    scores = TrinityScreener().screen_universe(price_data, payload.fundamentals)
    if payload.pre_explosion_only:
        scores = TrinityScreener().filter_pre_explosion(scores, price_data)
    return [score.to_dict() for score in scores]


@router.post("/scientific/portfolio/allocate")
async def allocate_portfolio(payload: AllocationPayload):
    allocator = CoreSatelliteAllocator(total_capital=payload.total_capital)
    return allocator.allocate(
        core_signals=_df(payload.core_signals),
        satellite_signals=_df(payload.satellite_signals),
        explosion_signals=_df(payload.explosion_signals),
        regime=payload.regime,
    )


@router.post("/scientific/meta/select")
async def select_meta_strategy(payload: MetaSelectPayload):
    selector = MetaStrategySelector()
    market_data = pd.DataFrame(payload.market_data)
    decay_results = pd.DataFrame(payload.decay_results or [])
    weights = selector.select(payload.strategies, market_data, decay_results)
    return {"regime": selector.current_regime, "weights": weights}


@router.post("/scientific/decay/check")
async def check_alpha_decay(payload: DecayPayload):
    monitor = AlphaDecayMonitor(min_observations=min(30, max(2, len(payload.live_returns))))
    monitor.initialize_strategy(
        strategy_id=payload.strategy_id,
        strategy_name=payload.strategy_name,
        historical_returns=pd.Series(payload.baseline_returns, dtype=float),
        in_sample_sharpe=payload.baseline_sharpe,
    )
    alert = None
    for ret in payload.live_returns:
        alert = monitor.update(payload.strategy_id, float(ret)) or alert
    status = monitor.status_for(payload.strategy_id)
    return {"alert": alert.to_dict() if alert else None, "status": status}


@router.post("/api/v1/weekly-pipeline")
async def weekly_pipeline(payload: WeeklyPipelinePayload):
    price_data = _frames(payload.price_data)
    market_data = pd.DataFrame(payload.market_data)
    tickers = list(price_data.keys())

    selector = MetaStrategySelector()
    regime = selector.regime_detector.detect(market_data) if not market_data.empty else "REGIME_UNCERTAIN"

    trinity = TrinityScreener()
    trinity_scores = trinity.screen_universe(price_data)
    pre_explosion = trinity.filter_pre_explosion(trinity_scores, price_data)

    pead = PEADNLPStrategy()
    pead_signals = pead.generate_signals(
        tickers,
        price_data,
        fmp_api_key=payload.fmp_api_key,
        earnings_events=_earnings_events(payload.earnings_events),
    )
    pead_signals = pead.apply_meta_label(pead_signals)

    weights = selector.select(payload.strategies, market_data) if payload.strategies else {"CASH": 1.0}
    explosion_df = pd.DataFrame([score.to_dict() for score in pre_explosion])
    allocation = CoreSatelliteAllocator(total_capital=payload.total_capital).allocate(
        satellite_signals=pead_signals,
        explosion_signals=explosion_df,
        regime=regime,
    )

    return {
        "timestamp": utcnow().isoformat(),
        "regime": regime,
        "trinity_top": [score.to_dict() for score in trinity_scores[:20]],
        "pre_explosion": [score.to_dict() for score in pre_explosion[:15]],
        "pead_signals": pead_signals.to_dict(orient="records") if not pead_signals.empty else [],
        "strategy_weights": weights,
        "allocation": allocation,
        "risk_notice": "Research output only; use paper trading before live deployment.",
    }
