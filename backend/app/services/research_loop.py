"""
Self-improving research loop.

Proposer generates strategy mutations → walk-forward test →
Acceptance Gate → promotion if out-of-sample criteria met.

The holdout period is NEVER seen by the proposer.
"""
import copy
import json
import logging
import random
from datetime import date, timedelta

import numpy as np
from sqlalchemy import func as sqlfunc, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.research_budget import ResearchTrialBudget
from app.models.strategy import Strategy
from app.models.backtest import WalkForwardResult
from app.services.model_training import ModelTrainer
from app.services.feature_engineering import TECHNICAL_FEATURES
from app.services.mutation_memory import MUTATION_TYPES, MutationScoreTracker
from app.services.rl_agent import RLStrategyAgent
from app.services.statistical_tests import (
    probabilistic_sharpe_ratio,
    deflated_sharpe_ratio,
    permutation_test,
    concentration_check,
    get_spy_weekly_sharpe,
)
from app.services.mlflow_tracking import log_strategy_run

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
    "holding_weeks": 1,
    "stop_loss": -0.05,
    "take_profit": 0.08,
}


def _merge_base_config(base_config: dict | None) -> dict:
    merged = copy.deepcopy(BASE_STRATEGY)
    if not base_config:
        return merged

    for key, value in base_config.items():
        if key == "tickers" or value is None:
            continue
        merged[key] = copy.deepcopy(value)
    return merged

ACCEPTANCE_GATE = {
    "min_sharpe": 0.5,
    "min_win_rate": 0.45,
    "min_trades": settings.min_trades_for_promotion,
    "max_drawdown": -0.25,
    "min_profit_factor": 1.1,
}


class StrategyProposer:
    """Generates mutations of an existing strategy config.

    The proposer is no longer blind random search. It can use MutationScoreTracker
    for epsilon-greedy weighted choices and RLStrategyAgent for action selection.
    """

    FEATURE_POOL = TECHNICAL_FEATURES

    def __init__(
        self,
        tracker: MutationScoreTracker | None = None,
        rl_agent: RLStrategyAgent | None = None,
    ):
        self.tracker = tracker
        self.rl_agent = rl_agent
        self.last_mutation: dict = {}

    def _choice(self, items: list, weights: list[float] | None = None):
        if not items:
            return None
        if not weights:
            return random.choice(items)
        weights_arr = np.array(weights, dtype=float)
        if weights_arr.sum() <= 0:
            return random.choice(items)
        weights_arr = weights_arr / weights_arr.sum()
        return random.choices(items, weights=weights_arr.tolist(), k=1)[0]

    def _select_mutation_type(self, base_config: dict, recent_metrics: list[dict]) -> tuple[str, int | None]:
        if self.rl_agent is not None:
            action_idx = self.rl_agent.select_action(base_config, recent_metrics)
            return self.rl_agent.action_name(action_idx), action_idx

        if self.tracker is not None and not self.tracker.should_explore():
            return self._choice(MUTATION_TYPES, self.tracker.get_mutation_type_weights()), None

        # Weight stop_loss and take_profit more heavily to encourage risk-control exploration
        _mt_weights = {
            "add_feature": 1.0, "remove_feature": 1.0, "change_threshold": 1.0,
            "change_top_n": 0.8, "change_model": 0.8, "holding_period": 1.0,
            "stop_loss": 1.5, "take_profit": 1.5,
        }
        weights = [_mt_weights.get(mt, 1.0) for mt in MUTATION_TYPES]
        return random.choices(MUTATION_TYPES, weights=weights, k=1)[0], None

    def propose(self, base_config: dict, recent_metrics: list[dict] | None = None) -> dict:
        recent_metrics = recent_metrics or []
        mutation_type, action_idx = self._select_mutation_type(base_config, recent_metrics)
        new_config = copy.deepcopy(base_config)
        new_config["features"] = list(new_config.get("features") or [])
        features_added: list[str] = []
        features_removed: list[str] = []

        if mutation_type == "add_feature":
            candidates = [f for f in self.FEATURE_POOL if f not in new_config["features"]]
            if candidates:
                weights = self.tracker.get_feature_weights(candidates) if self.tracker else None
                feature = self._choice(candidates, weights)
                if feature:
                    new_config["features"].append(feature)
                    features_added.append(feature)

        elif mutation_type == "remove_feature" and len(new_config["features"]) > 5:
            weights = self.tracker.get_remove_weights(new_config["features"]) if self.tracker else None
            feature = self._choice(new_config["features"], weights)
            if feature:
                new_config["features"].remove(feature)
                features_removed.append(feature)

        elif mutation_type == "change_threshold":
            delta = random.choice([-0.05, 0.05, -0.1, 0.1])
            new_config["threshold"] = round(max(0.3, min(0.8, new_config.get("threshold", 0.5) + delta)), 2)

        elif mutation_type == "change_top_n":
            new_config["top_n"] = random.choice([3, 5, 7, 10])

        elif mutation_type == "change_model":
            new_config["model_type"] = random.choice([
                "lightgbm", "logistic_regression", "random_forest",
                "gradient_boosting", "xgboost", "neural_network",
            ])

        elif mutation_type == "holding_period":
            new_config["holding_weeks"] = random.choice([1, 2, 4])

        elif mutation_type == "stop_loss":
            new_config["stop_loss"] = random.choice([None, -0.03, -0.05, -0.07, -0.10])

        elif mutation_type == "take_profit":
            new_config["take_profit"] = random.choice([None, 0.05, 0.08, 0.10, 0.15])

        self.last_mutation = {
            "mutation_type": mutation_type,
            "features_added": features_added,
            "features_removed": features_removed,
            "action_idx": action_idx,
        }
        return new_config


