"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Strategy = { id: number; name: string; status: string };

type OverlapResult = {
  strategy_ids: number[];
  overlap_ratios: Record<string, number>;
};

export default function TradeOverlapPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [result, setResult] = useState<OverlapResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<Strategy[]>("/strategies?limit=100").then((d) => {
      setStrategies(d);
      // Pre-select all promoted strategies
      const promoted = d.filter((s) => s.status === "promoted").map((s) => s.id);
      if (promoted.length >= 2) setSelected(new Set(promoted));
    }).catch((e) => setError(e.message));
  }, []);

  function toggleSelect(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function computeOverlap() {
    if (selected.size < 2) {
      setError("Select at least 2 strategies.");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const ids = Array.from(selected).join(",");
      const data = await api.get<OverlapResult>(`/research/trade-overlap?strategy_ids=${ids}`);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Overlap computation failed.");
    } finally {
      setLoading(false);
    }
  }

  function overlapColor(ratio: number): string {
    if (ratio < 0.2) return "#006600";
    if (ratio < 0.5) return "#cc9900";
    return "#cc0000";
  }

  function stratName(id: number) {
    const s = strategies.find((x) => x.id === id);
    return s ? `#${s.id} ${s.name.slice(0, 20)}` : `#${id}`;
  }

  const overlapEntries = result ? Object.entries(result.overlap_ratios) : [];

  return (
    <div style={{ maxWidth: "900px", margin: "0 auto" }}>
      <h1>Trade Overlap Analysis</h1>
      <p style={{ color: "#666", fontSize: "11px", marginBottom: "10px" }}>
        Measures date-period overlap between strategies. High overlap = correlated risk, low overlap = diversification.
      </p>

      {error && <div className="alert alert-danger">{error}</div>}

      <div className="box">
        <div className="box-head">Select Strategies (min 2)</div>
        <div className="box-body">
          <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginBottom: "10px" }}>
            {strategies.map((s) => (
              <label
                key={s.id}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "4px",
                  padding: "2px 8px",
                  border: `1px solid ${selected.has(s.id) ? "#336699" : "#ccc"}`,
                  background: selected.has(s.id) ? "#e8f0f8" : "#fff",
                  cursor: "pointer",
                  fontSize: "11px",
                }}
              >
                <input
                  type="checkbox"
                  checked={selected.has(s.id)}
                  onChange={() => toggleSelect(s.id)}
                />
                #{s.id} {s.name.slice(0, 25)}
                <span className={`badge ${s.status === "promoted" ? "badge-success" : "badge-default"}`} style={{ fontSize: "9px" }}>
                  {s.status}
                </span>
              </label>
            ))}
          </div>
          <div style={{ display: "flex", gap: "8px" }}>
            <button onClick={computeOverlap} disabled={loading || selected.size < 2}>
              {loading ? "Computing..." : "Compute Overlap"}
            </button>
            <span style={{ fontSize: "11px", color: "#666", alignSelf: "center" }}>
              {selected.size} selected
            </span>
          </div>
        </div>
      </div>

      {result && (
        <>
          {/* Overlap matrix */}
          <div className="box" style={{ marginTop: "10px" }}>
            <div className="box-head">Overlap Ratios</div>
            <div className="box-body" style={{ padding: 0 }}>
              <table className="data-table" style={{ marginBottom: 0 }}>
                <thead>
                  <tr>
                    <th>Strategy A</th>
                    <th>Strategy B</th>
                    <th>Overlap Ratio</th>
                    <th>Risk Level</th>
                    <th>Visual</th>
                  </tr>
                </thead>
                <tbody>
                  {overlapEntries.length === 0 ? (
                    <tr><td colSpan={5} style={{ color: "#666" }}>No overlap data computed.</td></tr>
                  ) : (
                    overlapEntries.map(([pair, ratio]) => {
                      const [a, b] = pair.split("_vs_");
                      const pct = Math.round(ratio * 100);
                      const color = overlapColor(ratio);
                      return (
                        <tr key={pair}>
                          <td style={{ fontSize: "11px" }}>{stratName(Number(a))}</td>
                          <td style={{ fontSize: "11px" }}>{stratName(Number(b))}</td>
                          <td style={{ fontWeight: "bold", color }}>{(ratio * 100).toFixed(1)}%</td>
                          <td>
                            <span className={`badge ${ratio < 0.2 ? "badge-success" : ratio < 0.5 ? "badge-warning" : "badge-danger"}`}>
                              {ratio < 0.2 ? "LOW" : ratio < 0.5 ? "MEDIUM" : "HIGH"}
                            </span>
                          </td>
                          <td style={{ minWidth: "120px" }}>
                            <div style={{ background: "#eee", border: "1px solid #ccc", height: "12px", position: "relative" }}>
                              <div style={{ width: `${pct}%`, height: "100%", background: color }} />
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Interpretation */}
          <div className="box" style={{ marginTop: "10px" }}>
            <div className="box-head">Interpretation</div>
            <div className="box-body" style={{ fontSize: "11px" }}>
              <div><span className="badge badge-success">LOW (&lt;20%)</span> Good diversification — strategies trade different periods.</div>
              <div style={{ marginTop: "4px" }}><span className="badge badge-warning">MEDIUM (20-50%)</span> Partial overlap — some correlated risk exposure.</div>
              <div style={{ marginTop: "4px" }}><span className="badge badge-danger">HIGH (&gt;50%)</span> Heavy overlap — strategies share most trade periods; limited diversification benefit.</div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
