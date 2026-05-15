from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.backtest import WalkForwardResult
from app.models.strategy import Strategy
from app.services.meta_learner import MetaPromotionModel
from app.services.mutation_memory import MutationScoreTracker
from app.services.rl_agent import RLStrategyAgent
from app.services.strategy_bandit import StrategyBandit


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_mutation_memory_persists_scores_and_weights():
    session = _session()
    tracker = MutationScoreTracker(session)

    tracker.update("add_feature", ["rsi_14"], [], 0.4)
    tracker.update("add_feature", ["macd"], [], -0.2)

    summary = tracker.summary()
    weights = tracker.get_feature_weights(["rsi_14", "macd"])

    assert summary["top_features"][0][0] == "rsi_14"
    assert weights[0] > weights[1]


def test_strategy_bandit_updates_beta_parameters():
    session = _session()
    bandit = StrategyBandit(session)

    assert bandit.select_strategy([10]) == 10
    bandit.record_outcome(10, hit=True)
    bandit.record_outcome(10, hit=False)

    arm = bandit.arm_summary([10])[0]
    assert arm["alpha"] == 2
    assert arm["beta"] == 2
    assert arm["n_trials"] == 2


def test_rl_agent_saves_and_loads_qtable():
    session = _session()
    config = {"features": ["rsi_14"], "threshold": 0.5, "top_n": 5, "model_type": "lightgbm"}
    metrics = [{"sharpe": 0.4, "win_rate": 0.5}]

    agent = RLStrategyAgent(session)
    action_idx = agent.select_action(config, metrics)
    agent.update(config, metrics, action_idx, 0.3, config, [{"sharpe": 0.7, "win_rate": 0.55}])
    agent.save()

    loaded = RLStrategyAgent(session)
    status = loaded.status()

    assert status["n_states"] >= 1
    assert status["steps"] == 1


def test_meta_learner_records_outcome_and_cold_start_allows_gate():
    session = _session()
    strategy = Strategy(
        name="candidate",
        config={"features": ["rsi_14", "macd"]},
        status="candidate",
    )
    session.add(strategy)
    session.flush()
    session.add(WalkForwardResult(
        strategy_id=strategy.id,
        fold=0,
        train_start=date(2020, 1, 3),
        train_end=date(2024, 1, 5),
        test_start=date(2024, 1, 12),
        test_end=date(2024, 12, 27),
        metrics={"sharpe": 0.8, "win_rate": 0.55, "profit_factor": 1.4, "max_drawdown": -0.1},
    ))
    session.commit()

    model = MetaPromotionModel(session)
    model.record_outcome(
        strategy_id=strategy.id,
        fold_metrics=[{"sharpe": 0.8, "win_rate": 0.55, "profit_factor": 1.4, "max_drawdown": -0.1}],
        notes={"permutation_pvalue": 0.05, "deflated_sharpe": 0.4},
        n_features=2,
        paper_hit_rate=0.5,
    )
    passed, confidence, reason = model.predict(
        fold_metrics=[{"sharpe": 0.8, "win_rate": 0.55, "profit_factor": 1.4, "max_drawdown": -0.1}],
        notes={"permutation_pvalue": 0.05, "deflated_sharpe": 0.4},
        n_features=2,
    )

    assert model.n_samples() == 1
    assert passed is True
    assert confidence == 0.0
    assert "cold_start" in reason
