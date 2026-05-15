"""Optional MLflow tracking hooks.

The core app does not require MLflow to run. If mlflow is installed and
MLFLOW_TRACKING_URI is configured, research iterations are logged as MLflow
runs for model/strategy operations review.
"""
from __future__ import annotations

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


def log_strategy_run(strategy_id: int, config: dict[str, Any], metrics: dict[str, Any], status: str) -> None:
    if not settings.mlflow_tracking_uri:
        return

    try:
        import mlflow
    except ImportError:
        logger.warning("MLflow tracking URI configured but mlflow package is not installed")
        return

    try:
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_experiment(settings.mlflow_experiment_name)
        with mlflow.start_run(run_name=f"strategy_{strategy_id}_{status}"):
            mlflow.set_tag("strategy_id", strategy_id)
            mlflow.set_tag("status", status)
            for key, value in config.items():
                if isinstance(value, (str, int, float, bool)) or value is None:
                    mlflow.log_param(key, value)
                elif key == "features":
                    mlflow.log_param("n_features", len(value or []))
            for key, value in metrics.items():
                if isinstance(value, (int, float)):
                    mlflow.log_metric(key, float(value))
    except Exception as exc:
        logger.warning("MLflow logging failed for strategy %s: %s", strategy_id, exc)
