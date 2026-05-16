"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import EquityChart from "@/components/charts/EquityChart";
import { api, portfolioSimulation } from "@/lib/api";

type StrategySummary = {
  id: number;
  name: string;
  status: string;
  generation: number;
};

type SimulationResponse = {
  status: string;
  simulation_id?: number;
  equity_curve?: Array<{ date: string; value: number }>;
  drawdown_curve?: Array<{ date: string; value: number }>;
  monthly_returns?: number[];
  yearly_returns?: Record<string, number>;
  worst_month?: number | null;
  best_month?: number | null;
  consecutive_losses?: number | null;
  portfolio_volatility?: number | null;
  trades_executed?: number | null;
  reason?: string;
};

type FormState = {
  backtestRunId: string;
  initialCapital: number;
  maxPositions: number;
  maxPositionWeight: number;
  sectorLimit: number;
  cashRatio: number;
  rebalanceFrequency: string;
  transactionCostBps: number;
  slippageBps: number;
  threshold: number;
  topN: number;
  holdingWeeks: number;
  applyLiquidityFilter: boolean;
};

const DEFAULT_FORM: FormState = {
  backtestRunId: "",
  initialCapital: 100000,
  maxPositions: 5,
  maxPositionWeight: 0.25,
  sectorLimit: 0.4,
  cashRatio: 0.1,
  rebalanceFrequency: "weekly",
  transactionCostBps: 10,
  slippageBps: 5,
  threshold: 0.5,
  topN: 5,
  holdingWeeks: 1,
  applyLiquidityFilter: true,
};

