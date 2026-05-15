"""
Backtester with transaction costs, slippage, and walk-forward validation.

Entry: Friday close signal → Monday open (next trading day)
Exit: Following Friday close (1-week hold)
"""
import logging
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from app.config import settings

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
        returns = pd.Series([t.return_pct for t in self.trades])
        if returns.std() == 0 or len(returns) < 2:
            return 0.0
        return float(returns.mean() / returns.std() * np.sqrt(52))

    @property
    def sortino(self) -> float:
        returns = pd.Series([t.return_pct for t in self.trades])
        downside = returns[returns < 0].std()
        if downside == 0 or len(returns) < 2:
            return 0.0
        return float(returns.mean() / downside * np.sqrt(52))

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
        }


class Backtester:
    """
    Simulates weekly signal → trade execution.

    predictions_df: DataFrame with columns [week_ending, ticker, stock_id, prob]
    price_df: DataFrame with columns [date, ticker, open, close, high, low]
    threshold: minimum probability to take a trade
    top_n: max positions per week
    holding_weeks: how many weeks to hold (1, 2, or 4)
    stop_loss: max loss before forced exit (e.g. -0.05 = -5%)
    take_profit: profit target for early exit (e.g. 0.08 = +8%)
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
    ):
        self.predictions = predictions_df
        self.prices = price_df
        self.threshold = threshold
        self.top_n = top_n
        self.holding_weeks = holding_weeks
        self.stop_loss = stop_loss
        self.take_profit = take_profit

    def run(self) -> BacktestResult:
        trades: list[Trade] = []
        equity = 1.0
        equity_history = []

        weeks = sorted(self.predictions["week_ending"].unique())

        for week_end in weeks:
            week_preds = self.predictions[self.predictions["week_ending"] == week_end]
            candidates = week_preds[week_preds["prob"] >= self.threshold].nlargest(self.top_n, "prob")

            week_trades = []
            for _, row in candidates.iterrows():
                ticker = row["ticker"]
                entry_price = self._get_monday_open(ticker, week_end)
                exit_price = self._get_friday_close(ticker, week_end, offset=self.holding_weeks)

                if entry_price is None or exit_price is None:
                    continue

                # Stop-loss / take-profit: check intra-period daily prices
                exit_price, exit_reason = self._apply_sl_tp(
                    ticker, entry_price, week_end, exit_price
                )

                t = Trade(
                    ticker=ticker,
                    stock_id=int(row["stock_id"]),
                    entry_date=self._monday_after(week_end),
                    exit_date=self._friday_after(week_end, offset=self.holding_weeks),
                    entry_price=entry_price,
                    exit_price=exit_price,
                    signal_strength=float(row["prob"]),
                )
                week_trades.append(t)

            if week_trades:
                # Equal weight per position
                position_size = 1.0 / len(week_trades)
                week_return = sum(t.return_pct * position_size for t in week_trades)
                equity *= (1 + week_return)
                trades.extend(week_trades)

            equity_history.append((week_end, equity))

        equity_series = pd.Series(
            [e for _, e in equity_history],
            index=[w for w, _ in equity_history],
        ) if equity_history else pd.Series(dtype=float)

        return BacktestResult(trades=trades, equity_curve=equity_series)

    # ------------------------------------------------------------------

    def _apply_sl_tp(self, ticker: str, entry_price: float, week_end: date, planned_exit: float | None) -> tuple[float | None, str]:
        """Check intra-period daily prices for stop-loss/take-profit triggers."""
        if not self.stop_loss and not self.take_profit:
            return planned_exit, "normal"
        if entry_price is None or entry_price == 0:
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
