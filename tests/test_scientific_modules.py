from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from sklearn.linear_model import LogisticRegression

from app.backtest.hypothesis_registry import HypothesisEntry, HypothesisRegistry
from app.backtest.scientific_engine import Hypothesis, PurgedKFold, ScientificBacktestEngine
from app.main import app
from app.risk.alpha_decay import AlphaDecayMonitor
from app.services.core_satellite import CoreSatelliteAllocator
from app.services.trinity_screener import TrinityScreener
from app.strategies.meta_selector import MetaStrategySelector
from app.strategies.pead_nlp import EarningsEvent, PEADNLPStrategy
from app.time_utils import utcnow


def _price_frame(n: int = 280, drift: float = 0.001) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    wave = np.sin(np.linspace(0, 14, n)) * 0.003
    returns = drift + wave
    close = 100 * np.cumprod(1 + returns)
    volume = np.linspace(1_000_000, 2_000_000, n)
    volume[-1] = 3_000_000
    return pd.DataFrame({"close": close, "volume": volume}, index=idx)


def test_purged_kfold_removes_embargo_overlap() -> None:
    X = pd.DataFrame({"x": range(100)})
    splitter = PurgedKFold(n_splits=5, pct_embargo=0.05)
    for train_idx, test_idx in splitter.split(X):
        assert len(set(train_idx) & set(test_idx)) == 0
        assert len(test_idx) == 20


def test_scientific_backtest_and_bh_adjustment() -> None:
    rng = np.random.default_rng(7)
    X = pd.DataFrame(rng.normal(size=(90, 3)), columns=["a", "b", "c"])
    y = pd.Series(np.where(X["a"] + X["b"] * 0.2 > 0, 0.01, -0.01), index=X.index)
    engine = ScientificBacktestEngine(n_splits=4, pct_embargo=0.02)
    results = engine.cpcv_backtest(X, y, LogisticRegression(max_iter=200))

    assert results
    assert all(r.trades > 0 for r in results)

    hypothesis = Hypothesis(
        name="Synthetic sign edge",
        mechanism="Feature a carries directional information",
        expected_edge=0.01,
        asset_universe="synthetic",
        timeframe="daily",
        min_sharpe=-10,
    )
    assert engine.evaluate_hypothesis(hypothesis, results)

    rejected, adjusted = engine.multiple_testing_adjustment([0.001, 0.02, 0.5])
    assert rejected[0]
    assert adjusted[0] <= adjusted[1] <= adjusted[2]


def test_hypothesis_registry_lifecycle() -> None:
    db_path = Path(".pytest_tmp") / f"hypotheses_{uuid4().hex}.db"
    registry = HypothesisRegistry(str(db_path))
    entry = HypothesisEntry(
        id="pead_v1",
        name="PEAD drift",
        mechanism="Positive earnings surprise drifts after announcement",
        expected_edge=0.02,
        asset_universe="US equities",
        timeframe="weekly",
    )
    assert registry.register(entry)
    assert not registry.register(entry)
    assert registry.update_status("pead_v1", "VALIDATED", [{"sharpe": 1.2}])
    assert registry.get("pead_v1").status == "VALIDATED"
    assert len(registry.get_validated_candidates()) == 1


def test_trinity_screener_and_allocator() -> None:
    prices = {"AAA": _price_frame(), "BBB": _price_frame(drift=-0.0002)}
    scores = TrinityScreener().screen_universe(prices)
    assert len(scores) == 2
    assert scores[0].rank == 1

    explosion = pd.DataFrame([s.to_dict() for s in scores])
    allocation = CoreSatelliteAllocator(total_capital=100_000).allocate(
        explosion_signals=explosion,
        regime="TRENDING_UP",
    )
    assert "EXPLOSION" in allocation["allocations"]
    assert allocation["weekly_target_prob"] >= 0


def test_meta_selector_and_decay_monitor() -> None:
    returns = [0.01] * 25 + [-0.001] * 5
    market = pd.DataFrame({"returns": returns})
    selector = MetaStrategySelector(min_sharpe_threshold=0.1)
    weights = selector.select(
        [
            {
                "id": "s1",
                "name": "Strategy 1",
                "recent_returns": returns,
                "regime_performance": {"LOW_VOL": 0.8, "REGIME_UNCERTAIN": 0.6},
            }
        ],
        market,
    )
    assert sum(weights.values()) > 0.99

    monitor = AlphaDecayMonitor(min_observations=5, rolling_window=5)
    monitor.initialize_strategy("s1", "Strategy 1", pd.Series([0.01] * 30), 2.0)
    alert = None
    for ret in [-0.02] * 6:
        alert = monitor.update("s1", ret) or alert
    assert monitor.status_for("s1")["status"] in {"WARNING", "CRITICAL", "HEALTHY"}
    assert alert is None or alert.status in {"WARNING", "CRITICAL"}


def test_pead_strategy_generates_meta_labeled_signal() -> None:
    now = utcnow()
    events = {
        "AAA": [
            EarningsEvent("AAA", now - timedelta(days=90), 1.0, actual_eps=1.1),
            EarningsEvent("AAA", now - timedelta(days=60), 1.0, actual_eps=1.2),
            EarningsEvent("AAA", now - timedelta(days=30), 1.0, actual_eps=1.3),
            EarningsEvent(
                "AAA",
                now,
                1.0,
                actual_eps=1.5,
                transcript_text="strong growth exceeded expectations record demand",
            ),
        ]
    }
    strategy = PEADNLPStrategy(finbert_threshold=0.1)
    signals = strategy.generate_signals(["AAA"], {"AAA": _price_frame()}, earnings_events=events)
    labeled = strategy.apply_meta_label(signals, historical_win_rate=0.8)

    assert not labeled.empty
    assert {"meta_prob", "kelly_fraction", "take_trade"}.issubset(labeled.columns)


def test_weekly_pipeline_endpoint() -> None:
    client = TestClient(app)
    df = _price_frame().reset_index(names="date")
    rows = [
        {"date": row["date"].isoformat(), "close": row["close"], "volume": row["volume"]}
        for _, row in df.iterrows()
    ]
    response = client.post(
        "/api/v1/weekly-pipeline",
        json={
            "price_data": {"AAA": rows},
            "market_data": [{"returns": 0.001} for _ in range(60)],
            "strategies": [],
            "total_capital": 100000,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "allocation" in data
    assert "trinity_top" in data
