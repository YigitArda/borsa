"""
Backtester with transaction costs, slippage, walk-forward validation,
fractional Kelly position sizing, and market regime filtering.

Entry: Friday close signal → Monday open (next trading day)
Exit: Following Friday close (1-week hold)

Kelly sizing: position_size = kelly_fraction per trade (0 = equal weight).
Regime filter: multiplies position size by regime multiplier;
  bull → 1.0, sideways → 0.5, bear → 0.0 (skip week).
"""
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from app.config import settings

if TYPE_CHECKING:
    from app.services.regime_filter import RegimeFilter

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    ticker: str
    stock_id: int
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    signal_strength: float
    return_pct: float = field(init=False)
    pnl: float = field(init=False)

    def __post_init__(self):
        tc = (settings.transaction_cost_bps + settings.slippage_bps) / 10000
        if (
            self.entry_price is None
            or self.exit_price is None
            or not np.isfinite(self.entry_price)
            or not np.isfinite(self.exit_price)
            or self.entry_price <= 0
            or self.exit_price <= 0
        ):
            logger.warning(
                "Invalid trade prices for %s: entry=%s exit=%s",
                self.ticker,
                self.entry_price,
                self.exit_price,
            )
            self.return_pct = 0.0
            self.pnl = 0.0
            return
        raw_return = (self.exit_price - self.entry_price) / self.entry_price
        self.return_pct = raw_return - tc
        self.pnl = self.return_pct  # as fraction of capital


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: pd.Series

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t.return_pct > 0) / len(self.trades)

    @property
    def avg_return(self) -> float:
        if not self.trades:
            return 0.0
        return float(np.mean([t.return_pct for t in self.trades]))

    @property
    def sharpe(self) -> float:
        # Use portfolio-level weekly returns (from equity curve), not trade-level.
        # Trade-level returns with sqrt(52) overcount observations when top_n > 1.
        if self.equity_curve.empty or len(self.equity_curve) < 2:
            return 0.0
        weekly_rets = self.equity_curve.pct_change().dropna()
        if weekly_rets.std() == 0 or len(weekly_rets) < 2:
            return 0.0
        return float(weekly_rets.mean() / weekly_rets.std() * np.sqrt(52))

    @property
    def sortino(self) -> float:
        if self.equity_curve.empty or len(self.equity_curve) < 2:
            return 0.0
        weekly_rets = self.equity_curve.pct_change().dropna()
        downside = weekly_rets[weekly_rets < 0].std()
        if downside == 0 or len(weekly_rets) < 2:
            return 0.0
        return float(weekly_rets.mean() / downside * np.sqrt(52))

    @property
    def max_drawdown(self) -> float:
        if self.equity_curve.empty:
            return 0.0
        roll_max = self.equity_curve.cummax()
        drawdown = (self.equity_curve - roll_max) / roll_max
        return float(drawdown.min())

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.return_pct for t in self.trades if t.return_pct > 0)
        gross_loss = abs(sum(t.return_pct for t in self.trades if t.return_pct < 0))
        return gross_profit / gross_loss if gross_loss > 0 else float("inf")

    @property
    def cagr(self) -> float:
        if self.equity_curve.empty or len(self.equity_curve) < 2:
            return 0.0
        years = len(self.equity_curve) / 52
        final = float(self.equity_curve.iloc[-1])
        return float(final ** (1 / years) - 1) if years > 0 and final > 0 else 0.0

    @property
    def calmar(self) -> float:
        """CAGR / abs(max drawdown)."""
        dd = abs(self.max_drawdown)
        return float(self.cagr / dd) if dd > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "n_trades": self.n_trades,
            "win_rate": round(self.win_rate, 4),
            "avg_return": round(self.avg_return, 4),
            "sharpe": round(self.sharpe, 4),
            "sortino": round(self.sortino, 4),
            "calmar": round(self.calmar, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "profit_factor": round(self.profit_factor, 4) if self.profit_factor != float("inf") else 99.0,
            "cagr": round(self.cagr, 4),
            # Kelly & regime diagnostics (populated by caller if available)
            "kelly_fraction": None,
            "regime_weeks_skipped": None,
        }


