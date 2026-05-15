"""
Bayesian hyperparameter optimization via Optuna.

Systematically searches threshold, top_n, embargo_weeks, holding_weeks,
model_type, n_estimators, max_depth using Tree-structured Parzen Estimator (TPE).

MedianPruner stops bad trials early (fold 0-2 Sharpe < 0.2).
Results persisted to hyperparam_trials table (restart-safe).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)

# How many Optuna trials to run per optimization call
DEFAULT_N_TRIALS = 50

# Optuna storage: use in-process (SQLite) for portability
# Override via OPTUNA_STORAGE env var for distributed setups
_OPTUNA_DB = "sqlite:///optuna_studies.db"


def _get_optuna_storage() -> str:
    import os
    return os.getenv("OPTUNA_STORAGE", _OPTUNA_DB)


class HyperparamOptimizer:
    """
    Wraps Optuna to perform TPE-based hyperparameter search for strategy configs.

    Usage:
        opt = HyperparamOptimizer(session, tickers, study_name="strategy_opt")
        best_config = opt.optimize(base_config, n_trials=50)
    """

    def __init__(self, session: Session, tickers: list[str], study_name: str = "borsa_strategy"):
        self.session = session
        self.tickers = tickers
        self.study_name = study_name

    # ------------------------------------------------------------------
    # Search space
    # ------------------------------------------------------------------

    def _build_config_from_trial(self, trial: Any, base_features: list[str]) -> dict:
        """Map Optuna trial parameters → strategy config dict."""
        return {
            "model_type": trial.suggest_categorical(
                "model_type", ["lightgbm", "random_forest", "xgboost"]
            ),
            "threshold": trial.suggest_float("threshold", 0.35, 0.75),
            "top_n": trial.suggest_int("top_n", 3, 10),
            "embargo_weeks": trial.suggest_int("embargo_weeks", 2, 8),
            "holding_weeks": trial.suggest_categorical("holding_weeks", [1, 2, 4]),
            "n_estimators": trial.suggest_int("n_estimators", 100, 500),
            "max_depth": trial.suggest_int("max_depth", 3, 8),
            "features": base_features,  # keep features from base config
            "target": "target_2pct_1w",
            "stop_loss": trial.suggest_categorical("stop_loss", [None, -0.03, -0.05, -0.07]),
            "take_profit": trial.suggest_categorical("take_profit", [None, 0.05, 0.08, 0.12]),
        }

    # ------------------------------------------------------------------
    # Objective
    # ------------------------------------------------------------------

    def _objective(self, trial: Any, base_features: list[str]) -> float:
        """Optuna objective: returns avg walk-forward Sharpe (to maximize)."""
        import optuna
        from app.services.model_training import ModelTrainer

        config = self._build_config_from_trial(trial, base_features)
        trainer = ModelTrainer(self.session, config)

        try:
            folds = trainer.walk_forward(self.tickers, min_train_years=5)
        except Exception as exc:
            logger.warning("Trial %d failed: %s", trial.number, exc)
            raise optuna.exceptions.TrialPruned()

        if not folds:
            raise optuna.exceptions.TrialPruned()

        sharpes = [f.metrics.get("sharpe", 0.0) for f in folds]

        # Early pruning: check first 3 folds
        if len(sharpes) >= 3:
            early_avg = sum(sharpes[:3]) / 3
            trial.report(early_avg, step=3)
            if trial.should_prune() or early_avg < 0.2:
                raise optuna.exceptions.TrialPruned()

        avg_sharpe = sum(sharpes) / len(sharpes) if sharpes else 0.0

        # Complexity penalty: more features → lower adjusted_sharpe
        n_features = len(base_features)
        adjusted_sharpe = avg_sharpe - 0.01 * n_features

        # Persist trial result
        self._save_trial(trial.number, config, adjusted_sharpe, "completed")

        return adjusted_sharpe

    # ------------------------------------------------------------------
    # Optimize
    # ------------------------------------------------------------------

    def optimize(
        self,
        base_config: dict,
        n_trials: int = DEFAULT_N_TRIALS,
    ) -> dict:
        """
        Run Optuna TPE optimization.

        Args:
            base_config: Strategy config to use as a starting point (features taken from here).
            n_trials:    Number of trials (default 50).

        Returns:
            Best config dict found. Falls back to base_config if all trials fail.
        """
        try:
            import optuna
            optuna.logging.set_verbosity(optuna.logging.WARNING)
        except ImportError:
            logger.error("optuna not installed — skipping Bayesian optimization")
            return base_config

        base_features = base_config.get("features", [])
        storage = _get_optuna_storage()

        try:
            study = optuna.create_study(
                direction="maximize",
                study_name=self.study_name,
                storage=storage,
                load_if_exists=True,
                pruner=optuna.pruners.MedianPruner(n_startup_trials=5, n_warmup_steps=2),
            )
        except Exception as exc:
            logger.warning("Could not connect to Optuna storage (%s), using in-memory study: %s", storage, exc)
            study = optuna.create_study(
                direction="maximize",
                pruner=optuna.pruners.MedianPruner(n_startup_trials=5, n_warmup_steps=2),
            )

        logger.info("Starting Optuna study '%s' with %d trials", self.study_name, n_trials)
        study.optimize(
            lambda trial: self._objective(trial, base_features),
            n_trials=n_trials,
            catch=(Exception,),
        )

        if study.best_trial is None or study.best_value is None:
            logger.warning("No successful Optuna trials — returning base config")
            return base_config

        best_params = study.best_params
        best_config = self._build_config_from_trial_params(best_params, base_features)
        logger.info(
            "Optuna best: sharpe=%.4f params=%s",
            study.best_value, best_params,
        )
        return best_config

    def _build_config_from_trial_params(self, params: dict, base_features: list[str]) -> dict:
        return {
            "model_type": params.get("model_type", "lightgbm"),
            "threshold": params.get("threshold", 0.5),
            "top_n": params.get("top_n", 5),
            "embargo_weeks": params.get("embargo_weeks", 4),
            "holding_weeks": params.get("holding_weeks", 1),
            "n_estimators": params.get("n_estimators", 200),
            "max_depth": params.get("max_depth", 4),
            "features": base_features,
            "target": "target_2pct_1w",
            "stop_loss": params.get("stop_loss"),
            "take_profit": params.get("take_profit"),
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_trial(self, trial_number: int, config: dict, sharpe: float, status: str) -> None:
        try:
            from app.models.hyperparam_trial import HyperparamTrial
            row = self.session.execute(
                select(HyperparamTrial).where(
                    HyperparamTrial.study_name == self.study_name,
                    HyperparamTrial.trial_number == trial_number,
                )
            ).scalar_one_or_none()
            if row is None:
                row = HyperparamTrial(study_name=self.study_name, trial_number=trial_number)
                self.session.add(row)
            row.params_json = config
            row.sharpe = round(sharpe, 4)
            row.status = status
            row.created_at = datetime.now(tz=timezone.utc).replace(tzinfo=None)
            self.session.commit()
        except Exception as exc:
            logger.debug("Could not persist Optuna trial: %s", exc)

    def get_best_from_db(self) -> dict | None:
        """Return best params from persisted trials (by sharpe)."""
        try:
            from app.models.hyperparam_trial import HyperparamTrial
            row = self.session.execute(
                select(HyperparamTrial)
                .where(HyperparamTrial.study_name == self.study_name, HyperparamTrial.status == "completed")
                .order_by(HyperparamTrial.sharpe.desc())
                .limit(1)
            ).scalar_one_or_none()
            return row.params_json if row else None
        except Exception:
            return None

    def status(self) -> dict:
        """Return summary of current Optuna study state."""
        try:
            import optuna
            optuna.logging.set_verbosity(optuna.logging.WARNING)
            study = optuna.load_study(study_name=self.study_name, storage=_get_optuna_storage())
            completed = [t for t in study.trials if t.state.name == "COMPLETE"]
            pruned = [t for t in study.trials if t.state.name == "PRUNED"]
            return {
                "study_name": self.study_name,
                "n_trials": len(study.trials),
                "n_completed": len(completed),
                "n_pruned": len(pruned),
                "best_value": study.best_value if completed else None,
                "best_params": study.best_params if completed else None,
            }
        except Exception as exc:
            return {"error": str(exc)}
