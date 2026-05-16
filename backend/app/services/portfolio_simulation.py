"""
Portfolio simulation engine with capital allocation, sector limits,
position sizing, rebalancing, and exposure tracking.
"""
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class Position:
    ticker: str
    stock_id: int
    shares: float = 0.0
    avg_cost: float = 0.0
    market_value: float = 0.0
    sector: str | None = None

    def weight(self, total_value: float) -> float:
        return self.market_value / total_value if total_value else 0.0

    @property
    def unrealized_return(self) -> float:
        if self.avg_cost == 0:
            return 0.0
        return (self._current_price - self.avg_cost) / self.avg_cost

    _current_price: float = field(default=0.0, repr=False)


@dataclass
class PortfolioState:
    cash: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    date: date | None = None

    @property
    def invested_value(self) -> float:
        return sum(p.market_value for p in self.positions.values())

    @property
    def total_value(self) -> float:
        return self.cash + self.invested_value

    @property
    def n_positions(self) -> int:
        return len([p for p in self.positions.values() if p.shares > 0])

    def sector_exposure(self) -> dict[str, float]:
        tv = self.total_value
        if tv == 0:
            return {}
        exposure: dict[str, float] = {}
        for p in self.positions.values():
            if p.market_value > 0 and p.sector:
                exposure[p.sector] = exposure.get(p.sector, 0.0) + p.market_value / tv
        return exposure


@dataclass
class Signal:
    ticker: str
    stock_id: int
    prob: float
    expected_return: float | None = None
    sector: str | None = None


@dataclass
class SimulationConfig:
    initial_capital: float = 100_000.0
    max_positions: int = 5
    max_position_weight: float = 0.25
    sector_limit: float = 0.40
    cash_ratio: float = 0.10
    rebalance_frequency: str = "weekly"  # weekly | monthly | quarterly
    stop_loss: float | None = None
    take_profit: float | None = None
    transaction_cost_bps: float = 10.0
    slippage_bps: float = 5.0


@dataclass
class SimulationResult:
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    drawdown_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    monthly_returns: list[float] = field(default_factory=list)
    yearly_returns: dict[int, float] = field(default_factory=dict)
    worst_month: float = 0.0
    best_month: float = 0.0
    consecutive_losses: int = 0
    portfolio_volatility: float = 0.0
    sector_exposure_history: list[dict[str, Any]] = field(default_factory=list)
    snapshots: list[dict] = field(default_factory=list)
    trades_executed: int = 0


