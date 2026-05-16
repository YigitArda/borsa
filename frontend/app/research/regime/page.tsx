"use client";

import { useEffect, useState } from "react";
import { api, research } from "@/lib/api";

type Strategy = { id: number; name: string; status: string };

type FoldEntry = {
  fold: number;
  test_start: string;
  test_end: string;
  avg_vix: number | null;
  sharpe?: number;
  win_rate?: number;
  n_trades?: number;
  max_drawdown?: number;
};

type RegimeBucket = {
  n_folds: number;
  avg_sharpe: number | null;
  folds: FoldEntry[];
};

type RegimeData = {
  strategy_id: number;
  regimes: Record<string, RegimeBucket>;
};

const REGIME_LABEL: Record<string, string> = {
  low_vix: "Bull (VIX < 15)",
  mid_vix: "Normal (VIX 15-25)",
  high_vix: "Bear (VIX > 25)",
  unknown: "Unknown",
};

const REGIME_COLOR: Record<string, string> = {
  low_vix: "#006600",
  mid_vix: "#666600",
  high_vix: "#990000",
  unknown: "#666666",
};

export default function RegimePage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [data, setData] = useState<RegimeData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    api.get<Strategy[]>("/strategies?limit=100").then((d) => {
      setStrategies(d);
      const promoted = d.find((s) => s.status === "promoted") ?? d[0];
      if (promoted) setSelectedId(String(promoted.id));
    }).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    loadRegime(Number(selectedId));
  }, [selectedId]);

  async function loadRegime(id: number) {
    setLoading(true);
    setData(null);
    setError(null);
    try {
      const d = await research.regimeAnalysis(id);
      setData(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load regime analysis.");
    } finally {
      setLoading(false);
    }
  }

  const regimes = data?.regimes ?? {};
  const regimeKeys = Object.keys(regimes).sort();

  function tone(v: number | null | undefined) {
    if (v == null) return "";
    return v >= 0.5 ? "text-green" : v >= 0 ? "" : "text-red";
  }

  return (
    <div style={{ maxWidth: "1100px", margin: "0 auto" }}>
      <h1>Regime Analysis</h1>
      <p style={{ color: "#666", fontSize: "11px", marginBottom: "10px" }}>
        Strategy performance by VIX regime — low/mid/high volatility buckets.
      </p>

      {error && <div className="alert alert-danger">{error}</div>}

      <div className="box">
        <div className="box-head">Controls</div>
        <div className="box-body" style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <label style={{ fontSize: "11px", display: "inline-flex", alignItems: "center", gap: "4px" }}>
            Strategy:
            <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
              <option value="">Select...</option>
              {strategies.map((s) => (
                <option key={s.id} value={s.id}>#{s.id} {s.name} ({s.status})</option>
              ))}
            </select>
          </label>
          <button onClick={() => selectedId && loadRegime(Number(selectedId))} disabled={loading}>
            {loading ? "Loading..." : "Refresh"}
          </button>
        </div>
      </div>

      {/* Regime summary cards */}
      {data && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "8px", margin: "10px 0" }}>
          {regimeKeys.map((regime) => {
            const bucket = regimes[regime];
            const sharpe = bucket.avg_sharpe;
            return (
              <div key={regime} className="box" style={{ marginBottom: 0 }}>
                <div
                  className="box-head"
                  style={{ background: `linear-gradient(to bottom, ${REGIME_COLOR[regime]}88, ${REGIME_COLOR[regime]})`, color: "#fff" }}
                >
                  {REGIME_LABEL[regime] ?? regime}
                </div>
                <div className="box-body">
                  <div style={{ fontSize: "20px", fontWeight: "bold" }} className={tone(sharpe)}>
                    {sharpe != null ? sharpe.toFixed(3) : "—"}
                  </div>
                  <div style={{ fontSize: "10px", color: "#666" }}>avg sharpe</div>
                  <div style={{ fontSize: "11px", marginTop: "4px" }}>{bucket.n_folds} folds</div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Regime fold details */}
      {data && regimeKeys.map((regime) => {
        const bucket = regimes[regime];
        const isExpanded = expanded === regime;
        return (
          <div key={regime} className="box" style={{ marginTop: "10px" }}>
            <div
              className="box-head"
              style={{ cursor: "pointer", display: "flex", justifyContent: "space-between" }}
              onClick={() => setExpanded(isExpanded ? null : regime)}
            >
              <span>{REGIME_LABEL[regime] ?? regime} — {bucket.n_folds} folds, avg Sharpe: {bucket.avg_sharpe?.toFixed(3) ?? "—"}</span>
              <span>{isExpanded ? "▲" : "▼"}</span>
            </div>
            {isExpanded && (
              <div className="box-body" style={{ padding: 0 }}>
                <table className="data-table" style={{ marginBottom: 0 }}>
                  <thead>
                    <tr>
                      <th>Fold</th>
                      <th>Test Period</th>
                      <th>Avg VIX</th>
                      <th>Sharpe</th>
                      <th>Win Rate</th>
                      <th>Trades</th>
                      <th>Max DD</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bucket.folds.map((fold) => (
                      <tr key={fold.fold}>
                        <td>{fold.fold}</td>
                        <td style={{ fontSize: "10px" }}>{fold.test_start} → {fold.test_end}</td>
                        <td>{fold.avg_vix?.toFixed(1) ?? "—"}</td>
                        <td className={tone(fold.sharpe)}>{fold.sharpe?.toFixed(3) ?? "—"}</td>
                        <td>{fold.win_rate != null ? `${(fold.win_rate * 100).toFixed(1)}%` : "—"}</td>
                        <td>{fold.n_trades ?? "—"}</td>
                        <td className={fold.max_drawdown != null && fold.max_drawdown < -0.1 ? "text-red" : ""}>
                          {fold.max_drawdown != null ? `${(fold.max_drawdown * 100).toFixed(1)}%` : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        );
      })}

      {!data && !loading && selectedId && (
        <div className="alert alert-info">No regime data found for this strategy. Run walk-forward validation first.</div>
      )}
      {loading && <div className="alert alert-info">Loading regime analysis...</div>}
    </div>
  );
}
