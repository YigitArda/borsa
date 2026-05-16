"use client";

import { useEffect, useState } from "react";
import { api, ablation } from "@/lib/api";

type StrategySummary = {
  id: number;
  name: string;
  status: string;
  generation: number;
};

type AblationRow = {
  id?: number;
  strategy_id?: number;
  feature_group: string;
  features_removed?: string[] | null;
  sharpe: number | null;
  profit_factor: number | null;
  max_drawdown: number | null;
  win_rate: number | null;
  avg_return: number | null;
  sharpe_impact: number | null;
  profit_factor_impact: number | null;
  drawdown_impact: number | null;
  stability_score: number | null;
};

type Recommendation = {
  feature_group: string;
  action: string;
  reason: string;
  sharpe_impact: number;
  drawdown_impact: number;
  stability_score: number;
};

export default function AblationPage() {
  const [strategies, setStrategies] = useState<StrategySummary[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState<string>("");
  const [rows, setRows] = useState<AblationRow[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadStrategies() {
      try {
        const data = await api.get<StrategySummary[]>("/strategies?limit=100");
        if (!active) return;
        setStrategies(data);
        const promoted = data.find((s) => s.status === "promoted") ?? data[0];
        if (promoted) {
          setSelectedStrategy(String(promoted.id));
        }
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Strategy list could not be loaded.");
      }
    }

    loadStrategies();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedStrategy) return;
    loadCurrentResults(Number(selectedStrategy));
  }, [selectedStrategy]);

  async function loadCurrentResults(strategyId: number) {
    setLoading(true);
    try {
      const [ablationRows, recs] = await Promise.all([
        ablation.results(strategyId),
        ablation.recommendations(strategyId).catch(() => ({ recommendations: [] as Recommendation[] })),
      ]);
      setRows(ablationRows);
      setRecommendations(recs.recommendations ?? []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ablation results could not be loaded.");
      setRows([]);
      setRecommendations([]);
    } finally {
      setLoading(false);
    }
  }

  async function runAblation() {
    if (!selectedStrategy) {
      setError("Select a strategy first.");
      return;
    }

    setRunning(true);
    setMessage(null);
    setError(null);
    try {
      const response = await ablation.run(Number(selectedStrategy));
      const resultRows = Array.isArray(response?.results) ? response.results : [];
      setMessage(`Ablation finished with ${resultRows.length} rows.`);
      await loadCurrentResults(Number(selectedStrategy));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ablation could not be started.");
    } finally {
      setRunning(false);
    }
  }

  const selectedStrategyLabel = strategies.find((s) => String(s.id) === selectedStrategy)?.name ?? "Unknown";
  const baseline = rows.find((row) => row.feature_group === "all");
  const nonBaselineRows = rows.filter((row) => row.feature_group !== "all");

  return (
    <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
      <h1>Ablation Results</h1>
      <p style={{ marginBottom: "10px", color: "#666", fontSize: "11px" }}>
        Feature group ablation, impact scores and keep/remove recommendations.
      </p>

      <div className="alert alert-info">
        <b>Akis:</b> Baseline run is stored as <code>all</code>. Other rows show what happens when a feature group is isolated.
      </div>

      {message && <div className="alert alert-success">{message}</div>}
      {error && <div className="alert alert-danger">{error}</div>}

      <div className="box">
        <div className="box-head">Controls</div>
        <div className="box-body" style={{ display: "flex", flexWrap: "wrap", gap: "8px", alignItems: "center" }}>
          <label style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
            <span className="section-label" style={{ marginBottom: 0 }}>Strategy</span>
            <select value={selectedStrategy} onChange={(e) => setSelectedStrategy(e.target.value)}>
              <option value="">Seç...</option>
              {strategies.map((strategy) => (
                <option key={strategy.id} value={strategy.id}>
                  #{strategy.id} {strategy.name} ({strategy.status})
                </option>
              ))}
            </select>
          </label>

          <button onClick={() => selectedStrategy && loadCurrentResults(Number(selectedStrategy))} disabled={loading}>
            {loading ? "Loading..." : "Refresh"}
          </button>
          <button onClick={runAblation} disabled={running}>
            {running ? "Running..." : "Run Ablation"}
          </button>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: "8px", marginBottom: "12px" }}>
        <StatCard label="Rows" value={rows.length} />
        <StatCard label="Baseline" value={baseline ? "Yes" : "No"} />
        <StatCard label="Variants" value={nonBaselineRows.length} />
        <StatCard label="Recommendations" value={recommendations.length} />
      </div>

      <div className="box">
        <div className="box-head">Selected Strategy</div>
        <div className="box-body">
          <div><b>ID:</b> {selectedStrategy || "Seçilmedi"}</div>
          <div><b>Name:</b> {selectedStrategyLabel}</div>
        </div>
      </div>

      <div className="box" style={{ marginTop: "12px" }}>
        <div className="box-head">Ablation Results</div>
        <div className="box-body" style={{ padding: 0 }}>
          <table className="data-table" style={{ marginBottom: 0 }}>
            <thead>
              <tr>
                <th>Feature Group</th>
                <th>Sharpe</th>
                <th>Sharpe Impact</th>
                <th>Profit Factor</th>
                <th>Drawdown Impact</th>
                <th>Stability</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ color: "#666" }}>
                    {loading ? "Loading results..." : "No ablation results yet."}
                  </td>
                </tr>
              ) : (
                rows.map((row) => (
                  <tr key={row.id ?? row.feature_group} className={row.feature_group === "all" ? "highlight" : ""}>
                    <td>
                      <b>{row.feature_group}</b>
                      {row.features_removed && row.features_removed.length > 0 && (
                        <div style={{ fontSize: "10px", color: "#666", marginTop: "3px" }}>
                          Removed: {row.features_removed.slice(0, 4).join(", ")}
                          {row.features_removed.length > 4 ? "..." : ""}
                        </div>
                      )}
                    </td>
                    <td className={tone(row.sharpe)}>{fmt(row.sharpe)}</td>
                    <td className={tone(row.sharpe_impact)}>{fmtPct(row.sharpe_impact)}</td>
                    <td className={tone(row.profit_factor)}>{fmt(row.profit_factor)}</td>
                    <td className={tone(row.drawdown_impact)}>{fmtPct(row.drawdown_impact)}</td>
                    <td className={tone(row.stability_score)}>{fmt(row.stability_score)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="box" style={{ marginTop: "12px" }}>
        <div className="box-head">Recommendations</div>
        <div className="box-body" style={{ padding: 0 }}>
          <table className="data-table" style={{ marginBottom: 0 }}>
            <thead>
              <tr>
                <th>Group</th>
                <th>Action</th>
                <th>Reason</th>
                <th>Impact</th>
              </tr>
            </thead>
            <tbody>
              {recommendations.length === 0 ? (
                <tr>
                  <td colSpan={4} style={{ color: "#666" }}>
                    No recommendations yet. Run ablation first.
                  </td>
                </tr>
              ) : (
                recommendations.map((rec) => (
                  <tr key={rec.feature_group}>
                    <td><b>{rec.feature_group}</b></td>
                    <td>
                      <span className={`badge ${rec.action === "keep" ? "badge-success" : "badge-warning"}`}>
                        {rec.action.toUpperCase()}
                      </span>
                    </td>
                    <td>{rec.reason}</td>
                    <td style={{ fontSize: "10px", fontFamily: "monospace" }}>
                      Sharpe {fmtPct(rec.sharpe_impact)} | DD {fmtPct(rec.drawdown_impact)} | Score {fmt(rec.stability_score)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function fmt(value: number | null): string {
  return value == null ? "—" : value.toFixed(3);
}

function fmtPct(value: number | null): string {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function tone(value: number | null): string {
  if (value == null) return "text-muted";
  return value >= 0 ? "text-green" : "text-red";
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="box" style={{ marginBottom: 0 }}>
      <div className="box-head">{label}</div>
      <div className="box-body">
        <div style={{ fontSize: "20px", fontWeight: "bold" }}>{value}</div>
      </div>
    </div>
  );
}
