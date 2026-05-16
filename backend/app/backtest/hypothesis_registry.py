"""SQLite-backed hypothesis registry for falsifiable strategy research."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.time_utils import utcnow

logger = logging.getLogger(__name__)


@dataclass
class HypothesisEntry:
    """A single falsifiable trading hypothesis."""

    id: str
    name: str
    mechanism: str
    expected_edge: float
    asset_universe: str
    timeframe: str
    features: list[str] = field(default_factory=list)
    entry_rules: str = ""
    exit_rules: str = ""
    max_drawdown_tolerance: float = 0.20
    min_sharpe: float = 1.0
    min_win_rate: float = 0.35
    max_correlation_to_existing: float = 0.70
    status: str = "UNTESTED"
    created_at: str = field(default_factory=lambda: utcnow().isoformat())
    validated_at: str | None = None
    live_at: str | None = None
    decayed_at: str | None = None
    backtest_results: list[dict[str, Any]] = field(default_factory=list)
    live_results: list[dict[str, Any]] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HypothesisEntry":
        return cls(**data)


class HypothesisRegistry:
    """Lifecycle registry: UNTESTED -> VALIDATED -> LIVE -> DECAYED/REJECTED."""

    VALID_TRANSITIONS = {
        "UNTESTED": {"VALIDATED", "REJECTED"},
        "VALIDATED": {"LIVE", "REJECTED"},
        "LIVE": {"DECAYED", "REJECTED"},
        "DECAYED": {"UNTESTED"},
        "REJECTED": set(),
    }

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            import os
            db_path = os.environ.get(
                "HYPOTHESIS_REGISTRY_PATH",
                str(Path(__file__).resolve().parent.parent.parent / "data" / "hypothesis_registry.db"),
            )
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS hypotheses (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    mechanism TEXT NOT NULL,
                    expected_edge REAL,
                    asset_universe TEXT,
                    timeframe TEXT,
                    features TEXT,
                    entry_rules TEXT,
                    exit_rules TEXT,
                    max_drawdown_tolerance REAL DEFAULT 0.20,
                    min_sharpe REAL DEFAULT 1.0,
                    min_win_rate REAL DEFAULT 0.35,
                    max_correlation_to_existing REAL DEFAULT 0.70,
                    status TEXT DEFAULT 'UNTESTED',
                    created_at TEXT,
                    validated_at TEXT,
                    live_at TEXT,
                    decayed_at TEXT,
                    backtest_results TEXT,
                    live_results TEXT,
                    notes TEXT
                )
                """
            )
            conn.commit()

    def register(self, hypothesis: HypothesisEntry) -> bool:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO hypotheses
                    (id, name, mechanism, expected_edge, asset_universe, timeframe,
                     features, entry_rules, exit_rules, max_drawdown_tolerance,
                     min_sharpe, min_win_rate, max_correlation_to_existing, status,
                     created_at, validated_at, live_at, decayed_at,
                     backtest_results, live_results, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._entry_values(hypothesis),
                )
                conn.commit()
            logger.info("Registered hypothesis: %s (%s)", hypothesis.name, hypothesis.id)
            return True
        except sqlite3.IntegrityError:
            logger.warning("Hypothesis %s already exists", hypothesis.id)
            return False

    def upsert(self, hypothesis: HypothesisEntry) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO hypotheses
                (id, name, mechanism, expected_edge, asset_universe, timeframe,
                 features, entry_rules, exit_rules, max_drawdown_tolerance,
                 min_sharpe, min_win_rate, max_correlation_to_existing, status,
                 created_at, validated_at, live_at, decayed_at,
                 backtest_results, live_results, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    mechanism=excluded.mechanism,
                    expected_edge=excluded.expected_edge,
                    asset_universe=excluded.asset_universe,
                    timeframe=excluded.timeframe,
                    features=excluded.features,
                    entry_rules=excluded.entry_rules,
                    exit_rules=excluded.exit_rules,
                    max_drawdown_tolerance=excluded.max_drawdown_tolerance,
                    min_sharpe=excluded.min_sharpe,
                    min_win_rate=excluded.min_win_rate,
                    max_correlation_to_existing=excluded.max_correlation_to_existing,
                    status=excluded.status,
                    validated_at=excluded.validated_at,
                    live_at=excluded.live_at,
                    decayed_at=excluded.decayed_at,
                    backtest_results=excluded.backtest_results,
                    live_results=excluded.live_results,
                    notes=excluded.notes
                """,
                self._entry_values(hypothesis),
            )
            conn.commit()

    def update_status(
        self,
        hypothesis_id: str,
        new_status: str,
        results: list[dict[str, Any]] | None = None,
    ) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM hypotheses WHERE id = ?", (hypothesis_id,)
            ).fetchone()
            if row is None:
                return False

            current = row["status"]
            if new_status not in self.VALID_TRANSITIONS.get(current, set()):
                logger.error("Invalid hypothesis transition: %s -> %s", current, new_status)
                return False

            updates: dict[str, Any] = {"status": new_status}
            timestamp_field = {
                "VALIDATED": "validated_at",
                "LIVE": "live_at",
                "DECAYED": "decayed_at",
            }.get(new_status)
            if timestamp_field:
                updates[timestamp_field] = utcnow().isoformat()
            if results is not None:
                key = "live_results" if new_status in {"LIVE", "DECAYED"} else "backtest_results"
                updates[key] = json.dumps(results)

            set_clause = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE hypotheses SET {set_clause} WHERE id = ?",
                [*updates.values(), hypothesis_id],
            )
            conn.commit()
        return True

    def get(self, hypothesis_id: str) -> HypothesisEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM hypotheses WHERE id = ?", (hypothesis_id,)
            ).fetchone()
        return self._row_to_entry(dict(row)) if row else None

    def list(self, status: str | None = None) -> list[HypothesisEntry]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM hypotheses WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM hypotheses ORDER BY created_at DESC"
                ).fetchall()
        return [self._row_to_entry(dict(row)) for row in rows]

    def get_by_status(self, status: str) -> list[HypothesisEntry]:
        return self.list(status=status)

    def get_live_strategies(self) -> list[HypothesisEntry]:
        return self.get_by_status("LIVE")

    def get_validated_candidates(self) -> list[HypothesisEntry]:
        return self.get_by_status("VALIDATED")

    def export_all(self, filepath: str) -> None:
        rows = [entry.to_dict() for entry in self.list()]
        with open(filepath, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, indent=2, default=str)

    def _entry_values(self, h: HypothesisEntry) -> tuple[Any, ...]:
        return (
            h.id,
            h.name,
            h.mechanism,
            h.expected_edge,
            h.asset_universe,
            h.timeframe,
            json.dumps(h.features),
            h.entry_rules,
            h.exit_rules,
            h.max_drawdown_tolerance,
            h.min_sharpe,
            h.min_win_rate,
            h.max_correlation_to_existing,
            h.status,
            h.created_at,
            h.validated_at,
            h.live_at,
            h.decayed_at,
            json.dumps(h.backtest_results),
            json.dumps(h.live_results),
            h.notes,
        )

    def _row_to_entry(self, row: dict[str, Any]) -> HypothesisEntry:
        return HypothesisEntry(
            id=row["id"],
            name=row["name"],
            mechanism=row["mechanism"],
            expected_edge=row["expected_edge"],
            asset_universe=row["asset_universe"],
            timeframe=row["timeframe"],
            features=json.loads(row["features"]) if row["features"] else [],
            entry_rules=row["entry_rules"] or "",
            exit_rules=row["exit_rules"] or "",
            max_drawdown_tolerance=row["max_drawdown_tolerance"],
            min_sharpe=row["min_sharpe"],
            min_win_rate=row["min_win_rate"],
            max_correlation_to_existing=row["max_correlation_to_existing"],
            status=row["status"],
            created_at=row["created_at"],
            validated_at=row["validated_at"],
            live_at=row["live_at"],
            decayed_at=row["decayed_at"],
            backtest_results=json.loads(row["backtest_results"])
            if row["backtest_results"]
            else [],
            live_results=json.loads(row["live_results"]) if row["live_results"] else [],
            notes=row["notes"] or "",
        )
