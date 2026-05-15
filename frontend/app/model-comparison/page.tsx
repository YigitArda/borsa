"use client";

import { useState, useEffect } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer } from "recharts";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Strategy {
  strategy_id?: number;
  id?: number;
  name: string;
  status: string;
  generation: number;
  avg_metrics: Record<string, number | null>;
}

interface RollingPoint {
  fold: number;
  test_start: string;
  rolling_sharpe: number;
}

const COLORS = ["#60a5fa", "#34d399", "#f59e0b", "#f87171", "#a78bfa", "#fb923c"];

function Cell({ v, good }: { v: number | null | undefined; good?: boolean }) {
  if (v == null) return <td className="px-4 py-2 text-slate-500 text-center">—</td>;
  const color = good === undefined ? "text-white" : good ? "text-green-400" : "text-red-400";
  return <td className={`px-4 py-2 text-center font-mono ${color}`}>{v.toFixed(3)}</td>;
}

export default function ModelComparison() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [rollingData, setRollingData] = useState<Record<number, RollingPoint[]>>({});
  const [selectedIds, setSelectedIds] = useState<number[]>([]);

  useEffect(() => {
    fetch(`${API}/strategies`)
      .then((r) => r.json())
      .then(async (all: { id: number; name: string; status: string; generation: number }[]) => {
        if (!all.length) return;
        const ids = all.map((s) => s.id).join(",");
        const compared = await fetch(`${API}/research/compare?strategy_ids=${ids}`).then((r) => r.json());
        setStrategies(compared);
        // Load rolling sharpe for promoted strategies
        const promoted = compared.filter((s: Strategy) => s.status === "promoted");
        const rolling: Record<number, RollingPoint[]> = {};
        await Promise.all(
          promoted.map(async (s: Strategy) => {
            const sid = s.strategy_id ?? s.id ?? 0;
            const d = await fetch(`${API}/research/rolling-sharpe/${sid}`).then((r) => r.json());
            rolling[sid] = d.rolling_sharpe || [];
          })
        );
        setRollingData(rolling);
        setSelectedIds(promoted.slice(0, 3).map((s: Strategy) => s.strategy_id ?? s.id ?? 0));
      })
      .catch(() => {});
  }, []);

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

  // Build chart data by aligning folds across strategies
  const chartPoints: Record<string, number | string>[] = [];
  if (selectedIds.length > 0) {
    const maxLen = Math.max(...selectedIds.map((id) => (rollingData[id] || []).length));
    for (let i = 0; i < maxLen; i++) {
      const point: Record<string, number | string> = { fold: i };
      for (const sid of selectedIds) {
        const arr = rollingData[sid] || [];
        if (arr[i]) {
          point[`strategy_${sid}`] = arr[i].rolling_sharpe;
          if (i === 0 || !point.test_start) point.test_start = arr[i].test_start;
        }
      }
      chartPoints.push(point);
    }
  }

  function toggleSelected(sid: number) {
    setSelectedIds((prev) => prev.includes(sid) ? prev.filter((x) => x !== sid) : [...prev, sid]);
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Model Comparison</h1>
        <p className="text-slate-400 text-sm mt-1">Average walk-forward metrics and rolling Sharpe across strategies.</p>
      </div>

      {strategies.length === 0 ? (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-8 text-center text-slate-400">
          No strategies found. Run the research loop first.
        </div>
      ) : (
        <>
          {/* Metrics table */}
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
                  <th className="px-4 py-3 text-center">Chart</th>
                </tr>
              </thead>
              <tbody>
                {strategies.map((s, idx) => {
                  const sid = s.strategy_id ?? s.id ?? 0;
                  return (
                    <tr key={sid} className="border-t border-slate-700 hover:bg-slate-800/50">
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
                      <td className="px-4 py-2 text-center">
                        {rollingData[sid] && (
                          <button
                            onClick={() => toggleSelected(sid)}
                            className={`w-3 h-3 rounded-full border-2 transition-colors ${selectedIds.includes(sid) ? "border-transparent" : "border-slate-500 bg-transparent"}`}
                            style={selectedIds.includes(sid) ? { backgroundColor: COLORS[idx % COLORS.length] } : {}}
                          />
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Rolling Sharpe chart */}
          {chartPoints.length > 0 && (
            <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
              <h2 className="text-base font-semibold text-white mb-4">Rolling Sharpe (4-fold window)</h2>
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={chartPoints}>
                  <XAxis dataKey="fold" stroke="#64748b" tick={{ fontSize: 10 }} />
                  <YAxis stroke="#64748b" tick={{ fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155" }}
                    labelStyle={{ color: "#94a3b8" }}
                  />
                  <Legend />
                  {selectedIds.map((sid, idx) => (
                    <Line
                      key={sid}
                      type="monotone"
                      dataKey={`strategy_${sid}`}
                      name={`Strategy #${sid}`}
                      stroke={COLORS[idx % COLORS.length]}
                      dot={false}
                      strokeWidth={2}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
    </div>
  );
}
