"""
Q-Learning RL Agent for mutation type selection.

State:  compact vector derived from current strategy config + last 5 fold metrics.
        [n_features, threshold, top_n, model_type_idx, holding_weeks,
         avg_sharpe_5, avg_win_rate_5, avg_pf_5, avg_dd_5, sharpe_trend_5]
Actions: 8 mutation types (indices map to MUTATION_TYPES list).
Q-update: Q(s,a) ← Q(s,a) + lr × (reward + γ × max_a' Q(s',a') - Q(s,a))
Reward:   sharpe_delta (new_sharpe - old_sharpe)

Storage: DB-backed Q-table serialized as JSON in rl_agent_qtable table.
Epsilon-greedy exploration: starts at 0.30, decays by 0.01 per step (min 0.05).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MUTATION_TYPES = [
    "add_feature", "remove_feature", "change_threshold",
    "change_top_n", "change_model", "holding_period",
    "stop_loss", "take_profit",
]
N_ACTIONS = len(MUTATION_TYPES)

MODEL_TYPE_IDX = {
    "lightgbm": 0, "random_forest": 1, "xgboost": 2,
    "gradient_boosting": 3, "logistic_regression": 4, "neural_network": 5,
}

LEARNING_RATE = 0.1
DISCOUNT = 0.9
EPSILON_INIT = 0.30
EPSILON_MIN = 0.05
EPSILON_DECAY = 0.01


def _config_to_state(config: dict, recent_metrics: list[dict]) -> tuple:
    """
    Convert strategy config + recent fold metrics into a discrete state key.

    State is discretized to a tuple so it can be used as a dict key.
    """
    n_features = min(len(config.get("features", [])), 30)
    threshold_bin = int(config.get("threshold", 0.5) * 10)  # 0-10
    top_n = min(config.get("top_n", 5), 10)
    model_idx = MODEL_TYPE_IDX.get(config.get("model_type", "lightgbm"), 0)
    holding = config.get("holding_weeks", 1)

    # Last up to 5 metrics, padded with zeros
    sharpes = [m.get("sharpe", 0.0) for m in recent_metrics[-5:]]
    win_rates = [m.get("win_rate", 0.0) for m in recent_metrics[-5:]]

    avg_sharpe_bin = int(max(min(np.mean(sharpes) if sharpes else 0.0, 3.0), -1.0) * 4)
    avg_wr_bin = int((np.mean(win_rates) if win_rates else 0.5) * 10)

    # Sharpe trend: positive / zero / negative
    if len(sharpes) >= 2:
        trend = 1 if sharpes[-1] > sharpes[0] else (-1 if sharpes[-1] < sharpes[0] else 0)
    else:
        trend = 0

    return (n_features // 3, threshold_bin, top_n // 2, model_idx, holding,
            avg_sharpe_bin, avg_wr_bin, trend)


class RLStrategyAgent:
    """
    Tabular Q-learning agent for mutation type selection.

    Usage:
        agent = RLStrategyAgent(session)
        action_idx = agent.select_action(config, recent_metrics)
        mutation_type = MUTATION_TYPES[action_idx]
        # ... apply mutation, run walk-forward, compute reward ...
        agent.update(old_state, action_idx, reward, new_config, new_metrics)
        agent.save()
    """

    def __init__(self, session: Session, agent_name: str = "default"):
        self.session = session
        self.agent_name = agent_name
        self._q: dict[tuple, list[float]] = {}
        self._epsilon = EPSILON_INIT
        self._steps = 0
        self._loaded = False

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load Q-table from DB."""
        from app.models.rl_agent_qtable import RLAgentQTable
        row = self.session.execute(
            select(RLAgentQTable).where(RLAgentQTable.agent_name == self.agent_name)
        ).scalar_one_or_none()
        if row:
            raw = row.qtable_json
            # Keys stored as JSON strings; convert back to tuples
            self._q = {tuple(json.loads(k)): v for k, v in raw.items()}
            self._epsilon = row.epsilon
            self._steps = row.steps
            logger.info("RLAgent '%s': loaded Q-table (%d states, ε=%.3f)",
                        self.agent_name, len(self._q), self._epsilon)
        self._loaded = True

    def save(self) -> None:
        """Persist Q-table to DB."""
        from app.models.rl_agent_qtable import RLAgentQTable

        # Keys → JSON strings
        raw = {json.dumps(list(k)): v for k, v in self._q.items()}
        row = self.session.execute(
            select(RLAgentQTable).where(RLAgentQTable.agent_name == self.agent_name)
        ).scalar_one_or_none()
        if row is None:
            row = RLAgentQTable(agent_name=self.agent_name)
            self.session.add(row)
        row.qtable_json = raw
        row.epsilon = self._epsilon
        row.steps = self._steps
        row.last_updated = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def _get_q(self, state: tuple) -> list[float]:
        if state not in self._q:
            self._q[state] = [0.0] * N_ACTIONS
        return self._q[state]

    # ------------------------------------------------------------------
    # Action selection
    # ------------------------------------------------------------------

    def select_action(self, config: dict, recent_metrics: list[dict]) -> int:
        """
        Epsilon-greedy action selection.

        Returns action index (maps to MUTATION_TYPES[idx]).
        """
        self._ensure_loaded()
        state = _config_to_state(config, recent_metrics)
        if np.random.random() < self._epsilon:
            return np.random.randint(N_ACTIONS)
        q_vals = self._get_q(state)
        return int(np.argmax(q_vals))

    def action_name(self, action_idx: int) -> str:
        return MUTATION_TYPES[action_idx]

    # ------------------------------------------------------------------
    # Q-update
    # ------------------------------------------------------------------

    def update(
        self,
        old_config: dict,
        old_metrics: list[dict],
        action_idx: int,
        reward: float,
        new_config: dict,
        new_metrics: list[dict],
    ) -> None:
        """
        Q(s,a) ← Q(s,a) + lr × (reward + γ × max Q(s',·) - Q(s,a))
        """
        self._ensure_loaded()
        s = _config_to_state(old_config, old_metrics)
        s_next = _config_to_state(new_config, new_metrics)

        q_sa = self._get_q(s)[action_idx]
        q_next_max = max(self._get_q(s_next))

        td_target = reward + DISCOUNT * q_next_max
        self._get_q(s)[action_idx] = q_sa + LEARNING_RATE * (td_target - q_sa)

        # Epsilon decay
        self._steps += 1
        self._epsilon = max(EPSILON_MIN, EPSILON_INIT - EPSILON_DECAY * (self._steps // 10))

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def best_actions(self, config: dict, recent_metrics: list[dict]) -> list[dict]:
        """Return ranked mutation types by Q-value for current state."""
        self._ensure_loaded()
        state = _config_to_state(config, recent_metrics)
        q_vals = self._get_q(state)
        ranked = sorted(
            enumerate(q_vals), key=lambda x: x[1], reverse=True
        )
        return [
            {"mutation_type": MUTATION_TYPES[idx], "q_value": round(v, 4)}
            for idx, v in ranked
        ]

    def status(self) -> dict:
        self._ensure_loaded()
        return {
            "agent_name": self.agent_name,
            "n_states": len(self._q),
            "epsilon": round(self._epsilon, 4),
            "steps": self._steps,
        }
