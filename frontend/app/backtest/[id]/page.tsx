import { loadApi } from "@/lib/server-api";

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

export default async function BacktestResultPage({ params }: { params: { id: string } }) {
  const { data: bt, error } = await loadApi<BacktestDetail>(`/backtest/${params.id}`);

  if (!bt) {
    return (
      <div style={{ maxWidth: "960px", margin: "0 auto" }}>
        <div className="alert alert-danger">{error || "Backtest not found."}</div>
      </div>
    );
  }

  const metrics = bt.metrics;

  const metricCards = [
    { label: "Sharpe", value: num(metrics.sharpe), good: (metrics.sharpe ?? 0) > 0.5 },
    { label: "Sortino", value: num(metrics.sortino), good: (metrics.sortino ?? 0) > 0.5 },
    { label: "Calmar", value: num(metrics.calmar), good: (metrics.calmar ?? 0) > 0.5 },
    { label: "CAGR", value: pct(metrics.cagr), good: (metrics.cagr ?? 0) > 0 },
    { label: "Max Drawdown", value: pct(metrics.max_drawdown), good: (metrics.max_drawdown ?? -1) > -0.15 },
    { label: "Win Rate", value: pct(metrics.win_rate), good: (metrics.win_rate ?? 0) > 0.5 },
    { label: "Profit Factor", value: num(metrics.profit_factor), good: (metrics.profit_factor ?? 0) > 1.2 },
    { label: "Avg Return/Trade", value: pct(metrics.avg_return), good: (metrics.avg_return ?? 0) > 0 },
    { label: "Precision", value: pct(metrics.precision), good: undefined },
    { label: "Recall", value: pct(metrics.recall), good: undefined },
    { label: "F1", value: pct(metrics.f1), good: undefined },
    { label: "Total Trades", value: String(metrics.n_trades ?? "—"), good: undefined },
  ];

  return (
    <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
      <h1>Backtest #{bt.id}</h1>
      <p style={{ marginBottom: "10px", color: "#666", fontSize: "11px" }}>
        Strategy #{bt.strategy_id} · Test: {bt.test_start} → {bt.test_end}
      </p>

      {error && <div className="alert alert-warning">{error}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: "8px", marginBottom: "12px" }}>
        {metricCards.map((card) => (
          <StatCard key={card.label} {...card} />
        ))}
      </div>

      <div className="box">
        <div className="box-head">Training Window</div>
        <div className="box-body">
          <table className="data-table">
            <tbody>
              <tr>
                <td><b>Train</b></td>
                <td>{bt.train_start} → {bt.train_end}</td>
                <td><b>Status</b></td>
                <td>{bt.status}</td>
              </tr>
              <tr>
                <td><b>Test</b></td>
                <td>{bt.test_start} → {bt.test_end}</td>
                <td><b>Strategy</b></td>
                <td>{bt.strategy_id}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="box" style={{ marginTop: "12px" }}>
        <div className="box-head">Metrics</div>
        <div className="box-body" style={{ padding: 0 }}>
          <table className="data-table" style={{ marginBottom: 0 }}>
            <thead>
              <tr>
                <th>Metric</th>
                <th>Value</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(metrics).map(([name, value]) => (
                <tr key={name}>
                  <td><b>{name}</b></td>
                  <td className={tone(name, value)}>{formatMetric(name, value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  good,
}: {
  label: string;
  value: string;
  good?: boolean;
}) {
  return (
    <div className="box" style={{ marginBottom: 0 }}>
      <div className="box-head">{label}</div>
      <div className="box-body">
        <div style={{ fontSize: "20px", fontWeight: "bold", color: good === undefined ? "#000" : good ? "#006600" : "#cc0000" }}>
          {value}
        </div>
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

function formatMetric(name: string, value: number): string {
  const pctMetrics = new Set([
    "cagr",
    "max_drawdown",
    "win_rate",
    "avg_return",
    "precision",
    "recall",
    "f1",
  ]);
  return pctMetrics.has(name) ? `${(value * 100).toFixed(2)}%` : value.toFixed(4);
}

function tone(name: string, value: number): string {
  if (name === "max_drawdown") return "text-red";
  if (["cagr", "win_rate", "avg_return", "precision", "recall", "f1"].includes(name)) {
    return value >= 0 ? "text-green" : "text-red";
  }
  return value >= 0 ? "text-green" : "text-red";
}
