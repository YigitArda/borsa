import json
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.models.backtest import WalkForwardResult
from app.models.prediction import PaperTrade
from app.models.stock import Stock
from app.models.strategy import Strategy
from app.services.promotion import PromotionGate


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_promotion_requires_paper_forward_results():
    session = _session()
    settings.min_paper_trades_for_promotion = 2
    settings.min_paper_hit_rate_2pct = 0.45
    settings.max_paper_calibration_error_2pct = 0.20

    stock = Stock(ticker="MSFT")
    strategy = Strategy(
        name="candidate",
        config={"features": ["rsi_14"], "model_type": "lightgbm"},
        status="candidate",
        notes=json.dumps({
            "deflated_sharpe": 0.5,
            "probabilistic_sr": 0.8,
            "permutation_pvalue": 0.05,
            "spy_sharpe": 0.4,
            "outperforms_spy": True,
            "benchmark_alpha": 0.01,
            "concentration": {"ok": True},
        }),
    )
    session.add_all([stock, strategy])
    session.flush()

    for fold in range(2):
        session.add(WalkForwardResult(
            strategy_id=strategy.id,
            fold=fold,
            train_start=date(2020, 1, 3),
            train_end=date(2024, 1, 5),
            test_start=date(2024, 1, 12),
            test_end=date(2024, 12, 27),
            metrics={
                "sharpe": 0.8,
                "win_rate": 0.55,
                "n_trades": 20,
                "max_drawdown": -0.1,
                "profit_factor": 1.4,
            },
        ))

    session.add_all([
        PaperTrade(
            prediction_id=1,
            week_starting=date(2026, 5, 11),
            stock_id=stock.id,
            strategy_id=strategy.id,
            planned_exit_date=date(2026, 5, 15),
            prob_2pct=0.55,
            realized_return=0.03,
            hit_2pct=True,
            hit_3pct=True,
            hit_loss_2pct=False,
            status="closed",
        ),
        PaperTrade(
            prediction_id=2,
            week_starting=date(2026, 5, 18),
            stock_id=stock.id,
            strategy_id=strategy.id,
            planned_exit_date=date(2026, 5, 22),
            prob_2pct=0.55,
            realized_return=0.01,
            hit_2pct=False,
            hit_3pct=False,
            hit_loss_2pct=False,
            status="closed",
        ),
    ])
    session.commit()

    passed, summary = PromotionGate(session).evaluate(strategy.id)

    assert passed is True
    assert summary["paper"]["closed"] == 2
    assert summary["paper"]["hit_rate_2pct"] == 0.5
