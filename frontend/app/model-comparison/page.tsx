import { api } from "@/lib/api";

interface Strategy {
  id: number;
  name: string;
  status: string;
  generation: number;
  avg_metrics: Record<string, number | null>;
}

async function getStrategies(): Promise<Strategy[]> {
  try {
    const all = await api.get<{ id: number; name: string; status: string; generation: number }[]>("/strategies");
    const ids = all.map((s) => s.id).join(",");
    if (!ids) return [];
    return await api.get<Strategy[]>(`/research/compare?strategy_ids=${ids}`);
  } catch { return []; }
}

function Cell({ v, good }: { v: number | null | undefined; good?: boolean }) {
  if (v == null) return <td className="px-4 py-2 text-slate-500 text-center">—</td>;
  const color = good === undefined ? "text-white" : good ? "text-green-400" : "text-red-400";
  return <td className={`px-4 py-2 text-center font-mono ${color}`}>{v.toFixed(3)}</td>;
}

export default async function ModelComparison() {
  const strategies = await getStrategies();

  const metricKeys = [
    { key: "sharpe", label: "Sharpe", goodFn: (v: number) => v > 0.5 },
    { key: "sortino", label: "Sortino", goodFn: (v: number) => v > 0.5 },
    { key: "calmar", label: "Calmar", goodFn: (v: number) => v > 0.5 },
    { key: "cagr", label: "CAGR", goodFn: (v: number) => v > 0 },
    { key: "max_drawdown", label: "Max DD", goodFn: (v: number) => v > -0.2 },
    { key: "win_rate", label: "Win Rate", goodFn: (v: number) => v > 0.5 },
    { key: "profit_factor", label: "Profit Factor", goodFn: (v: number) => v > 1.2 },
    { key: "n_trades", label: "Trades", goodFn: (v: number) => v >= 30 },
  ];

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Model Comparison</h1>
        <p className="text-slate-400 text-sm mt-1">Average walk-forward metrics across all folds for each strategy.</p>
      </div>

      {strategies.length === 0 ? (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-8 text-center text-slate-400">
          No strategies found. Run the research loop first.
        </div>
      ) : (
        <div className="rounded-lg border border-slate-700 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-800 text-slate-400">
              <tr>
                <th className="px-4 py-3 text-left">Strategy</th>
                <th className="px-4 py-3 text-center">Status</th>
                <th className="px-4 py-3 text-center">Gen</th>
                {metricKeys.map((m) => (
                  <th key={m.key} className="px-4 py-3 text-center">{m.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {strategies.map((s) => (
                <tr key={s.strategy_id ?? s.id} className="border-t border-slate-700 hover:bg-slate-800/50">
                  <td className="px-4 py-2 text-white font-medium">{s.name}</td>
                  <td className="px-4 py-2 text-center">
                    <span className={`text-xs px-2 py-0.5 rounded ${s.status === "promoted" ? "text-green-400 bg-green-400/10" : "text-slate-400 bg-slate-700"}`}>
                      {s.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-center text-slate-400">{s.generation}</td>
                  {metricKeys.map((m) => (
                    <Cell
                      key={m.key}
                      v={s.avg_metrics?.[m.key]}
                      good={s.avg_metrics?.[m.key] != null ? m.goodFn(s.avg_metrics[m.key]!) : undefined}
                    />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
