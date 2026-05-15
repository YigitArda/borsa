import pandas as pd

from app.services.model_training import ModelTrainer


def test_combinatorial_purged_cv_produces_folds(monkeypatch):
    trainer = ModelTrainer(None, {
        "features": ["feature_a"],
        "target": "target_2pct_1w",
        "threshold": 0.5,
        "top_n": 1,
        "embargo_weeks": 1,
    })

    weeks = pd.date_range("2020-01-03", periods=36, freq="W-FRI")
    df = pd.DataFrame({
        "stock_id": [1] * len(weeks),
        "ticker": ["AAPL"] * len(weeks),
        "week_ending": weeks,
        "feature_a": [float(i) for i in range(len(weeks))],
        "label": [i % 2 for i in range(len(weeks))],
    })

    monkeypatch.setattr(trainer, "load_dataset", lambda tickers: df)
    monkeypatch.setattr(trainer, "_train", lambda train: (object(), object()))
    monkeypatch.setattr(
        trainer,
        "_evaluate",
        lambda model, scaler, test, tickers: {
            "precision": 0.5,
            "recall": 0.5,
            "f1": 0.5,
            "n_trades": len(test),
            "win_rate": 0.5,
            "avg_return": 0.01,
            "sharpe": 0.6,
            "sortino": 0.7,
            "max_drawdown": -0.1,
            "profit_factor": 1.2,
            "cagr": 0.1,
            "calmar": 1.0,
            "_trade_returns": [0.01],
            "_trade_details": [],
            "_equity_curve": [],
        },
    )

    folds = trainer.combinatorial_purged_cv(
        ["AAPL"],
        n_groups=6,
        n_test_groups=2,
        min_train_rows=10,
        apply_liquidity_filter=False,
    )

    assert len(folds) > 1
    assert all(f.metrics["sharpe"] == 0.6 for f in folds)