class AcceptanceGate:
    """Evaluates whether a strategy's walk-forward results are good enough."""

    def evaluate(self, fold_metrics: list[dict], n_features: int = 0) -> tuple[bool, dict]:
        if not fold_metrics:
            return False, {"reason": "no folds"}

        avg_sharpe = sum(m.get("sharpe", 0) for m in fold_metrics) / len(fold_metrics)
        adjusted_sharpe = avg_sharpe - 0.01 * n_features
        avg_win_rate = sum(m.get("win_rate", 0) for m in fold_metrics) / len(fold_metrics)
        total_trades = sum(m.get("n_trades", 0) for m in fold_metrics)
        min_drawdown = min(m.get("max_drawdown", 0) for m in fold_metrics)
        avg_pf = sum(m.get("profit_factor", 0) for m in fold_metrics) / len(fold_metrics)

        summary = {
            "avg_sharpe": round(avg_sharpe, 4),
            "adjusted_sharpe": round(adjusted_sharpe, 4),
            "complexity_penalty": round(0.01 * n_features, 4),
            "avg_win_rate": round(avg_win_rate, 4),
            "total_trades": total_trades,
            "min_drawdown": round(min_drawdown, 4),
            "avg_profit_factor": round(avg_pf, 4),
        }

        passed = (
            adjusted_sharpe >= ACCEPTANCE_GATE["min_sharpe"]
            and avg_win_rate >= ACCEPTANCE_GATE["min_win_rate"]
            and total_trades >= ACCEPTANCE_GATE["min_trades"]
            and min_drawdown >= ACCEPTANCE_GATE["max_drawdown"]
            and avg_pf >= ACCEPTANCE_GATE["min_profit_factor"]
        )

        if not passed:
            reasons = []
            if adjusted_sharpe < ACCEPTANCE_GATE["min_sharpe"]:
                reasons.append(
                    f"adjusted_sharpe {adjusted_sharpe:.2f} < {ACCEPTANCE_GATE['min_sharpe']}"
                )
            if avg_win_rate < ACCEPTANCE_GATE["min_win_rate"]:
                reasons.append(f"win_rate {avg_win_rate:.2f} < {ACCEPTANCE_GATE['min_win_rate']}")
            if total_trades < ACCEPTANCE_GATE["min_trades"]:
                reasons.append(f"trades {total_trades} < {ACCEPTANCE_GATE['min_trades']}")
            if min_drawdown < ACCEPTANCE_GATE["max_drawdown"]:
                reasons.append(f"drawdown {min_drawdown:.2f} < {ACCEPTANCE_GATE['max_drawdown']}")
            summary["reason"] = "; ".join(reasons)

        return passed, summary


class RuleBasedResearch:
    """Evaluate all rule-based strategies on the full dataset."""

    def __init__(self, session: Session, tickers: list[str]):
        self.session = session
        self.tickers = tickers

    def run(self) -> list[dict]:
        from app.services.model_training import ModelTrainer
        from app.services.rule_based import evaluate_all_rules

        trainer = ModelTrainer(self.session, BASE_STRATEGY)
        df = trainer.load_dataset(self.tickers)
        if df.empty:
            return []
        return evaluate_all_rules(df, label_col="label")