class PortfolioSimulator:
    """
    Simulates portfolio-level capital allocation over time.

    Inputs:
      - trades: list of dicts with keys:
          ticker, stock_id, entry_date, exit_date, entry_price, exit_price,
          return_pct, signal_strength, sector (optional)
      - config: SimulationConfig

    Outputs:
      - equity_curve, drawdown_curve, monthly_returns, yearly_returns,
        worst_month, best_month, consecutive_losses, portfolio_volatility,
        sector_exposure_history
    """

    def __init__(self, config: SimulationConfig | None = None):
        self.config = config or SimulationConfig()

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------

    def simulate(
        self,
        trades: list[dict],
        price_df: pd.DataFrame | None = None,
    ) -> SimulationResult:
        """Run full portfolio simulation from a list of trades."""
        if not trades:
            return SimulationResult()

        portfolio = PortfolioState(cash=self.config.initial_capital)
        snapshots: list[dict] = []
        all_dates = self._extract_all_dates(trades)

        # Pre-index trades by entry date for allocation
        trades_by_date: dict[date, list[dict]] = {}
        for t in trades:
            d = t["entry_date"]
            if isinstance(d, str):
                d = pd.to_datetime(d).date()
            trades_by_date.setdefault(d, []).append(t)

        # Pre-index prices by (ticker, date)
        price_lookup: dict[tuple[str, date], float] = {}
        if price_df is not None and not price_df.empty:
            for _, row in price_df.iterrows():
                d = row["date"]
                if isinstance(d, str):
                    d = pd.to_datetime(d).date()
                price_lookup[(row["ticker"], d)] = float(row.get("close", row.get("open", 0)))

        prev_month: int | None = None
        month_start_value = self.config.initial_capital
        prev_year: int | None = None
        year_start_value = self.config.initial_capital
        running_peak = self.config.initial_capital

        for current_date in sorted(all_dates):
            portfolio.date = current_date

            # 1. Exit positions whose exit_date == current_date
            portfolio = self._process_exits(portfolio, trades, current_date, price_lookup)

            # 2. Enter new positions for trades starting today
            day_trades = trades_by_date.get(current_date, [])
            if day_trades:
                signals = [
                    Signal(
                        ticker=t["ticker"],
                        stock_id=t["stock_id"],
                        prob=t.get("signal_strength", 0.5),
                        expected_return=t.get("return_pct"),
                        sector=t.get("sector"),
                    )
                    for t in day_trades
                ]
                portfolio = self._enter_positions(portfolio, signals, day_trades, price_lookup)

            # 3. Update mark-to-market for open positions
            portfolio = self._mark_to_market(portfolio, current_date, price_lookup)

            # 4. Apply stop-loss / take-profit
            portfolio = self._apply_risk_rules(portfolio, current_date, price_lookup)

            # 5. Periodic rebalance
            portfolio = self._rebalance(portfolio, current_date)

            # 6. Record snapshot
            running_peak = max(running_peak, portfolio.total_value)
            snap = self._record_snapshot(
                portfolio,
                current_date,
                month_start_value,
                year_start_value,
                prev_month,
                prev_year,
                running_peak,
            )
            snapshots.append(snap)

            # Update period tracking
            if prev_month is None or current_date.month != prev_month:
                month_start_value = portfolio.total_value
                prev_month = current_date.month
            if prev_year is None or current_date.year != prev_year:
                year_start_value = portfolio.total_value
                prev_year = current_date.year

        result = self._build_result(snapshots)
        return result

    def allocate_capital(
        self,
        signals: list[Signal],
        current_portfolio: PortfolioState,
    ) -> dict[str, float]:
        """Return target dollar allocation per ticker."""
        if not signals:
            return {}

        total_value = current_portfolio.total_value
        investable = total_value * (1 - self.config.cash_ratio)
        n = min(len(signals), self.config.max_positions)

        # Signal-strength proportional sizing
        total_prob = sum(s.prob for s in signals[:n])
        if total_prob == 0:
            total_prob = n

        allocations: dict[str, float] = {}
        for s in signals[:n]:
            weight = (s.prob / total_prob) if total_prob > 0 else (1.0 / n)
            dollar = investable * weight
            # Cap at max_position_weight
            max_dollar = total_value * self.config.max_position_weight
            allocations[s.ticker] = min(dollar, max_dollar)

        return allocations

    def apply_sector_limits(
        self,
        positions: dict[str, Position],
        sector_limit: float | None = None,
    ) -> dict[str, Position]:
        """Trim positions to enforce sector concentration limits."""
        limit = sector_limit if sector_limit is not None else self.config.sector_limit
        if limit <= 0 or limit >= 1.0:
            return positions

        # Compute current sector exposure
        sector_vals: dict[str, float] = {}
        total = sum(p.market_value for p in positions.values())
        if total == 0:
            return positions

        for p in positions.values():
            if p.sector:
                sector_vals[p.sector] = sector_vals.get(p.sector, 0.0) + p.market_value

        # Scale down sectors that exceed limit
        for sector, val in sector_vals.items():
            exposure = val / total
            if exposure > limit:
                scale = limit / exposure
                for p in positions.values():
                    if p.sector == sector:
                        p.shares *= scale
                        p.market_value *= scale
        return positions

    def apply_position_limits(
        self,
        positions: dict[str, Position],
        max_weight: float | None = None,
        total_value: float = 0.0,
    ) -> dict[str, Position]:
        """Trim individual positions to max weight."""
        mw = max_weight if max_weight is not None else self.config.max_position_weight
        if mw <= 0 or mw >= 1.0 or total_value <= 0:
            return positions

        for p in positions.values():
            max_val = total_value * mw
            if p.market_value > max_val:
                scale = max_val / p.market_value if p.market_value > 0 else 0.0
                p.shares *= scale
                p.market_value = max_val
        return positions

    def rebalance(
        self,
        portfolio: PortfolioState,
        frequency: str | None = None,
    ) -> PortfolioState:
        """Periodic rebalancing — trims overweight positions back to target."""
        freq = frequency or self.config.rebalance_frequency
        if freq == "none":
            return portfolio

        # In a full implementation this would check calendar dates;
        # here we treat each call as a rebalance trigger.
        total = portfolio.total_value
        if total == 0:
            return portfolio

        target_weight = 1.0 / self.config.max_positions if self.config.max_positions > 0 else 0.2
        for p in portfolio.positions.values():
            w = p.weight(total)
            if w > target_weight * 1.2:  # 20% tolerance
                target_val = total * target_weight
                scale = target_val / p.market_value if p.market_value > 0 else 0.0
                p.shares *= scale
                p.market_value = target_val
        return portfolio

    def compute_monthly_returns(self, snapshots: list[dict]) -> list[float]:
        """Return list of monthly returns from snapshot series."""
        if not snapshots:
            return []

        df = pd.DataFrame(snapshots)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        monthly = df["total_value"].resample("ME").last()
        returns = monthly.pct_change().dropna().tolist()
        return [float(r) for r in returns]

    def compute_yearly_returns(self, snapshots: list[dict]) -> dict[int, float]:
        """Return {year: return} from snapshot series."""
        if not snapshots:
            return {}

        df = pd.DataFrame(snapshots)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        yearly = df["total_value"].resample("YE").last()
        returns = yearly.pct_change().dropna()
        return {int(k.year): float(v) for k, v in returns.items()}

    def compute_consecutive_losses(self, snapshots: list[dict]) -> int:
        """Maximum consecutive losing months."""
        monthly = self.compute_monthly_returns(snapshots)
        if not monthly:
            return 0

        max_streak = 0
        current = 0
        for r in monthly:
            if r < 0:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    def compute_exposure(self, snapshots: list[dict]) -> dict[str, list]:
        """Cash vs invested exposure over time."""
        if not snapshots:
            return {"dates": [], "cash_pct": [], "invested_pct": []}

        dates = [s["date"] for s in snapshots]
        cash_pcts = [
            s["cash_value"] / s["total_value"] if s["total_value"] else 0.0
            for s in snapshots
        ]
        invested_pcts = [
            s["invested_value"] / s["total_value"] if s["total_value"] else 0.0
            for s in snapshots
        ]
        return {
            "dates": dates,
            "cash_pct": cash_pcts,
            "invested_pct": invested_pcts,
        }

    # ------------------------------------------------------------------
    #  Internal helpers
    # ------------------------------------------------------------------

    def _extract_all_dates(self, trades: list[dict]) -> set[date]:
        dates: set[date] = set()
        for t in trades:
            for key in ("entry_date", "exit_date"):
                d = t.get(key)
                if d is None:
                    continue
                if isinstance(d, str):
                    d = pd.to_datetime(d).date()
                dates.add(d)
        return dates

    def _process_exits(
        self,
        portfolio: PortfolioState,
        trades: list[dict],
        current_date: date,
        price_lookup: dict,
    ) -> PortfolioState:
        for t in trades:
            exit_date = t["exit_date"]
            if isinstance(exit_date, str):
                exit_date = pd.to_datetime(exit_date).date()
            if exit_date != current_date:
                continue

            ticker = t["ticker"]
            pos = portfolio.positions.get(ticker)
            if not pos or pos.shares <= 0:
                continue

            exit_price = t.get("exit_price", 0.0)
            if exit_price == 0.0:
                exit_price = price_lookup.get((ticker, current_date), 0.0)

            tc = (self.config.transaction_cost_bps + self.config.slippage_bps) / 10000
            proceeds = pos.shares * exit_price * (1 - tc)
            portfolio.cash += proceeds
            pos.shares = 0.0
            pos.market_value = 0.0

        return portfolio

    def _enter_positions(
        self,
        portfolio: PortfolioState,
        signals: list[Signal],
        trades: list[dict],
        price_lookup: dict,
    ) -> PortfolioState:
        allocations = self.allocate_capital(signals, portfolio)
        trade_map = {t["ticker"]: t for t in trades}

        for ticker, dollar in allocations.items():
            if dollar <= 0 or portfolio.cash < dollar:
                continue

            t = trade_map.get(ticker)
            if not t:
                continue

            entry_price = t.get("entry_price", 0.0)
            if entry_price == 0.0:
                d = t["entry_date"]
                if isinstance(d, str):
                    d = pd.to_datetime(d).date()
                entry_price = price_lookup.get((ticker, d), 0.0)

            if entry_price <= 0:
                continue

            tc = (self.config.transaction_cost_bps + self.config.slippage_bps) / 10000
            shares = dollar / (entry_price * (1 + tc))
            cost = shares * entry_price * (1 + tc)

            if portfolio.cash < cost:
                continue

            portfolio.cash -= cost
            pos = portfolio.positions.get(ticker)
            if pos is None:
                pos = Position(
                    ticker=ticker,
                    stock_id=t["stock_id"],
                    sector=t.get("sector"),
                )
                portfolio.positions[ticker] = pos

            # Averaging in
            total_cost = pos.avg_cost * pos.shares + cost
            pos.shares += shares
            pos.avg_cost = total_cost / pos.shares if pos.shares > 0 else 0.0
            pos.market_value = pos.shares * entry_price
            pos._current_price = entry_price

        return portfolio

    def _mark_to_market(
        self,
        portfolio: PortfolioState,
        current_date: date,
        price_lookup: dict,
    ) -> PortfolioState:
        for pos in portfolio.positions.values():
            if pos.shares <= 0:
                continue
            price = price_lookup.get((pos.ticker, current_date))
            if price is not None and price > 0:
                pos._current_price = price
                pos.market_value = pos.shares * price
        return portfolio

    def _apply_risk_rules(
        self,
        portfolio: PortfolioState,
        current_date: date,
        price_lookup: dict,
    ) -> PortfolioState:
        for pos in list(portfolio.positions.values()):
            if pos.shares <= 0 or pos.avg_cost == 0:
                continue

            price = pos._current_price
            if price <= 0:
                continue

            ret = (price - pos.avg_cost) / pos.avg_cost

            if self.config.stop_loss and ret <= self.config.stop_loss:
                tc = (self.config.transaction_cost_bps + self.config.slippage_bps) / 10000
                proceeds = pos.shares * price * (1 - tc)
                portfolio.cash += proceeds
                pos.shares = 0.0
                pos.market_value = 0.0
                logger.debug(f"Stop-loss hit for {pos.ticker} on {current_date}")

            elif self.config.take_profit and ret >= self.config.take_profit:
                tc = (self.config.transaction_cost_bps + self.config.slippage_bps) / 10000
                proceeds = pos.shares * price * (1 - tc)
                portfolio.cash += proceeds
                pos.shares = 0.0
                pos.market_value = 0.0
                logger.debug(f"Take-profit hit for {pos.ticker} on {current_date}")

        return portfolio

    def _rebalance(
        self,
        portfolio: PortfolioState,
        current_date: date,
    ) -> PortfolioState:
        return self.rebalance(portfolio)

    def _record_snapshot(
        self,
        portfolio: PortfolioState,
        current_date: date,
        month_start_value: float,
        year_start_value: float,
        prev_month: int | None,
        prev_year: int | None,
        running_peak: float = 0.0,
    ) -> dict:
        tv = portfolio.total_value
        monthly_return = None
        if prev_month is not None and month_start_value > 0:
            monthly_return = (tv - month_start_value) / month_start_value

        ytd_return = None
        if prev_year is not None and year_start_value > 0:
            ytd_return = (tv - year_start_value) / year_start_value

        # Peak-to-trough drawdown from all-time high
        peak = running_peak if running_peak > 0 else tv
        drawdown = (tv - peak) / peak if peak > 0 else 0.0

        return {
            "date": current_date,
            "total_value": tv,
            "cash_value": portfolio.cash,
            "invested_value": portfolio.invested_value,
            "n_positions": portfolio.n_positions,
            "sector_exposure": portfolio.sector_exposure(),
            "monthly_return": monthly_return,
            "ytd_return": ytd_return,
            "drawdown": drawdown,
        }

    def _build_result(self, snapshots: list[dict]) -> SimulationResult:
        if not snapshots:
            return SimulationResult()

        df = pd.DataFrame(snapshots)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()

        equity = df["total_value"]
        roll_max = equity.cummax()
        drawdown = (equity - roll_max) / roll_max

        monthly = self.compute_monthly_returns(snapshots)
        yearly = self.compute_yearly_returns(snapshots)
        cons_losses = self.compute_consecutive_losses(snapshots)
        exposure = self.compute_exposure(snapshots)

        vol = 0.0
        if len(monthly) > 1:
            vol = float(np.std(monthly, ddof=1) * np.sqrt(12))

        return SimulationResult(
            equity_curve=equity,
            drawdown_curve=drawdown,
            monthly_returns=monthly,
            yearly_returns=yearly,
            worst_month=min(monthly) if monthly else 0.0,
            best_month=max(monthly) if monthly else 0.0,
            consecutive_losses=cons_losses,
            portfolio_volatility=vol,
            sector_exposure_history=exposure["dates"],
            snapshots=snapshots,
            trades_executed=len(snapshots),
        )
