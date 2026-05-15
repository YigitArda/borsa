import { api } from "@/lib/api";
import EquityChart from "@/components/charts/EquityChart";

interface BacktestDetail {
  id: number;
  strategy_id: number;
  status: string;
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  metrics: Record<string, number>;
}

async function getBacktest(id: string): Promise<BacktestDetail | null> {
  try { return await api.get<BacktestDetail>(`/backtest/${id}`); } catch { return null; }
}

function MetricCard({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
      <div className="text-xs text-slate-400">{label}</div>
      <div className={`text-xl font-bold mt-1 ${good === undefined ? "text-white" : good ? "text-green-400" : "text-red-400"}`}>
        {value}
      </div>
    </div>
  );
}

function pct(v: number | undefined) {
  return v != null ? `${(v * 100).toFixed(2)}%` : "—";
}

function num(v: number | undefined, decimals = 2) {
  return v != null ? v.toFixed(decimals) : "—";
}

export default async function BacktestResultPage({ params }: { params: { id: string } }) {
  const bt = await getBacktest(params.id);
  if (!bt) return <div className="p-8 text-slate-400">Backtest not found.</div>;

  const m = bt.metrics;

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Backtest #{bt.id}</h1>
        <p className="text-slate-400 text-sm">
          Strategy #{bt.strategy_id} · Test: {bt.test_start} → {bt.test_end}
        </p>
      </div>

      <div className="grid grid-cols-4 gap-4">
        <MetricCard label="Sharpe" value={num(m.sharpe)} good={(m.sharpe ?? 0) > 0.5} />
        <MetricCard label="Sortino" value={num(m.sortino)} good={(m.sortino ?? 0) > 0.5} />
        <MetricCard label="Calmar" value={num(m.calmar)} good={(m.calmar ?? 0) > 0.5} />
        <MetricCard label="CAGR" value={pct(m.cagr)} good={(m.cagr ?? 0) > 0} />
        <MetricCard label="Max Drawdown" value={pct(m.max_drawdown)} good={(m.max_drawdown ?? -1) > -0.15} />
        <MetricCard label="Win Rate" value={pct(m.win_rate)} good={(m.win_rate ?? 0) > 0.5} />
        <MetricCard label="Profit Factor" value={num(m.profit_factor)} good={(m.profit_factor ?? 0) > 1.2} />
        <MetricCard label="Avg Return/Trade" value={pct(m.avg_return)} good={(m.avg_return ?? 0) > 0} />
        <MetricCard label="Precision" value={pct(m.precision)} />
        <MetricCard label="Recall" value={pct(m.recall)} />
        <MetricCard label="F1" value={pct(m.f1)} />
        <MetricCard label="Total Trades" value={String(m.n_trades ?? "—")} />
      </div>

      <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
        <h2 className="text-lg font-semibold text-white mb-3">Training Window</h2>
        <div className="text-sm text-slate-400 space-y-1">
          <div>Train: <span className="text-white">{bt.train_start} → {bt.train_end}</span></div>
          <div>Test: <span className="text-white">{bt.test_start} → {bt.test_end}</span></div>
          <div>Status: <span className="text-yellow-400">{bt.status}</span></div>
        </div>
      </div>
    </div>
  );
}