class Backtester:
    """
    Simulates weekly signal → trade execution with Kelly sizing + regime filter.

    predictions_df: DataFrame with [week_ending, ticker, stock_id, prob]
    price_df:       DataFrame with [date, ticker, open, close, high, low]
    threshold:      Minimum probability to take a trade.
    top_n:          Max concurrent positions per week.
    holding_weeks:  Hold period in weeks (1, 2, or 4).
    stop_loss:      Max loss before forced exit (e.g. -0.05).
    take_profit:    Profit target for early exit (e.g. 0.08).
    kelly_fraction: Per-position Kelly fraction (0.0 = equal weight fallback).
    regime_filter:  Optional RegimeFilter instance; None = no regime gating.
    spike_detector: Optional IntradayEventDetector for spike-aware sizing.
    """

    def __init__(
        self,
        predictions_df: pd.DataFrame,
        price_df: pd.DataFrame,
        threshold: float = 0.5,
        top_n: int = 5,
        holding_weeks: int = 1,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        kelly_fraction: float = 0.0,
        regime_filter: "RegimeFilter | None" = None,
        spike_detector=None,
    ):
        self.predictions = predictions_df
        self.prices = price_df
        self.threshold = threshold
        self.top_n = top_n
        self.holding_weeks = holding_weeks
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.kelly_fraction = kelly_fraction
        self.regime_filter = regime_filter
        self.spike_detector = spike_detector

    def run(self, return_raw_trades: bool = False) -> BacktestResult:
        trades: list[Trade] = []
        equity = 1.0
        equity_history: list[tuple] = []

        weeks = sorted(self.predictions["week_ending"].unique())
        week_to_idx = {w: i for i, w in enumerate(weeks)}

        tc_bps = (settings.transaction_cost_bps + settings.slippage_bps) / 10000

        # open_positions: list of dicts tracking held positions across weeks
        # Each dict: {ticker, stock_id, prev_price, exit_price, exit_week_idx, size, trade}
        open_positions: list[dict] = []

        for week_end in weeks:
            # --- Regime gate ---
            regime_mult = 1.0
            if self.regime_filter is not None:
                regime_mult = self.regime_filter.multiplier_for_week(week_end)
                if regime_mult == 0.0:
                    equity_history.append((week_end, equity))
                    continue

            week_idx = week_to_idx[week_end]
            week_pnl = 0.0

            # --- Close expired positions & MTM remaining ---
            still_open: list[dict] = []
            for pos in open_positions:
                if pos["exit_week_idx"] == week_idx:
                    # Final leg: prev_price → exit_price (TC already deducted at entry)
                    prev_p = pos["prev_price"]
                    exit_p = pos["exit_price"]
                    if prev_p > 0 and exit_p > 0:
                        week_pnl += (exit_p - prev_p) / prev_p * pos["size"]
                    trades.append(pos["trade"])
                else:
                    # Mark-to-market: Friday close this week
                    current_p = self._get_friday_close(pos["ticker"], week_end, offset=0)
                    if current_p and current_p > 0:
                        week_pnl += (current_p - pos["prev_price"]) / pos["prev_price"] * pos["size"]
                        pos["prev_price"] = current_p
                    still_open.append(pos)
            open_positions = still_open

            # --- New entries (only fill available slots) ---
            n_active = len(open_positions)
            available_slots = self.top_n - n_active
            if available_slots > 0:
                week_preds = self.predictions[self.predictions["week_ending"] == week_end]
                candidates = week_preds[week_preds["prob"] >= self.threshold].nlargest(available_slots, "prob")

                new_entries: list[tuple] = []  # (Trade, ticker, entry_price, stock_id)
                for _, row in candidates.iterrows():
                    ticker = row["ticker"]
                    entry_p = self._get_monday_open(ticker, week_end)
                    raw_exit_p = self._get_friday_close(ticker, week_end, offset=self.holding_weeks)

                    if not entry_p or not raw_exit_p or entry_p <= 0 or raw_exit_p <= 0:
                        continue
                    if not np.isfinite(entry_p) or not np.isfinite(raw_exit_p):
                        continue

                    exit_p, _ = self._apply_sl_tp(ticker, entry_p, week_end, raw_exit_p)
                    if not exit_p or exit_p <= 0 or not np.isfinite(exit_p):
                        continue

                    t = Trade(
                        ticker=ticker,
                        stock_id=int(row["stock_id"]),
                        entry_date=self._monday_after(week_end),
                        exit_date=self._friday_after(week_end, offset=self.holding_weeks),
                        entry_price=entry_p,
                        exit_price=exit_p,
                        signal_strength=float(row["prob"]),
                    )
                    new_entries.append((t, ticker, entry_p, int(row["stock_id"])))

                if new_entries:
                    n_new = len(new_entries)
                    exit_week_idx = min(week_idx + self.holding_weeks, len(weeks) - 1)

                    for t, ticker, entry_p, stock_id in new_entries:
                        # Spike-aware position sizing: reduce size for high-spike-risk stocks
                        spike_mult = self._spike_multiplier(stock_id, week_end)
                        pos_size = self._position_size(n_new, regime_mult) * spike_mult

                        week_pnl -= tc_bps * pos_size  # entry TC
                        open_positions.append({
                            "ticker": ticker,
                            "stock_id": stock_id,
                            "prev_price": entry_p,
                            "exit_price": t.exit_price,
                            "exit_week_idx": exit_week_idx,
                            "size": pos_size,
                            "trade": t,
                        })

            equity *= (1 + week_pnl)
            equity_history.append((week_end, equity))

        # Flush positions that never reached their exit week (data ended)
        for pos in open_positions:
            trades.append(pos["trade"])

        equity_series = pd.Series(
            [e for _, e in equity_history],
            index=[w for w, _ in equity_history],
        ) if equity_history else pd.Series(dtype=float)

        result = BacktestResult(trades=trades, equity_curve=equity_series)
        if return_raw_trades:
            result._raw_trades = trades  # type: ignore[attr-defined]
        return result

    # ------------------------------------------------------------------

    def _position_size(self, n_positions: int, regime_mult: float) -> float:
        """Per-trade position size as fraction of total capital.

        Kelly mode: capped at equal-weight (1/top_n) to prevent leverage > 1.
        Equal-weight: 1/n_positions scaled by regime_mult.
        """
        if n_positions <= 0:
            return 0.0
        equal_weight = 1.0 / max(n_positions, self.top_n)
        if self.kelly_fraction > 0:
            # Kelly can't exceed equal-weight: prevents total deployment > 100%
            return min(self.kelly_fraction * regime_mult, equal_weight)
        return equal_weight * regime_mult

    def _spike_multiplier(self, stock_id: int, week_end) -> float:
        """Position size multiplier based on spike risk. 1.0 = no adjustment."""
        if self.spike_detector is None:
            return 1.0
        try:
            week_date = week_end.date() if hasattr(week_end, "date") else week_end
            prob = self.spike_detector.spike_probability(stock_id, week_date)
            # Linear scale: prob=0 → 1.0x, prob=0.5 → 0.7x, prob>=0.8 → 0.3x
            return max(0.3, 1.0 - prob * 0.875)
        except Exception:
            return 1.0

    def _apply_sl_tp(self, ticker: str, entry_price: float, week_end: date, planned_exit: float | None) -> tuple[float | None, str]:
        """Check intra-period daily prices for stop-loss/take-profit triggers."""
        if not self.stop_loss and not self.take_profit:
            return planned_exit, "normal"
        if entry_price is None or entry_price <= 0 or not np.isfinite(entry_price):
            return planned_exit, "normal"

        entry_date = self._monday_after(week_end)
        exit_date = self._friday_after(week_end, offset=self.holding_weeks)

        daily = self.prices[
            (self.prices["ticker"] == ticker) &
            (self.prices["date"] >= entry_date) &
            (self.prices["date"] <= exit_date)
        ].sort_values("date")

        for _, row in daily.iterrows():
            high = row.get("high") or row.get("close")
            low = row.get("low") or row.get("close")

            if self.take_profit and high and (high - entry_price) / entry_price >= self.take_profit:
                tp_price = entry_price * (1 + self.take_profit)
                return tp_price, "take_profit"

            if self.stop_loss and low and (low - entry_price) / entry_price <= self.stop_loss:
                sl_price = entry_price * (1 + self.stop_loss)
                return sl_price, "stop_loss"

        return planned_exit, "normal"

    def _get_monday_open(self, ticker: str, week_end: date) -> float | None:
        monday = self._monday_after(week_end)
        rows = self.prices[
            (self.prices["ticker"] == ticker) &
            (self.prices["date"] >= monday)
        ].sort_values("date")
        if rows.empty:
            return None
        return float(rows.iloc[0]["open"]) if pd.notna(rows.iloc[0]["open"]) else None

    def _get_friday_close(self, ticker: str, week_end: date, offset: int = 1) -> float | None:
        target_friday = self._friday_after(week_end, offset)
        rows = self.prices[
            (self.prices["ticker"] == ticker) &
            (self.prices["date"] <= target_friday)
        ].sort_values("date")
        if rows.empty:
            return None
        return float(rows.iloc[-1]["close"]) if pd.notna(rows.iloc[-1]["close"]) else None

    @staticmethod
    def _monday_after(week_end: date) -> date:
        from datetime import timedelta
        # week_end is Friday; Monday after = +3 days
        return week_end + timedelta(days=3)

    @staticmethod
    def _friday_after(week_end: date, offset: int = 1) -> date:
        from datetime import timedelta
        return week_end + timedelta(weeks=offset)
