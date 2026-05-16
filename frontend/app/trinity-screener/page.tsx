"use client";

import { useState } from "react";
import { api } from "@/lib/api";

type TrinityScore = {
  ticker: string;
  total_score: number;
  value_score: number;
  quality_score: number;
  momentum_score: number;
  pre_explosion: boolean;
  signals: string[];
};

const DEMO_TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "V", "UNH"];

export default function TrinityScreenerPage() {
  const [tickers, setTickers] = useState<string>(DEMO_TICKERS.join(", "));
  const [preExplosionOnly, setPreExplosionOnly] = useState(false);
  const [scores, setScores] = useState<TrinityScore[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [screened, setScreened] = useState(false);

  async function runScreener() {
    const tickerList = tickers
      .split(/[,\s]+/)
      .map((t) => t.trim().toUpperCase())
      .filter(Boolean);

    if (tickerList.length === 0) {
      setError("Enter at least one ticker.");
      return;
    }

    setLoading(true);
    setError(null);
    setScores([]);

    try {
      // Build minimal price_data placeholder — Trinity uses patterns from price data
      // For UI demo, we send empty price_data and let backend use defaults
      const payload = {
        price_data: Object.fromEntries(tickerList.map((t) => [t, []])),
        fundamentals: null,
        pre_explosion_only: preExplosionOnly,
      };

      const data = await api.post<TrinityScore[]>("/scientific/trinity/screen", payload);
      const sorted = [...(Array.isArray(data) ? data : [])].sort(
        (a, b) => b.total_score - a.total_score
      );
      setScores(sorted);
      setScreened(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Screener failed.");
    } finally {
      setLoading(false);
    }
  }

  function scoreBadge(score: number) {
    if (score >= 0.7) return "badge-success";
    if (score >= 0.4) return "badge-warning";
    return "badge-danger";
  }

  const preExplosion = scores.filter((s) => s.pre_explosion);

  return (
    <div style={{ maxWidth: "1100px", margin: "0 auto" }}>
      <h1>Trinity Screener</h1>
      <p style={{ color: "#666", fontSize: "11px", marginBottom: "10px" }}>
        Multi-factor universe screen: Value + Quality + Momentum composite scores. Pre-explosion filter detects
        volatility compression before breakout moves.
      </p>

      {error && <div className="alert alert-danger">{error}</div>}

      <div className="box">
        <div className="box-head">Screen Universe</div>
        <div className="box-body">
          <label style={{ fontSize: "11px", display: "block", marginBottom: "6px" }}>
            Tickers (comma or space separated)
            <textarea
              value={tickers}
              onChange={(e) => setTickers(e.target.value)}
              rows={3}
              style={{ display: "block", width: "100%", marginTop: "4px", fontFamily: "monospace", fontSize: "11px" }}
            />
          </label>
          <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
            <label style={{ display: "inline-flex", alignItems: "center", gap: "4px", fontSize: "11px" }}>
              <input
                type="checkbox"
                checked={preExplosionOnly}
                onChange={(e) => setPreExplosionOnly(e.target.checked)}
              />
              Pre-explosion only
            </label>
            <button onClick={runScreener} disabled={loading}>
              {loading ? "Screening..." : "Run Screener"}
            </button>
          </div>
        </div>
      </div>

      {screened && (
        <>
          {/* Summary cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "8px", margin: "10px 0" }}>
            <div className="box" style={{ marginBottom: 0 }}>
              <div className="box-head">Screened</div>
              <div className="box-body"><div style={{ fontSize: "22px", fontWeight: "bold" }}>{scores.length}</div></div>
            </div>
            <div className="box" style={{ marginBottom: 0 }}>
              <div className="box-head">High Score (≥0.7)</div>
              <div className="box-body">
                <div style={{ fontSize: "22px", fontWeight: "bold", color: "#006600" }}>
                  {scores.filter((s) => s.total_score >= 0.7).length}
                </div>
              </div>
            </div>
            <div className="box" style={{ marginBottom: 0 }}>
              <div className="box-head">Pre-Explosion</div>
              <div className="box-body">
                <div style={{ fontSize: "22px", fontWeight: "bold", color: "#cc6600" }}>
                  {preExplosion.length}
                </div>
              </div>
            </div>
            <div className="box" style={{ marginBottom: 0 }}>
              <div className="box-head">Avg Score</div>
              <div className="box-body">
                <div style={{ fontSize: "22px", fontWeight: "bold" }}>
                  {scores.length > 0
                    ? (scores.reduce((s, x) => s + x.total_score, 0) / scores.length).toFixed(3)
                    : "—"}
                </div>
              </div>
            </div>
          </div>

          {/* Pre-explosion alerts */}
          {preExplosion.length > 0 && (
            <div className="alert alert-warning" style={{ marginBottom: "10px" }}>
              <b>Pre-explosion candidates:</b>{" "}
              {preExplosion.map((s) => s.ticker).join(", ")} —
              volatility compression detected, potential breakout setup.
            </div>
          )}

          {/* Results table */}
          <div className="box">
            <div className="box-head">Screener Results</div>
            <div className="box-body" style={{ padding: 0 }}>
              <table className="data-table" style={{ marginBottom: 0 }}>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Ticker</th>
                    <th>Total Score</th>
                    <th>Value</th>
                    <th>Quality</th>
                    <th>Momentum</th>
                    <th>Pre-Explosion</th>
                    <th>Signals</th>
                  </tr>
                </thead>
                <tbody>
                  {scores.length === 0 ? (
                    <tr>
                      <td colSpan={8} style={{ color: "#666" }}>No results. Provide price data for full scoring.</td>
                    </tr>
                  ) : (
                    scores.map((s, i) => (
                      <tr key={s.ticker} className={s.pre_explosion ? "highlight" : ""}>
                        <td style={{ color: "#666" }}>{i + 1}</td>
                        <td>
                          <b style={{ fontFamily: "monospace" }}>{s.ticker}</b>
                        </td>
                        <td>
                          <span className={`badge ${scoreBadge(s.total_score)}`}>
                            {s.total_score.toFixed(3)}
                          </span>
                        </td>
                        <td className={s.value_score >= 0.6 ? "text-green" : s.value_score < 0.3 ? "text-red" : ""}>
                          {s.value_score.toFixed(3)}
                        </td>
                        <td className={s.quality_score >= 0.6 ? "text-green" : s.quality_score < 0.3 ? "text-red" : ""}>
                          {s.quality_score.toFixed(3)}
                        </td>
                        <td className={s.momentum_score >= 0.6 ? "text-green" : s.momentum_score < 0.3 ? "text-red" : ""}>
                          {s.momentum_score.toFixed(3)}
                        </td>
                        <td>
                          {s.pre_explosion ? (
                            <span className="badge badge-warning">YES</span>
                          ) : (
                            <span style={{ color: "#666", fontSize: "10px" }}>—</span>
                          )}
                        </td>
                        <td style={{ fontSize: "10px", maxWidth: "200px" }}>
                          {(s.signals ?? []).slice(0, 3).join(", ")}
                          {(s.signals ?? []).length > 3 && "..."}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Info box */}
          <div className="box" style={{ marginTop: "10px" }}>
            <div className="box-head">About Trinity Screener</div>
            <div className="box-body" style={{ fontSize: "11px" }}>
              <div><b>Value Score:</b> PE ratio, P/B, EV/EBITDA relative to peers</div>
              <div><b>Quality Score:</b> ROE, debt/equity, earnings stability</div>
              <div><b>Momentum Score:</b> Price momentum, earnings revisions, insider activity</div>
              <div><b>Pre-Explosion:</b> Low realized volatility + volume compression + technical setup</div>
              <div style={{ marginTop: "6px", color: "#666" }}>
                Note: Full scoring requires price_data. Empty price_data returns pattern-based scores only.
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
