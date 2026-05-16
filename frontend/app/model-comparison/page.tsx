"use client";

import { useEffect, useState } from "react";
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

const COLORS = ["#336699", "#6699cc", "#cc9900", "#006600", "#cc0000", "#666666"];

function Cell({ value, good }: { value: number | null | undefined; good?: boolean }) {
  if (value == null) return <td style={{ textAlign: "center", color: "#666" }}>—</td>;
  const color = good === undefined ? "#000" : good ? "#006600" : "#cc0000";
  return <td style={{ textAlign: "center", fontFamily: "monospace", color, fontWeight: "bold" }}>{value.toFixed(3)}</td>;
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

        const promoted = compared.filter((s: Strategy) => s.status === "promoted");
        const rolling: Record<number, RollingPoint[]> = {};
        await Promise.all(
          promoted.map(async (s: Strategy) => {
            const sid = s.strategy_id ?? s.id ?? 0;
            const data = await fetch(`${API}/research/rolling-sharpe/${sid}`).then((r) => r.json());
            rolling[sid] = data.rolling_sharpe || [];
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
    setSelectedIds((prev) => (prev.includes(sid) ? prev.filter((x) => x !== sid) : [...prev, sid]));
  }

  return (
    <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
      <h1>Model Comparison</h1>
      <p style={{ marginBottom: "10px", color: "#666", fontSize: "11px" }}>
        Average walk-forward metrics and rolling Sharpe across strategies.
      </p>

      {strategies.length === 0 ? (
        <div className="alert alert-warning">
          No strategies found. Run the research loop first.
        </div>
      ) : (
        <>
          <div className="box">
            <div className="box-head">Comparison Table</div>
            <div className="box-body" style={{ padding: 0, overflowX: "auto" }}>
              <table className="data-table" style={{ marginBottom: 0, minWidth: "100%" }}>
                <thead>
                  <tr>
                    <th>Strategy</th>
                    <th>Status</th>
                    <th>Gen</th>
                    {metricKeys.map((m) => (
                      <th key={m.key}>{m.label}</th>
                    ))}
                    <th>Chart</th>
                  </tr>
                </thead>
                <tbody>
                  {strategies.map((strategy, index) => {
                    const sid = strategy.strategy_id ?? strategy.id ?? 0;
                    return (
                      <tr key={sid}>
                        <td><b>{strategy.name}</b></td>
                        <td style={{ textAlign: "center" }}>
                          <span className={`badge ${strategy.status === "promoted" ? "badge-success" : "badge-info"}`}>
                            {strategy.status}
                          </span>
                        </td>
                        <td style={{ textAlign: "center" }}>{strategy.generation}</td>
                        {metricKeys.map((metric) => (
                          <Cell
                            key={metric.key}
                            value={strategy.avg_metrics?.[metric.key]}
                            good={strategy.avg_metrics?.[metric.key] != null ? metric.goodFn(strategy.avg_metrics[metric.key]!) : undefined}
                          />
                        ))}
                        <td style={{ textAlign: "center" }}>
                          {rollingData[sid] && (
                            <button
                              onClick={() => toggleSelected(sid)}
                              title="Toggle rolling Sharpe"
                              style={{
                                width: "12px",
                                height: "12px",
                                borderRadius: "999px",
                                border: "2px solid #666",
                                background: selectedIds.includes(sid) ? COLORS[index % COLORS.length] : "transparent",
                              }}
                            />
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {chartPoints.length > 0 && (
            <div className="box" style={{ marginTop: "12px" }}>
              <div className="box-head">Rolling Sharpe (4-fold window)</div>
              <div className="box-body">
                <ResponsiveContainer width="100%" height={280}>
                  <LineChart data={chartPoints}>
                    <XAxis dataKey="fold" stroke="#64748b" tick={{ fontSize: 10 }} />
                    <YAxis stroke="#64748b" tick={{ fontSize: 10 }} />
                    <Tooltip
                      contentStyle={{ backgroundColor: "#f8f8f8", border: "1px solid #c0c0c0" }}
                      labelStyle={{ color: "#666" }}
                    />
                    <Legend />
                    {selectedIds.map((sid, index) => (
                      <Line
                        key={sid}
                        type="monotone"
                        dataKey={`strategy_${sid}`}
                        name={`Strategy #${sid}`}
                        stroke={COLORS[index % COLORS.length]}
                        dot={false}
                        strokeWidth={2}
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
