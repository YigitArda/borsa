"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Hypothesis = {
  id: string;
  name: string;
  mechanism: string;
  expected_edge: number;
  asset_universe: string;
  timeframe: string;
  status: string;
  features: string[];
  entry_rules: string;
  exit_rules: string;
  max_drawdown_tolerance: number;
  min_sharpe: number;
  min_win_rate: number;
  notes: string;
  created_at?: string;
  updated_at?: string;
};

const STATUS_OPTIONS = ["UNTESTED", "TESTING", "VALIDATED", "LIVE", "DECAYED", "REJECTED"];

const STATUS_BADGE: Record<string, string> = {
  UNTESTED: "badge-default",
  TESTING: "badge-warning",
  VALIDATED: "badge-info",
  LIVE: "badge-success",
  DECAYED: "badge-warning",
  REJECTED: "badge-danger",
};

const EMPTY_FORM = {
  id: "",
  name: "",
  mechanism: "",
  expected_edge: 0.02,
  asset_universe: "SP500",
  timeframe: "1W",
  features: [] as string[],
  entry_rules: "",
  exit_rules: "",
  max_drawdown_tolerance: 0.2,
  min_sharpe: 1.0,
  min_win_rate: 0.35,
  notes: "",
};

export default function HypothesesPage() {
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState<string>("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  useEffect(() => {
    loadHypotheses();
  }, [filterStatus]);

  async function loadHypotheses() {
    setLoading(true);
    try {
      const url = filterStatus ? `/scientific/hypotheses?status=${filterStatus}` : "/scientific/hypotheses";
      const data = await api.get<Hypothesis[]>(url);
      setHypotheses(Array.isArray(data) ? data : []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hypothesis list could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  async function submitHypothesis() {
    if (!form.id.trim() || !form.name.trim()) {
      setError("ID and name are required.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.post("/scientific/hypotheses", {
        ...form,
        features: form.features,
      });
      setMessage(`Hypothesis "${form.name}" registered.`);
      setShowForm(false);
      setForm(EMPTY_FORM);
      await loadHypotheses();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not register hypothesis.");
    } finally {
      setSubmitting(false);
    }
  }

  async function updateStatus(id: string, newStatus: string) {
    setUpdatingId(id);
    try {
      await api.post(`/scientific/hypotheses/${id}/status`, { status: newStatus, results: null });
      setMessage(`Status updated to ${newStatus}.`);
      await loadHypotheses();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Status update failed.");
    } finally {
      setUpdatingId(null);
    }
  }

  const counts = STATUS_OPTIONS.reduce(
    (acc, s) => ({ ...acc, [s]: hypotheses.filter((h) => h.status === s).length }),
    {} as Record<string, number>
  );

  return (
    <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
      <h1>Hypothesis Registry</h1>
      <p style={{ color: "#666", fontSize: "11px", marginBottom: "10px" }}>
        Falsifiable trading hypotheses — lifecycle: UNTESTED → TESTING → VALIDATED → LIVE → DECAYED/REJECTED
      </p>

      {message && <div className="alert alert-success">{message}</div>}
      {error && <div className="alert alert-danger">{error}</div>}

      {/* Status summary */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: "6px", marginBottom: "12px" }}>
        {STATUS_OPTIONS.map((s) => (
          <div key={s} className="box" style={{ marginBottom: 0 }}>
            <div className="box-head" style={{ fontSize: "9px" }}>{s}</div>
            <div className="box-body" style={{ fontSize: "18px", fontWeight: "bold" }}>{counts[s] ?? 0}</div>
          </div>
        ))}
      </div>

      {/* Controls */}
      <div className="box">
        <div className="box-head">Controls</div>
        <div className="box-body" style={{ display: "flex", gap: "8px", flexWrap: "wrap", alignItems: "center" }}>
          <label style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
            <span style={{ fontSize: "11px" }}>Filter:</span>
            <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
              <option value="">All</option>
              {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <button onClick={loadHypotheses} disabled={loading}>{loading ? "Loading..." : "Refresh"}</button>
          <button onClick={() => setShowForm(!showForm)}>
            {showForm ? "Cancel" : "+ New Hypothesis"}
          </button>
        </div>
      </div>

      {/* New hypothesis form */}
      {showForm && (
        <div className="box" style={{ marginTop: "10px" }}>
          <div className="box-head">Register New Hypothesis</div>
          <div className="box-body">
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
              <label style={{ fontSize: "11px" }}>
                ID (unique slug)
                <input
                  value={form.id}
                  onChange={(e) => setForm((f) => ({ ...f, id: e.target.value }))}
                  style={{ display: "block", width: "100%", marginTop: "2px" }}
                  placeholder="e.g. pead-momentum-v1"
                />
              </label>
              <label style={{ fontSize: "11px" }}>
                Name
                <input
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  style={{ display: "block", width: "100%", marginTop: "2px" }}
                  placeholder="e.g. PEAD Momentum Strategy"
                />
              </label>
              <label style={{ fontSize: "11px" }}>
                Mechanism
                <input
                  value={form.mechanism}
                  onChange={(e) => setForm((f) => ({ ...f, mechanism: e.target.value }))}
                  style={{ display: "block", width: "100%", marginTop: "2px" }}
                  placeholder="e.g. Earnings surprise drives 2-4 week drift"
                />
              </label>
              <label style={{ fontSize: "11px" }}>
                Asset Universe
                <input
                  value={form.asset_universe}
                  onChange={(e) => setForm((f) => ({ ...f, asset_universe: e.target.value }))}
                  style={{ display: "block", width: "100%", marginTop: "2px" }}
                />
              </label>
              <label style={{ fontSize: "11px" }}>
                Timeframe
                <input
                  value={form.timeframe}
                  onChange={(e) => setForm((f) => ({ ...f, timeframe: e.target.value }))}
                  style={{ display: "block", width: "100%", marginTop: "2px" }}
                  placeholder="1W / 1M / 1D"
                />
              </label>
              <label style={{ fontSize: "11px" }}>
                Expected Edge (e.g. 0.02 = 2%)
                <input
                  type="number"
                  step="0.005"
                  value={form.expected_edge}
                  onChange={(e) => setForm((f) => ({ ...f, expected_edge: parseFloat(e.target.value) || 0 }))}
                  style={{ display: "block", width: "100%", marginTop: "2px" }}
                />
              </label>
              <label style={{ fontSize: "11px" }}>
                Min Sharpe
                <input
                  type="number"
                  step="0.1"
                  value={form.min_sharpe}
                  onChange={(e) => setForm((f) => ({ ...f, min_sharpe: parseFloat(e.target.value) || 0 }))}
                  style={{ display: "block", width: "100%", marginTop: "2px" }}
                />
              </label>
              <label style={{ fontSize: "11px" }}>
                Min Win Rate
                <input
                  type="number"
                  step="0.05"
                  value={form.min_win_rate}
                  onChange={(e) => setForm((f) => ({ ...f, min_win_rate: parseFloat(e.target.value) || 0 }))}
                  style={{ display: "block", width: "100%", marginTop: "2px" }}
                />
              </label>
              <label style={{ fontSize: "11px", gridColumn: "1 / -1" }}>
                Entry Rules
                <textarea
                  value={form.entry_rules}
                  onChange={(e) => setForm((f) => ({ ...f, entry_rules: e.target.value }))}
                  rows={2}
                  style={{ display: "block", width: "100%", marginTop: "2px", fontFamily: "monospace", fontSize: "11px" }}
                />
              </label>
              <label style={{ fontSize: "11px", gridColumn: "1 / -1" }}>
                Exit Rules
                <textarea
                  value={form.exit_rules}
                  onChange={(e) => setForm((f) => ({ ...f, exit_rules: e.target.value }))}
                  rows={2}
                  style={{ display: "block", width: "100%", marginTop: "2px", fontFamily: "monospace", fontSize: "11px" }}
                />
              </label>
              <label style={{ fontSize: "11px", gridColumn: "1 / -1" }}>
                Notes
                <textarea
                  value={form.notes}
                  onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
                  rows={2}
                  style={{ display: "block", width: "100%", marginTop: "2px" }}
                />
              </label>
            </div>
            <div style={{ marginTop: "8px" }}>
              <button onClick={submitHypothesis} disabled={submitting}>
                {submitting ? "Registering..." : "Register Hypothesis"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Hypothesis list */}
      <div className="box" style={{ marginTop: "10px" }}>
        <div className="box-head">Hypotheses ({hypotheses.length})</div>
        <div className="box-body" style={{ padding: 0 }}>
          <table className="data-table" style={{ marginBottom: 0 }}>
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Mechanism</th>
                <th>Universe</th>
                <th>Edge</th>
                <th>Sharpe</th>
                <th>Status</th>
                <th>Transition</th>
              </tr>
            </thead>
            <tbody>
              {hypotheses.length === 0 ? (
                <tr>
                  <td colSpan={8} style={{ color: "#666" }}>
                    {loading ? "Loading..." : "No hypotheses registered yet."}
                  </td>
                </tr>
              ) : (
                hypotheses.map((h) => (
                  <tr key={h.id}>
                    <td style={{ fontFamily: "monospace", fontSize: "10px" }}>{h.id}</td>
                    <td>
                      <b>{h.name}</b>
                      {h.notes && <div style={{ fontSize: "10px", color: "#666" }}>{h.notes.slice(0, 60)}</div>}
                    </td>
                    <td style={{ fontSize: "10px" }}>{h.mechanism}</td>
                    <td style={{ fontSize: "10px" }}>{h.asset_universe} / {h.timeframe}</td>
                    <td className="text-green">{(h.expected_edge * 100).toFixed(1)}%</td>
                    <td>{h.min_sharpe.toFixed(1)}</td>
                    <td>
                      <span className={`badge ${STATUS_BADGE[h.status] ?? "badge-default"}`}>{h.status}</span>
                    </td>
                    <td>
                      <select
                        value=""
                        disabled={updatingId === h.id}
                        onChange={(e) => { if (e.target.value) updateStatus(h.id, e.target.value); }}
                        style={{ fontSize: "10px" }}
                      >
                        <option value="">Set status...</option>
                        {STATUS_OPTIONS.filter((s) => s !== h.status).map((s) => (
                          <option key={s} value={s}>{s}</option>
                        ))}
                      </select>
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
