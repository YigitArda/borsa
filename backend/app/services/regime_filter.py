"""
Market regime filter for position sizing.

Translates detected market regime into a position-size multiplier.
Integrates with RegimeDetector (regime_detection.py) which persists
weekly regimes to the market_regimes table.

Rules (from spec):
  bull + low_vol  → full position  (1.0)
  bull            → full position  (1.0)
  low_vol         → full position  (1.0)
  risk_on         → 75%            (0.75)
  sideways        → 50%            (0.50)
  high_vol        → 25%            (0.25)
  risk_off        → 25%            (0.25)
  bear            → no trade       (0.0)
  bear + high_vol → no trade       (0.0)
  unknown         → conservative   (0.5)
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Sequence

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Position multiplier keyed by regime string from RegimeDetector.classify_regime()
REGIME_MULTIPLIERS: dict[str, float] = {
    "bull": 1.0,
    "low_vol": 1.0,
    "risk_on": 0.75,
    "sideways": 0.50,
    "high_vol": 0.25,
    "risk_off": 0.25,
    "bear": 0.0,
    "unknown": 0.50,  # conservative when regime is uncertain
}

# Opening new positions is blocked for these regimes
NO_TRADE_REGIMES: frozenset[str] = frozenset({"bear"})

# Existing positions should be closed when regime shifts to these
CLOSE_TRIGGER_REGIMES: frozenset[str] = frozenset({"bear", "high_vol", "risk_off"})


def get_position_multiplier(regime_type: str | None) -> float:
    """
    Return the position-size multiplier for a given regime label.

    bull → 1.0 (deploy capital fully)
    bear → 0.0 (stay in cash)
    """
    if regime_type is None:
        return 0.50
    return REGIME_MULTIPLIERS.get(regime_type, 0.50)


def should_close_positions(regime_type: str | None) -> bool:
    """Return True when the regime warrants closing all open positions."""
    if regime_type is None:
        return False
    return regime_type in CLOSE_TRIGGER_REGIMES


class RegimeFilter:
    """
    Week-level regime multiplier lookup backed by persisted MarketRegime rows.

    Usage in backtester:
        rf = RegimeFilter(session)
        rf.load(start, end)  # pre-load once
        mult = rf.multiplier_for_week(week_ending)
    """

    def __init__(self, session: Session):
        self.session = session
        # week_ending (date) → regime_type (str)
        self._cache: dict[date, str] = {}

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    def load(self, start: date, end: date) -> int:
        """
        Pre-load regime rows for [start, end] into local cache.
        Returns number of rows loaded.
        """
        from app.models.regime import MarketRegime
        from sqlalchemy import select

        rows = self.session.execute(
            select(MarketRegime).where(
                MarketRegime.week_ending >= start,
                MarketRegime.week_ending <= end,
            )
        ).scalars().all()

        for r in rows:
            self._cache[r.week_ending] = r.regime_type

        logger.debug("RegimeFilter: loaded %d regime rows (%s → %s)", len(rows), start, end)
        return len(rows)

    def load_from_dict(self, regime_map: dict[date, str]) -> None:
        """Load regimes from an externally computed dict (for testing / pipeline)."""
        self._cache.update(regime_map)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def regime_for_week(self, week_ending: date) -> str | None:
        """Return the regime label for a week, or None if not in cache."""
        return self._cache.get(week_ending)

    def multiplier_for_week(self, week_ending: date) -> float:
        """
        Return the position-size multiplier [0.0, 1.0] for a given week.
        Falls back to 0.50 (conservative) when regime is unknown.
        """
        regime = self._cache.get(week_ending)
        mult = get_position_multiplier(regime)
        if mult == 0.0:
            logger.debug("RegimeFilter: week %s regime=%s → NO TRADE", week_ending, regime)
        return mult

    def should_close_for_week(self, week_ending: date) -> bool:
        """Return True if regime this week requires closing all positions."""
        return should_close_positions(self._cache.get(week_ending))

    def as_series(self) -> dict[date, float]:
        """Return {week_ending: multiplier} for all cached weeks (useful for diagnostics)."""
        return {w: get_position_multiplier(r) for w, r in self._cache.items()}

    # ------------------------------------------------------------------
    # Detect + cache missing regimes on-the-fly
    # ------------------------------------------------------------------

    def detect_and_cache(self, weeks: Sequence[date]) -> int:
        """
        For weeks not already in cache, run RegimeDetector and persist.
        Returns number of weeks newly detected.
        """
        from app.services.regime_detection import RegimeDetector
        detector = RegimeDetector(self.session)
        count = 0
        for week in weeks:
            if week in self._cache:
                continue
            try:
                mr = detector.detect_regime_for_week(week)
                if mr:
                    self._cache[week] = mr.regime_type
                    count += 1
            except Exception as exc:
                logger.warning("Regime detection failed for %s: %s", week, exc)
        logger.info("RegimeFilter: detected %d new regimes", count)
        return count
