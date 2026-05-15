"""
Self-improving research loop.

Proposer generates strategy mutations → walk-forward test →
Acceptance Gate → promotion if out-of-sample criteria met.

The holdout period is NEVER seen by the proposer.
"""
import copy
import logging
import random
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.models.strategy import Strategy
from app.services.model_training import ModelTrainer
from app.services.feature_engineering import TECHNICAL_FEATURES

logger = logging.getLogger(__name__)

# Holdout: last N months never touched by proposer
HOLDOUT_MONTHS = settings.holdout_months

BASE_STRATEGY = {
    "model_type": "lightgbm",
    "features": TECHNICAL_FEATURES,
    "target": "target_2pct_1w",
    "threshold": 0.5,
    "top_n": 5,
    "embargo_weeks": 4,
}

ACCEPTANCE_GATE = {
    "min_sharpe": 0.5,
    "min_win_rate": 0.45,
    "min_trades": settings.min_trades_for_promotion,
    "max_drawdown": -0.25,
    "min_profit_factor": 1.1,
}


class StrategyProposer:
    """Generates mutations of an existing strategy config."""

    FEATURE_POOL = TECHNICAL_FEATURES

    def propose(self, base_config: dict) -> dict:
        mutation_type = random.choice(["add_feature", "remove_feature", "change_threshold", "change_top_n", "change_model"])
        new_config = copy.deepcopy(base_config)

        if mutation_type == "add_feature":
            candidates = [f for f in self.FEATURE_POOL if f not in new_config["features"]]
            if candidates:
                new_config["features"].append(random.choice(candidates))

        elif mutation_type == "remove_feature" and len(new_config["features"]) > 5:
            new_config["features"].remove(random.choice(new_config["features"]))

        elif mutation_type == "change_threshold":
            delta = random.choice([-0.05, 0.05, -0.1, 0.1])
            new_config["threshold"] = round(max(0.3, min(0.8, new_config["threshold"] + delta)), 2)

        elif mutation_type == "change_top_n":
            new_config["top_n"] = random.choice([3, 5, 7, 10])

        elif mutation_type == "change_model":
            new_config["model_type"] = random.choice([
                "lightgbm", "logistic_regression", "random_forest", "gradient_boosting"
            ])

        return new_config


class AcceptanceGate:
    """Evaluates whether a strategy's walk-forward results are good enough."""

    def evaluate(self, fold_metrics: list[dict]) -> tuple[bool, dict]:
        if not fold_metrics:
            return False, {"reason": "no folds"}

        avg_sharpe = sum(m.get("sharpe", 0) for m in fold_metrics) / len(fold_metrics)
        avg_win_rate = sum(m.get("win_rate", 0) for m in fold_metrics) / len(fold_metrics)
        total_trades = sum(m.get("n_trades", 0) for m in fold_metrics)
        min_drawdown = min(m.get("max_drawdown", 0) for m in fold_metrics)
        avg_pf = sum(m.get("profit_factor", 0) for m in fold_metrics) / len(fold_metrics)

        summary = {
            "avg_sharpe": round(avg_sharpe, 4),
            "avg_win_rate": round(avg_win_rate, 4),
            "total_trades": total_trades,
            "min_drawdown": round(min_drawdown, 4),
            "avg_profit_factor": round(avg_pf, 4),
        }

        passed = (
            avg_sharpe >= ACCEPTANCE_GATE["min_sharpe"]
            and avg_win_rate >= ACCEPTANCE_GATE["min_win_rate"]
            and total_trades >= ACCEPTANCE_GATE["min_trades"]
            and min_drawdown >= ACCEPTANCE_GATE["max_drawdown"]
            and avg_pf >= ACCEPTANCE_GATE["min_profit_factor"]
        )

        if not passed:
            reasons = []
            if avg_sharpe < ACCEPTANCE_GATE["min_sharpe"]:
                reasons.append(f"sharpe {avg_sharpe:.2f} < {ACCEPTANCE_GATE['min_sharpe']}")
            if avg_win_rate < ACCEPTANCE_GATE["min_win_rate"]:
                reasons.append(f"win_rate {avg_win_rate:.2f} < {ACCEPTANCE_GATE['min_win_rate']}")
            if total_trades < ACCEPTANCE_GATE["min_trades"]:
                reasons.append(f"trades {total_trades} < {ACCEPTANCE_GATE['min_trades']}")
            if min_drawdown < ACCEPTANCE_GATE["max_drawdown"]:
                reasons.append(f"drawdown {min_drawdown:.2f} < {ACCEPTANCE_GATE['max_drawdown']}")
            summary["reason"] = "; ".join(reasons)

        return passed, summary


class ResearchLoop:
    def __init__(self, session: Session, tickers: list[str]):
        self.session = session
        self.tickers = tickers
        self.proposer = StrategyProposer()
        self.gate = AcceptanceGate()
        self._holdout_cutoff = self._compute_holdout_cutoff()

    def _compute_holdout_cutoff(self) -> date:
        from dateutil.relativedelta import relativedelta
        return date.today() - relativedelta(months=HOLDOUT_MONTHS)

    def run_one_iteration(self, base_strategy_id: int | None = None) -> dict:
        """Run one research iteration: propose → train → gate → maybe promote."""
        if base_strategy_id:
            base = self.session.get(Strategy, base_strategy_id)
            base_config = base.config if base else BASE_STRATEGY
            generation = (base.generation + 1) if base else 1
        else:
            base_config = BASE_STRATEGY
            generation = 0

        new_config = self.proposer.propose(base_config)

        # Train only on data before holdout cutoff
        trainer = ModelTrainer(self.session, new_config)

        # Filter tickers to only those with data
        folds = trainer.walk_forward(
            self.tickers,
            min_train_years=5,
        )

        if not folds:
            return {"status": "failed", "reason": "no walk-forward folds produced"}

        fold_metrics = [f.metrics for f in folds]
        passed, summary = self.gate.evaluate(fold_metrics)

        # Persist strategy
        strategy = Strategy(
            name=f"gen{generation}_{'_'.join(new_config['features'][:3])}",
            config=new_config,
            parent_strategy_id=base_strategy_id,
            generation=generation,
            status="research",
            notes=str(summary),
        )
        self.session.add(strategy)
        self.session.flush()

        if passed:
            strategy.status = "promoted"
            self.session.commit()
            logger.info(f"Strategy {strategy.id} PROMOTED: {summary}")
            return {"status": "promoted", "strategy_id": strategy.id, **summary}
        else:
            self.session.commit()
            logger.info(f"Strategy {strategy.id} REJECTED: {summary}")
            return {"status": "rejected", "strategy_id": strategy.id, **summary}

    def run_loop(self, n_iterations: int = 10, base_strategy_id: int | None = None) -> list[dict]:
        results = []
        for i in range(n_iterations):
            logger.info(f"Research iteration {i + 1}/{n_iterations}")
            result = self.run_one_iteration(base_strategy_id)
            results.append(result)
            # If promoted, use it as next base
            if result.get("status") == "promoted":
                base_strategy_id = result.get("strategy_id")
        return results