export default function PortfolioSimulationPage() {
  const [strategies, setStrategies] = useState<StrategySummary[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState<string>("");
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<SimulationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

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

  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function runSimulation() {
    if (!selectedStrategy) {
      setError("Select a strategy first.");
      return;
    }

    setRunning(true);
    setError(null);
    setStatus(null);
    setResult(null);

    try {
      const payload = {
        strategy_id: Number(selectedStrategy),
        backtest_run_id: form.backtestRunId.trim() ? Number(form.backtestRunId) : undefined,
        initial_capital: form.initialCapital,
        max_positions: form.maxPositions,
        max_position_weight: form.maxPositionWeight,
        sector_limit: form.sectorLimit,
        cash_ratio: form.cashRatio,
        rebalance_frequency: form.rebalanceFrequency,
        transaction_cost_bps: form.transactionCostBps,
        slippage_bps: form.slippageBps,
        model_type: "lightgbm",
        threshold: form.threshold,
        top_n: form.topN,
        holding_weeks: form.holdingWeeks,
        apply_liquidity_filter: form.applyLiquidityFilter,
      };
      const data = await portfolioSimulation.run(payload);
      setResult(data);
      setStatus(data.status === "ok" ? "Simulation completed." : data.reason || "Simulation failed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Simulation request failed.");
    } finally {
      setRunning(false);
    }
  }

  const equityData = (result?.equity_curve ?? []).map((point) => ({
    date: point.date,
    equity: form.initialCapital > 0 ? point.value / form.initialCapital : point.value,
  }));

  const latestYearReturns = Object.entries(result?.yearly_returns ?? {}).sort((a, b) => Number(a[0]) - Number(b[0]));
  const recentCurve = (result?.equity_curve ?? []).slice(-10);
  const selectedStrategyLabel = strategies.find((s) => String(s.id) === selectedStrategy)?.name ?? "Unknown";

  return (
    <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
      <h1>Portfoy Simulasyonu</h1>
      <p style={{ marginBottom: "10px", color: "#666", fontSize: "11px" }}>
        Strateji bazli sermaye simulasyonu, yeniden dengeleme ve risk kisitlari.
      </p>

      <div className="alert alert-info">
        <b>Not:</b> Bu sayfa backend'deki <code>/backtest/portfolio</code> servisini calistirir ve sonucu aninda gosterir.
      </div>

      {error && <div className="alert alert-danger">{error}</div>}
      {status && <div className="alert alert-success">{status}</div>}

      <div className="box">
        <div className="box-head">Simulasyon Ayarlari</div>
        <div className="box-body">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "8px" }}>
            <label>
              <div className="section-label">Strateji</div>
              <select value={selectedStrategy} onChange={(e) => setSelectedStrategy(e.target.value)}>
                <option value="">Seç...</option>
                {strategies.map((strategy) => (
                  <option key={strategy.id} value={strategy.id}>
                    #{strategy.id} {strategy.name} ({strategy.status})
                  </option>
                ))}
              </select>
            </label>

            <label>
              <div className="section-label">Backtest ID</div>
              <input
                type="number"
                value={form.backtestRunId}
                onChange={(e) => updateField("backtestRunId", e.target.value)}
                placeholder="Opsiyonel"
              />
            </label>

            <label>
              <div className="section-label">Rebalance</div>
              <select
                value={form.rebalanceFrequency}
                onChange={(e) => updateField("rebalanceFrequency", e.target.value)}
              >
                <option value="weekly">weekly</option>
                <option value="monthly">monthly</option>
                <option value="quarterly">quarterly</option>
                <option value="none">none</option>
              </select>
            </label>

            <label>
              <div className="section-label">Initial Capital</div>
              <input
                type="number"
                value={form.initialCapital}
                onChange={(e) => updateField("initialCapital", Number(e.target.value))}
              />
            </label>

            <label>
              <div className="section-label">Max Positions</div>
              <input
                type="number"
                value={form.maxPositions}
                onChange={(e) => updateField("maxPositions", Number(e.target.value))}
              />
            </label>

            <label>
              <div className="section-label">Max Position Weight</div>
              <input
                type="number"
                step="0.05"
                value={form.maxPositionWeight}
                onChange={(e) => updateField("maxPositionWeight", Number(e.target.value))}
              />
            </label>

            <label>
              <div className="section-label">Sector Limit</div>
              <input
                type="number"
                step="0.05"
                value={form.sectorLimit}
                onChange={(e) => updateField("sectorLimit", Number(e.target.value))}
              />
            </label>

            <label>
              <div className="section-label">Cash Ratio</div>
              <input
                type="number"
                step="0.05"
                value={form.cashRatio}
                onChange={(e) => updateField("cashRatio", Number(e.target.value))}
              />
            </label>

            <label>
              <div className="section-label">Threshold</div>
              <input
                type="number"
                step="0.05"
                value={form.threshold}
                onChange={(e) => updateField("threshold", Number(e.target.value))}
              />
            </label>

            <label>
              <div className="section-label">Top N</div>
              <input
                type="number"
                value={form.topN}
                onChange={(e) => updateField("topN", Number(e.target.value))}
              />
            </label>

            <label>
              <div className="section-label">Holding Weeks</div>
              <input
                type="number"
                value={form.holdingWeeks}
                onChange={(e) => updateField("holdingWeeks", Number(e.target.value))}
              />
            </label>

            <label>
              <div className="section-label">Transaction Cost (bps)</div>
              <input
                type="number"
                value={form.transactionCostBps}
                onChange={(e) => updateField("transactionCostBps", Number(e.target.value))}
              />
            </label>

            <label>
              <div className="section-label">Slippage (bps)</div>
              <input
                type="number"
                value={form.slippageBps}
                onChange={(e) => updateField("slippageBps", Number(e.target.value))}
              />
            </label>
          </div>

          <label style={{ display: "inline-flex", alignItems: "center", gap: "8px", marginTop: "8px" }}>
            <input
              type="checkbox"
              checked={form.applyLiquidityFilter}
              onChange={(e) => updateField("applyLiquidityFilter", e.target.checked)}
            />
            Liquidity filter uygula
          </label>

          <div style={{ marginTop: "10px" }}>
            <button onClick={runSimulation} disabled={running}>
              {running ? "Calisiyor..." : "Simulasyonu Calistir"}
            </button>
          </div>
        </div>
      </div>

      <div className="box">
        <div className="box-head">Secili Strateji</div>
        <div className="box-body">
          <div><b>ID:</b> {selectedStrategy || "Seçilmedi"}</div>
          <div><b>Ad:</b> {selectedStrategyLabel}</div>
        </div>
      </div>

      {result?.status === "ok" && (
        <>
          <div className="box">
            <div className="box-head">Sonuc Ozeti</div>
            <div className="box-body">
              <table className="data-table">
                <tbody>
                  <tr>
                    <td>Simulation ID</td>
                    <td><b>{result.simulation_id ?? "—"}</b></td>
                    <td>Trades Executed</td>
                    <td><b>{result.trades_executed ?? "—"}</b></td>
                  </tr>
                  <tr>
                    <td>Best Month</td>
                    <td className={result.best_month != null && result.best_month >= 0 ? "text-green" : "text-red"}>
                      {result.best_month != null ? `${(result.best_month * 100).toFixed(2)}%` : "—"}
                    </td>
                    <td>Worst Month</td>
                    <td className={result.worst_month != null && result.worst_month >= 0 ? "text-green" : "text-red"}>
                      {result.worst_month != null ? `${(result.worst_month * 100).toFixed(2)}%` : "—"}
                    </td>
                  </tr>
                  <tr>
                    <td>Consecutive Losses</td>
                    <td><b>{result.consecutive_losses ?? "—"}</b></td>
                    <td>Volatility</td>
                    <td>{result.portfolio_volatility != null ? result.portfolio_volatility.toFixed(4) : "—"}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {equityData.length > 0 && (
            <div className="box">
              <div className="box-head">Equity Curve</div>
              <div className="box-body">
                <EquityChart data={equityData} />
              </div>
            </div>
          )}

          {latestYearReturns.length > 0 && (
            <div className="box">
              <div className="box-head">Yearly Returns</div>
              <div className="box-body" style={{ padding: 0 }}>
                <table className="data-table" style={{ marginBottom: 0 }}>
                  <thead>
                    <tr>
                      <th>Yil</th>
                      <th>Getiri</th>
                    </tr>
                  </thead>
                  <tbody>
                    {latestYearReturns.map(([year, value]) => (
                      <tr key={year}>
                        <td>{year}</td>
                        <td className={value >= 0 ? "text-green" : "text-red"}>
                          {value >= 0 ? "+" : ""}{(value * 100).toFixed(2)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {recentCurve.length > 0 && (
            <div className="box">
              <div className="box-head">Son Curve Noktalari</div>
              <div className="box-body" style={{ padding: 0 }}>
                <table className="data-table" style={{ marginBottom: 0 }}>
                  <thead>
                    <tr>
                      <th>Tarih</th>
                      <th>Portfoy Degeri</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentCurve.map((point) => (
                      <tr key={point.date}>
                        <td style={{ fontFamily: "monospace" }}>{point.date}</td>
                        <td>{point.value.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      <div style={{ marginTop: "8px", fontSize: "10px", color: "#666", textAlign: "center" }}>
        <Link href="/strategy-lab">Strategy Lab</Link> | <Link href="/backtest">Backtest Merkezi</Link>
      </div>
    </div>
  );
}