class ResearchLoop:
    def __init__(self, session: Session, tickers: list[str], base_config: dict | None = None):
        self.session = session
        self.tickers = tickers
        self.base_config = _merge_base_config(base_config)
        self.mutation_tracker = MutationScoreTracker(session)
        self.rl_agent = RLStrategyAgent(session)
        self.proposer = StrategyProposer(self.mutation_tracker, self.rl_agent)
        self.gate = AcceptanceGate()
        self._holdout_cutoff = self._compute_holdout_cutoff()

    def _compute_holdout_cutoff(self) -> date:
        from dateutil.relativedelta import relativedelta
        cutoff = date.today() - relativedelta(months=HOLDOUT_MONTHS)
        logger.info(
            "Holdout cutoff set to: %s (last %d months protected from training)",
            cutoff, HOLDOUT_MONTHS,
        )
        return cutoff

    def _consume_trial_budget(self) -> tuple[bool, dict]:
        today = date.today()
        budget = self.session.execute(
            select(ResearchTrialBudget).where(ResearchTrialBudget.budget_date == today)
        ).scalar_one_or_none()
        if budget is None:
            budget = ResearchTrialBudget(
                budget_date=today,
                iterations_used=0,
                max_iterations=settings.research_max_daily_iterations,
            )
            self.session.add(budget)
            self.session.flush()

        budget.max_iterations = settings.research_max_daily_iterations
        if budget.iterations_used >= budget.max_iterations:
            return False, {
                "status": "blocked",
                "reason": "daily research trial budget exhausted",
                "budget_date": str(today),
                "iterations_used": budget.iterations_used,
                "max_iterations": budget.max_iterations,
            }

        budget.iterations_used += 1
        self.session.commit()
        return True, {
            "budget_date": str(today),
            "iterations_used": budget.iterations_used,
            "max_iterations": budget.max_iterations,
        }

    def _fold_metrics_for_strategy(self, strategy_id: int | None) -> list[dict]:
        if strategy_id is None:
            return []
        rows = self.session.execute(
            select(WalkForwardResult)
            .where(WalkForwardResult.strategy_id == strategy_id)
            .order_by(WalkForwardResult.fold)
        ).scalars().all()
        return [r.metrics for r in rows if r.metrics]

    def _avg_sharpe(self, metrics: list[dict]) -> float:
        vals = [m.get("sharpe", 0.0) for m in metrics if m]
        return float(sum(vals) / len(vals)) if vals else 0.0

    def _should_run_bayesian_opt(self) -> bool:
        if not settings.enable_bayesian_optimization:
            return False
        interval = max(settings.bayesian_opt_interval, 1)
        budget = self.session.execute(
            select(ResearchTrialBudget).where(ResearchTrialBudget.budget_date == date.today())
        ).scalar_one_or_none()
        return bool(budget and budget.iterations_used > 0 and budget.iterations_used % interval == 0)

    def _maybe_optimize_base_config(self, base_config: dict) -> tuple[dict, bool]:
        if not self._should_run_bayesian_opt():
            return base_config, False
        try:
            from app.services.hyperparam_optimizer import HyperparamOptimizer

            optimizer = HyperparamOptimizer(self.session, self.tickers)
            optimized = optimizer.optimize(base_config, n_trials=settings.bayesian_opt_trials)
            return optimized, True
        except Exception as exc:
            logger.warning("Bayesian optimization skipped: %s", exc)
            return base_config, False

    def _update_learning_layers(
        self,
        base_config: dict,
        base_metrics: list[dict],
        new_config: dict,
        new_metrics: list[dict],
        sharpe_delta: float,
    ) -> None:
        mutation = self.proposer.last_mutation or {}
        mutation_type = mutation.get("mutation_type")
        if mutation_type:
            try:
                self.mutation_tracker.update(
                    mutation_type=mutation_type,
                    features_added=mutation.get("features_added") or [],
                    features_removed=mutation.get("features_removed") or [],
                    sharpe_delta=sharpe_delta,
                )
            except Exception as exc:
                logger.warning("Mutation memory update failed: %s", exc)

        action_idx = mutation.get("action_idx")
        if action_idx is not None:
            try:
                self.rl_agent.update(
                    old_config=base_config,
                    old_metrics=base_metrics,
                    action_idx=action_idx,
                    reward=sharpe_delta,
                    new_config=new_config,
                    new_metrics=new_metrics,
                )
                self.rl_agent.save()
            except Exception as exc:
                logger.warning("RL agent update failed: %s", exc)

    def run_one_iteration(self, base_strategy_id: int | None = None) -> dict:
        """Run one research iteration: propose → train → gate → maybe promote."""
        budget_ok, budget_info = self._consume_trial_budget()
        if not budget_ok:
            return budget_info

        if base_strategy_id:
            base = self.session.get(Strategy, base_strategy_id)
            base_config = copy.deepcopy(base.config) if base and base.config else copy.deepcopy(self.base_config)
            generation = (base.generation + 1) if base else 1
        else:
            base_config = copy.deepcopy(self.base_config)
            generation = 0

        base_metrics = self._fold_metrics_for_strategy(base_strategy_id)
        optimized_config, used_optuna = self._maybe_optimize_base_config(base_config)
        if used_optuna:
            new_config = optimized_config
            self.proposer.last_mutation = {
                "mutation_type": "bayesian_opt",
                "features_added": [],
                "features_removed": [],
                "action_idx": None,
            }
        else:
            new_config = self.proposer.propose(base_config, recent_metrics=base_metrics)

        # Train only on data before holdout cutoff
        trainer = ModelTrainer(self.session, new_config)

        # Filter tickers to only those with data
        folds = trainer.walk_forward(
            self.tickers,
            min_train_years=5,
            holdout_cutoff=self._holdout_cutoff,
            apply_liquidity_filter=new_config.get("apply_liquidity_filter", True),
        )

        if not folds:
            return {"status": "failed", "reason": "no walk-forward folds produced"}

        fold_metrics = [f.metrics for f in folds]
        passed, summary = self.gate.evaluate(fold_metrics, n_features=len(new_config.get("features", [])))

        # Collect all trade returns from folds for advanced statistics
        all_returns = []
        all_trades = []
        for fold in folds:
            all_returns.extend(fold.trade_returns or [])
            all_trades.extend(fold.trade_details or [])

        # Advanced statistical tests
        n_strategies_tested = self.session.execute(
            select(sqlfunc.count()).select_from(Strategy)
        ).scalar() or 1

        dsr = deflated_sharpe_ratio(all_returns, n_trials=n_strategies_tested) if all_returns else 0.0
        psr = probabilistic_sharpe_ratio(all_returns, sr_benchmark=0.0) if all_returns else 0.0
        perm_pvalue = permutation_test(all_returns, n_permutations=300) if len(all_returns) >= 10 else 1.0
        concentration = concentration_check(all_trades)
        spy_sharpe = get_spy_weekly_sharpe(self.session)

        outperforms_spy = summary.get("avg_sharpe", 0.0) > spy_sharpe

        # Benchmark alpha: avg_return - SPY weekly return scaled to same period
        avg_return_per_trade = float(sum(r for r in all_returns) / len(all_returns)) if all_returns else 0.0
        spy_weekly_return = spy_sharpe / (52 ** 0.5) if spy_sharpe else 0.0
        benchmark_alpha = round(avg_return_per_trade - spy_weekly_return, 4)

        # Tighten gate: also require permutation p-value < 0.1 and DSR > 0
        if passed and (perm_pvalue > 0.1 or dsr <= 0):
            passed = False
            summary["reason"] = summary.get("reason", "") + f"; perm_pvalue={perm_pvalue:.3f} dsr={dsr:.3f}"

        summary.update({
            "deflated_sharpe": round(dsr, 4),
            "probabilistic_sr": round(psr, 4),
            "permutation_pvalue": round(perm_pvalue, 4),
            "spy_sharpe": round(spy_sharpe, 4),
            "outperforms_spy": outperforms_spy,
            "benchmark_alpha": benchmark_alpha,
            "concentration": concentration,
            "mutation": self.proposer.last_mutation,
            "bayesian_optimized": used_optuna,
            "trial_budget": budget_info,
        })

        sharpe_delta = summary.get("avg_sharpe", 0.0) - self._avg_sharpe(base_metrics)
        summary["sharpe_delta"] = round(sharpe_delta, 4)
        self._update_learning_layers(base_config, base_metrics, new_config, fold_metrics, sharpe_delta)

        # Persist strategy
        strategy = Strategy(
            name=f"gen{generation}_{'_'.join(new_config['features'][:3])}",
            config=new_config,
            parent_strategy_id=base_strategy_id,
            generation=generation,
            status="research",
            notes=json.dumps(summary),
        )
        self.session.add(strategy)
        self.session.flush()

        # Save walk-forward fold results with equity curves
        for fold in folds:
            wfr = WalkForwardResult(
                strategy_id=strategy.id,
                fold=fold.fold,
                train_start=fold.train_start,
                train_end=fold.train_end,
                test_start=fold.test_start,
                test_end=fold.test_end,
                metrics=fold.metrics,
                equity_curve=fold.equity_curve or [],
            )
            self.session.add(wfr)

        if passed:
            strategy.status = "candidate"
            self.session.commit()
            log_strategy_run(strategy.id, new_config, summary, "candidate")
            logger.info(f"Strategy {strategy.id} CANDIDATE: {summary}")
            return {"status": "candidate", "strategy_id": strategy.id, **summary}
        else:
            self.session.commit()
            log_strategy_run(strategy.id, new_config, summary, "rejected")
            logger.info(f"Strategy {strategy.id} REJECTED: {summary}")
            return {"status": "rejected", "strategy_id": strategy.id, **summary}

    def evaluate_config(self, config: dict, parent_strategy_id: int | None = None, generation: int = 0) -> tuple[list[dict], int | None]:
        """Evaluate and persist one concrete config for genetic/population search."""
        trainer = ModelTrainer(self.session, config)
        folds = trainer.walk_forward(
            self.tickers,
            min_train_years=5,
            holdout_cutoff=self._holdout_cutoff,
            apply_liquidity_filter=config.get("apply_liquidity_filter", True),
        )
        if not folds:
            return [], None

        fold_metrics = [f.metrics for f in folds]
        passed, summary = self.gate.evaluate(fold_metrics, n_features=len(config.get("features", [])))
        strategy = Strategy(
            name=f"search_gen{generation}_{'_'.join(config.get('features', [])[:3])}",
            config=config,
            parent_strategy_id=parent_strategy_id,
            generation=generation,
            status="candidate" if passed else "research",
            notes=json.dumps(summary),
        )
        self.session.add(strategy)
        self.session.flush()

        for fold in folds:
            self.session.add(WalkForwardResult(
                strategy_id=strategy.id,
                fold=fold.fold,
                train_start=fold.train_start,
                train_end=fold.train_end,
                test_start=fold.test_start,
                test_end=fold.test_end,
                metrics=fold.metrics,
                equity_curve=fold.equity_curve or [],
            ))

        self.session.commit()
        return fold_metrics, strategy.id

    def run_genetic(self, n_generations: int = 5, base_strategy_id: int | None = None) -> dict:
        base = self.session.get(Strategy, base_strategy_id) if base_strategy_id else None
        base_config = copy.deepcopy(base.config) if base and base.config else copy.deepcopy(self.base_config)
        from app.services.genetic_evolver import GeneticEvolver

        evolver = GeneticEvolver(
            evaluate_fn=lambda cfg: self.evaluate_config(
                cfg,
                parent_strategy_id=base_strategy_id,
                generation=(base.generation + 1) if base else 1,
            ),
            n=settings.genetic_population_size,
        )
        best = evolver.evolve(base_config, n_generations=n_generations)
        return {
            "status": "ok",
            "mode": "genetic",
            "best_strategy_id": best.strategy_id,
            "best_fitness": round(best.fitness_score, 4),
            "n_generations": n_generations,
        }

    def run_population(self, n_generations: int = 5, base_strategy_id: int | None = None, use_celery: bool = True) -> dict:
        base = self.session.get(Strategy, base_strategy_id) if base_strategy_id else None
        base_config = copy.deepcopy(base.config) if base and base.config else copy.deepcopy(self.base_config)
        from app.services.population_manager import PopulationManager

        manager = PopulationManager(
            evaluate_fn=lambda cfg: self.evaluate_config(
                cfg,
                parent_strategy_id=base_strategy_id,
                generation=(base.generation + 1) if base else 1,
            ),
            n=settings.population_search_size,
        )
        manager.seed(base_config)
        manager.evolve(n_generations=n_generations, use_celery=use_celery)
        return {"status": "ok", "mode": "population", **manager.summary()}

    def run_loop(
        self,
        n_iterations: int = 10,
        base_strategy_id: int | None = None,
        mode: str = "sequential",
        n_generations: int | None = None,
    ) -> list[dict]:
        if mode == "genetic":
            return [self.run_genetic(n_generations=n_generations or n_iterations, base_strategy_id=base_strategy_id)]
        if mode == "population":
            return [self.run_population(n_generations=n_generations or n_iterations, base_strategy_id=base_strategy_id)]

        results = []
        for i in range(n_iterations):
            logger.info(f"Research iteration {i + 1}/{n_iterations}")
            result = self.run_one_iteration(base_strategy_id)
            results.append(result)
            # If a strategy passed research gates, use it as next base while it paper-tests.
            if result.get("status") == "candidate":
                base_strategy_id = result.get("strategy_id")
        return results
