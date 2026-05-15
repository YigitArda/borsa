"""
Ablation test engine.

Tests the contribution of each feature group by training and backtesting
with subsets of features.  Baseline = all features.
"""
import copy
import logging
from dataclasses import dataclass

import numpy as np

from app.config import settings
from app.models.strategy import Strategy
from app.models.ablation import AblationResult
from app.services.model_training import ModelTrainer
from app.services.feature_engineering import (
    TECHNICAL_FEATURES,
    FINANCIAL_FEATURES,
    MACRO_FEATURES,
    NEWS_FEATURES,
    SOCIAL_FEATURES,
)

logger = logging.getLogger(__name__)

FEATURE_GROUPS = {
    "technical": TECHNICAL_FEATURES,
    "financial": FINANCIAL_FEATURES,
    "macro": MACRO_FEATURES,
    "news": NEWS_FEATURES,
    "sentiment": SOCIAL_FEATURES,
}


@dataclass
class AblationMetrics:
    sharpe: float
    profit_factor: float
    max_drawdown: float
    win_rate: float
    avg_return: float

    @classmethod
    def from_fold_metrics(cls, fold_metrics: list[dict]) -> "AblationMetrics":
        if not fold_metrics:
            return cls(0.0, 0.0, 0.0, 0.0, 0.0)
        return cls(
            sharpe=float(np.mean([m.get("sharpe", 0) for m in fold_metrics])),
            profit_factor=float(np.mean([m.get("profit_factor", 0) for m in fold_metrics])),
            max_drawdown=float(np.mean([m.get("max_drawdown", 0) for m in fold_metrics])),
            win_rate=float(np.mean([m.get("win_rate", 0) for m in fold_metrics])),
            avg_return=float(np.mean([m.get("avg_return", 0) for m in fold_metrics])),
        )

    def to_dict(self) -> dict:
        return {
            "sharpe": round(self.sharpe, 4),
            "profit_factor": round(self.profit_factor, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "win_rate": round(self.win_rate, 4),
            "avg_return": round(self.avg_return, 4),
        }


class AblationTester:
    """Run ablation tests by removing / isolating feature groups."""

    def __init__(self, session, tickers: list[str] | None = None):
        self.session = session
        self.tickers = tickers or settings.mvp_tickers

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_ablation_test(
        self,
        strategy_id: int,
        feature_groups: list[str] | None = None,
    ) -> list[dict]:
        """Run ablation for each requested feature group and persist results.

        Args:
            strategy_id: ID of the strategy to test.
            feature_groups: List of group names to test. Defaults to all groups.

        Returns:
            List of result dicts with metrics and impacts.
        """
        strategy = self.session.get(Strategy, strategy_id)
        if strategy is None:
            raise ValueError(f"Strategy {strategy_id} not found")

        base_config = copy.deepcopy(strategy.config)
        all_features = self._resolve_all_features(base_config)

        # Baseline — all features
        baseline_metrics = self.test_all_features(base_config)
        baseline = AblationMetrics.from_fold_metrics(baseline_metrics)

        results: list[dict] = []

        # Persist baseline
        baseline_record = self._persist(
            strategy_id=strategy_id,
            base_strategy_id=strategy_id,
            group_name="all",
            features_removed=[],
            metrics=baseline,
            baseline=baseline,
        )
        results.append(self._to_dict(baseline_record))

        groups = feature_groups or list(FEATURE_GROUPS.keys())
        for group_name in groups:
            if group_name not in FEATURE_GROUPS:
                logger.warning(f"Unknown feature group '{group_name}', skipping")
                continue

            test_fn = getattr(self, f"test_{group_name}_only", None)
            if test_fn is None:
                logger.warning(f"No test method for group '{group_name}', skipping")
                continue

            fold_metrics = test_fn(base_config)
            metrics = AblationMetrics.from_fold_metrics(fold_metrics)
            removed = [f for f in all_features if f not in self._resolve_features_for_group(base_config, group_name)]

            record = self._persist(
                strategy_id=strategy_id,
                base_strategy_id=strategy_id,
                group_name=group_name,
                features_removed=removed,
                metrics=metrics,
                baseline=baseline,
            )
            results.append(self._to_dict(record))

        # Combo tests
        for combo_name, combo_fn in [
            ("tech_macro", self.test_technical_macro),
            ("tech_financial", self.test_technical_financial),
        ]:
            if combo_name not in groups:
                continue
            fold_metrics = combo_fn(base_config)
            metrics = AblationMetrics.from_fold_metrics(fold_metrics)
            removed = [f for f in all_features if f not in self._resolve_features_for_combo(base_config, combo_name)]

            record = self._persist(
                strategy_id=strategy_id,
                base_strategy_id=strategy_id,
                group_name=combo_name,
                features_removed=removed,
                metrics=metrics,
                baseline=baseline,
            )
            results.append(self._to_dict(record))

        self.session.commit()
        return results

    # ------------------------------------------------------------------
    # Individual ablation tests
    # ------------------------------------------------------------------

    def test_technical_only(self, base_config: dict) -> list[dict]:
        """Train with only technical features."""
        cfg = self._subset_config(base_config, FEATURE_GROUPS["technical"])
        return self._run_walk_forward(cfg)

    def test_financial_only(self, base_config: dict) -> list[dict]:
        """Train with only financial features."""
        cfg = self._subset_config(base_config, FEATURE_GROUPS["financial"])
        return self._run_walk_forward(cfg)

    def test_news_only(self, base_config: dict) -> list[dict]:
        """Train with only news features."""
        cfg = self._subset_config(base_config, FEATURE_GROUPS["news"])
        return self._run_walk_forward(cfg)

    def test_macro_only(self, base_config: dict) -> list[dict]:
        """Train with only macro features."""
        cfg = self._subset_config(base_config, FEATURE_GROUPS["macro"])
        return self._run_walk_forward(cfg)

    def test_sentiment_only(self, base_config: dict) -> list[dict]:
        """Train with only sentiment (social) features."""
        cfg = self._subset_config(base_config, FEATURE_GROUPS["sentiment"])
        return self._run_walk_forward(cfg)

    def test_technical_macro(self, base_config: dict) -> list[dict]:
        """Train with technical + macro features."""
        features = FEATURE_GROUPS["technical"] + FEATURE_GROUPS["macro"]
        cfg = self._subset_config(base_config, features)
        return self._run_walk_forward(cfg)

    def test_technical_financial(self, base_config: dict) -> list[dict]:
        """Train with technical + financial features."""
        features = FEATURE_GROUPS["technical"] + FEATURE_GROUPS["financial"]
        cfg = self._subset_config(base_config, features)
        return self._run_walk_forward(cfg)

    def test_all_features(self, base_config: dict) -> list[dict]:
        """Baseline — train with all available features."""
        all_features = self._resolve_all_features(base_config)
        cfg = self._subset_config(base_config, all_features)
        return self._run_walk_forward(cfg)

    # ------------------------------------------------------------------
    # Impact computation
    # ------------------------------------------------------------------

    @staticmethod
    def compute_impacts(base_metrics: AblationMetrics, ablated_metrics: AblationMetrics) -> dict:
        """Compute relative impacts of removing features.

        Negative sharpe_impact means the ablated config is *worse* (good group).
        Positive drawdown_impact means drawdown improved (less negative).
        """
        def _safe_pct(base: float, ablated: float) -> float:
            if base == 0:
                return 0.0
            return round((ablated - base) / abs(base), 4)

        return {
            "sharpe_impact": _safe_pct(base_metrics.sharpe, ablated_metrics.sharpe),
            "profit_factor_impact": _safe_pct(base_metrics.profit_factor, ablated_metrics.profit_factor),
            "drawdown_impact": _safe_pct(base_metrics.max_drawdown, ablated_metrics.max_drawdown),
            "stability_score": round(
                (_safe_pct(base_metrics.sharpe, ablated_metrics.sharpe) +
                 _safe_pct(base_metrics.profit_factor, ablated_metrics.profit_factor) +
                 _safe_pct(base_metrics.max_drawdown, ablated_metrics.max_drawdown)) / 3,
                4,
            ),
        }

    @staticmethod
    def recommend_feature_groups(results: list[dict]) -> list[dict]:
        """Recommend which feature groups to keep or remove.

        Returns a list of recommendations sorted by importance.
        """
        baseline = next((r for r in results if r["feature_group"] == "all"), None)
        if baseline is None:
            return []

        recommendations = []
        for r in results:
            if r["feature_group"] == "all":
                continue

            sharpe_impact = r.get("sharpe_impact", 0)
            drawdown_impact = r.get("drawdown_impact", 0)
            stability = r.get("stability_score", 0)

            # Heuristic: if sharpe drops > 10% or drawdown worsens > 5%, keep the group
            if sharpe_impact < -0.10 or drawdown_impact < -0.05:
                action = "keep"
                reason = "significant performance degradation when removed"
            elif stability > 0.05:
                action = "optional"
                reason = "minor improvement when removed; consider pruning"
            else:
                action = "optional"
                reason = "minimal impact; safe to remove for simplicity"

            recommendations.append({
                "feature_group": r["feature_group"],
                "action": action,
                "reason": reason,
                "sharpe_impact": sharpe_impact,
                "drawdown_impact": drawdown_impact,
                "stability_score": stability,
            })

        recommendations.sort(key=lambda x: x["stability_score"])
        return recommendations

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _run_walk_forward(self, config: dict) -> list[dict]:
        """Run walk-forward validation and return fold metrics."""
        trainer = ModelTrainer(self.session, config)
        folds = trainer.walk_forward(self.tickers, min_train_years=5)
        return [f.metrics for f in folds]

    @staticmethod
    def _subset_config(base_config: dict, features: list[str]) -> dict:
        cfg = copy.deepcopy(base_config)
        cfg["features"] = features
        return cfg

    def _resolve_all_features(self, base_config: dict) -> list[str]:
        """Return the union of all known feature groups."""
        known = set()
        for group in FEATURE_GROUPS.values():
            known.update(group)
        configured = set(base_config.get("features", []))
        return sorted(list(known | configured))

    def _resolve_features_for_group(self, base_config: dict, group_name: str) -> list[str]:
        """Return the features that would be used for a single-group test."""
        return FEATURE_GROUPS.get(group_name, [])

    def _resolve_features_for_combo(self, base_config: dict, combo_name: str) -> list[str]:
        if combo_name == "tech_macro":
            return FEATURE_GROUPS["technical"] + FEATURE_GROUPS["macro"]
        if combo_name == "tech_financial":
            return FEATURE_GROUPS["technical"] + FEATURE_GROUPS["financial"]
        return []

    def _persist(
        self,
        strategy_id: int,
        base_strategy_id: int,
        group_name: str,
        features_removed: list[str],
        metrics: AblationMetrics,
        baseline: AblationMetrics,
    ) -> AblationResult:
        impacts = self.compute_impacts(baseline, metrics)
        record = AblationResult(
            strategy_id=strategy_id,
            base_strategy_id=base_strategy_id,
            feature_group=group_name,
            features_removed=features_removed,
            sharpe=metrics.sharpe,
            profit_factor=metrics.profit_factor,
            max_drawdown=metrics.max_drawdown,
            win_rate=metrics.win_rate,
            avg_return=metrics.avg_return,
            sharpe_impact=impacts["sharpe_impact"],
            profit_factor_impact=impacts["profit_factor_impact"],
            drawdown_impact=impacts["drawdown_impact"],
            stability_score=impacts["stability_score"],
        )
        self.session.add(record)
        self.session.flush()
        return record

    @staticmethod
    def _to_dict(record: AblationResult) -> dict:
        return {
            "id": record.id,
            "strategy_id": record.strategy_id,
            "feature_group": record.feature_group,
            "features_removed": record.features_removed,
            "sharpe": record.sharpe,
            "profit_factor": record.profit_factor,
            "max_drawdown": record.max_drawdown,
            "win_rate": record.win_rate,
            "avg_return": record.avg_return,
            "sharpe_impact": record.sharpe_impact,
            "profit_factor_impact": record.profit_factor_impact,
            "drawdown_impact": record.drawdown_impact,
            "stability_score": record.stability_score,
            "created_at": str(record.created_at) if record.created_at else None,
        }
