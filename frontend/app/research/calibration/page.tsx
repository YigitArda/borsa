"use client";

import { useEffect, useState } from "react";
import { api, research } from "@/lib/api";

type Strategy = { id: number; name: string; status: string };

type CalibrationData = {
  strategy_id: number;
  week_starting: string | null;
  brier_score: number | null;
  calibration_error: number | null;
  prob_buckets: Array<{ bucket: string; predicted: number; actual: number; count: number }> | null;
  reliability_data: Array<{ mean_predicted: number; fraction_pos: number; count: number }> | null;
};

export default function CalibrationPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [data, setData] = useState<CalibrationData | null>(null);
  const [loading, setLoading] = useState(false);
  const [computing, setComputing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    api.get<Strategy[]>("/strategies?limit=100").then((d) => {
      setStrategies(d);
      const promoted = d.find((s) => s.status === "promoted") ?? d[0];
      if (promoted) setSelectedId(String(promoted.id));
    }).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    loadCalibration(Number(selectedId));
  }, [selectedId]);

  async function loadCalibration(id: number) {
    setLoading(true);
    setData(null);
    setError(null);
    try {
      const d = await research.calibration(id);
      setData(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load calibration.");
    } finally {
      setLoading(false);
    }
  }

  async function computeCalibration() {
    if (!selectedId) return;
    setComputing(true);
    setError(null);
    try {
      await research.computeCalibration(Number(selectedId));
      setMessage("Calibration computed.");
      await loadCalibration(Number(selectedId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Calibration computation failed.");
    } finally {
      setComputing(false);
    }
  }

  const cal = data;
  const hasCal = cal && cal.brier_score != null;
  const buckets = cal?.prob_buckets ?? [];
  const reliability = cal?.reliability_data ?? [];

  function calBadge(err: number | null) {
    if (err == null) return "badge-default";
    const abs = Math.abs(err);
    if (abs < 0.05) return "badge-success";
    if (abs < 0.15) return "badge-warning";
    return "badge-danger";
  }

  return (
    <div style={{ maxWidth: "1000px", margin: "0 auto" }}>
      <h1>Probability Calibration</h1>
      <p style={{ color: "#666", fontSize: "11px", marginBottom: "10px" }}>
        How well do predicted probabilities match actual outcomes? Brier score, calibration error, reliability diagram.
      </p>

      {message && <div className="alert alert-success">{message}</div>}
      {error && <div className="alert alert-danger">{error}</div>}

      <div className="box">
        <div className="box-head">Controls</div>
        <div className="box-body" style={{ display: "flex", gap: "8px", flexWrap: "wrap", alignItems: "center" }}>
          <label style={{ fontSize: "11px", display: "inline-flex", alignItems: "center", gap: "4px" }}>
            Strategy:
            <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
              <option value="">Select...</option>
              {strategies.map((s) => (
                <option key={s.id} value={s.id}>#{s.id} {s.name} ({s.status})</option>
              ))}
            </select>
          </label>
          <button onClick={() => selectedId && loadCalibration(Number(selectedId))} disabled={loading}>
            {loading ? "Loading..." : "Refresh"}
          </button>
          <button onClick={computeCalibration} disabled={computing || !selectedId}>
            {computing ? "Computing..." : "Compute Calibration"}
          </button>
        </div>
      </div>

      {/* Summary stats */}
      {hasCal && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "8px", margin: "10px 0" }}>
          <div className="box" style={{ marginBottom: 0 }}>
            <div className="box-head">Brier Score</div>
            <div className="box-body">
              <div style={{ fontSize: "22px", fontWeight: "bold" }}>{cal.brier_score?.toFixed(4) ?? "—"}</div>
              <div style={{ fontSize: "10px", color: "#666" }}>lower is better (0 = perfect)</div>
            </div>
          </div>
          <div className="box" style={{ marginBottom: 0 }}>
            <div className="box-head">Calibration Error</div>
            <div className="box-body">
              <div style={{ fontSize: "22px", fontWeight: "bold" }}>
                <span className={`badge ${calBadge(cal.calibration_error)}`}>
                  {cal.calibration_error != null ? (cal.calibration_error * 100).toFixed(2) + "%" : "—"}
                </span>
              </div>
              <div style={{ fontSize: "10px", color: "#666" }}>predicted − actual (should be ~0)</div>
            </div>
          </div>
          <div className="box" style={{ marginBottom: 0 }}>
            <div className="box-head">Week Starting</div>
            <div className="box-body">
              <div style={{ fontSize: "16px", fontWeight: "bold" }}>{cal.week_starting ?? "—"}</div>
              <div style={{ fontSize: "10px", color: "#666" }}>last computed</div>
            </div>
          </div>
        </div>
      )}

      {/* Reliability data (diagonal chart substitute) */}
      {reliability.length > 0 && (
        <div className="box" style={{ marginTop: "10px" }}>
          <div className="box-head">Reliability Diagram Data</div>
          <div className="box-body" style={{ padding: 0 }}>
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th>Mean Predicted Prob</th>
                  <th>Actual Fraction Positive</th>
                  <th>Count</th>
                  <th>Calibration Gap</th>
                  <th>Visual</th>
                </tr>
              </thead>
              <tbody>
                {reliability.map((r, i) => {
                  const gap = r.mean_predicted - r.fraction_pos;
                  const barW = Math.round(r.fraction_pos * 100);
                  const predW = Math.round(r.mean_predicted * 100);
                  return (
                    <tr key={i}>
                      <td>{(r.mean_predicted * 100).toFixed(1)}%</td>
                      <td className={Math.abs(gap) < 0.05 ? "text-green" : gap > 0.1 ? "text-red" : ""}>
                        {(r.fraction_pos * 100).toFixed(1)}%
                      </td>
                      <td>{r.count}</td>
                      <td className={Math.abs(gap) < 0.05 ? "text-green" : "text-red"}>
                        {gap > 0 ? "+" : ""}{(gap * 100).toFixed(1)}%
                      </td>
                      <td style={{ minWidth: "120px" }}>
                        <div style={{ position: "relative", height: "12px", background: "#eee", border: "1px solid #ccc" }}>
                          <div style={{ position: "absolute", left: 0, top: 0, width: `${barW}%`, height: "100%", background: "#336699" }} />
                          <div style={{ position: "absolute", left: `${predW}%`, top: 0, width: "2px", height: "100%", background: "#cc0000" }} />
                        </div>
                        <div style={{ fontSize: "9px", color: "#666" }}>Blue=actual, Red=predicted</div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Probability buckets */}
      {buckets.length > 0 && (
        <div className="box" style={{ marginTop: "10px" }}>
          <div className="box-head">Probability Buckets</div>
          <div className="box-body" style={{ padding: 0 }}>
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th>Bucket</th>
                  <th>Predicted</th>
                  <th>Actual</th>
                  <th>Count</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {buckets.map((b, i) => {
                  const err = b.predicted - b.actual;
                  return (
                    <tr key={i}>
                      <td><b>{b.bucket}</b></td>
                      <td>{(b.predicted * 100).toFixed(1)}%</td>
                      <td>{(b.actual * 100).toFixed(1)}%</td>
                      <td>{b.count}</td>
                      <td className={Math.abs(err) < 0.05 ? "text-green" : "text-red"}>
                        {err > 0 ? "+" : ""}{(err * 100).toFixed(1)}%
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!hasCal && !loading && selectedId && (
        <div className="alert alert-info">
          No calibration data yet for this strategy. Click "Compute Calibration" to generate.
        </div>
      )}
      {loading && <div className="alert alert-info">Loading calibration...</div>}
    </div>
  );
}
