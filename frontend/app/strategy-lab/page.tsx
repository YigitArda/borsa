"use client";

import { useState } from "react";
import EquityChart from "@/components/charts/EquityChart";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const MODEL_TYPES = ["lightgbm", "logistic_regression", "random_forest", "gradient_boosting", "catboost", "xgboost", "neural_network"];
const TARGETS = ["target_2pct_1w", "target_3pct_1w", "risk_target_1w"];
const TOP_N_OPTIONS = [3, 5, 7, 10];
const HOLDING_OPTIONS = [
  { label: "1 week", value: 1 },
  { label: "2 weeks", value: 2 },
  { label: "4 weeks", value: 4 },
];

const ALL_FEATURE_OPTIONS = [
  "rsi_14","macd","macd_signal","macd_hist","sma_20","sma_50","sma_200","ema_12","ema_26",
  "bb_position","atr_14","volume_zscore","return_1w","return_4w","return_12w","momentum",
  "high_52w_distance","low_52w_distance","trend_strength","price_to_sma50","price_to_sma200","realized_vol",
  "pe_ratio","forward_pe","price_to_sales","price_to_book","ev_to_ebitda",
  "gross_margin","operating_margin","net_margin","roe","roa","revenue_growth","earnings_growth",
  "debt_to_equity","current_ratio","beta",
  "VIX","VIX_WEEKLY","VIX_CHANGE_W","TNX_10Y","FED_RATE_PROXY","RISK_ON_SCORE",
  "sp500_trend_20w","nasdaq_trend_20w","cpi_proxy_trend_26w",
  "news_sentiment_score","news_volume","news_earnings_flag",
  "social_mention_count","social_mention_momentum","social_sentiment_polarity",
  "pe_percentile_sector","pb_percentile_sector","ev_ebitda_percentile_sector",
];

const SP500_TICKERS = [
  "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","BRK-B","JPM","V",
  "UNH","XOM","JNJ","MA","PG","HD","CVX","MRK","LLY","ABBV",
];

interface BacktestResult {
  status: string;
  task_id?: string;
  results?: Array<{
    status: string;
    strategy_id?: number;
    avg_sharpe?: number;
    avg_win_rate?: number;
    total_trades?: number;
    deflated_sharpe?: number;
    permutation_pvalue?: number;
    outperforms_spy?: boolean;
    spy_sharpe?: number;
    benchmark_alpha?: number;
  }>;
}

interface DirectBacktestResult {
  status: string;
  n_folds?: number;
  avg_metrics?: Record<string, number | null>;
  folds?: Array<{
    fold: number;
    test_start: string;
    test_end: string;
    metrics: Record<string, number>;
    equity_curve: Array<{ date: string; equity: number }>;
  }>;
  reason?: string;
}

function StatBadge({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div className="bg-slate-700/60 rounded p-3">
      <div className="text-xs text-slate-400">{label}</div>
      <div className={`text-sm font-mono mt-0.5 ${good === true ? "text-green-400" : good === false ? "text-red-400" : "text-white"}`}>
        {value}
      </div>
    </div>
  );
}

export default function StrategyLab() {
  const [modelType, setModelType] = useState("lightgbm");
  const [target, setTarget] = useState("target_2pct_1w");
  const [threshold, setThreshold] = useState(0.5);
  const [topN, setTopN] = useState(5);
  const [holdingWeeks, setHoldingWeeks] = useState(1);
  const [applyLiquidityFilter, setApplyLiquidityFilter] = useState(true);
  const [nIterations, setNIterations] = useState(5);
  const [selectedTickers, setSelectedTickers] = useState<string[]>(SP500_TICKERS.slice(0, 10));
  const [selectedFeatures, setSelectedFeatures] = useState<string[]>(ALL_FEATURE_OPTIONS.slice(0, 22));
  const [pipelineStatus, setPipelineStatus] = useState<string | null>(null);
  const [researchResult, setResearchResult] = useState<BacktestResult | null>(null);
  const [directResult, setDirectResult] = useState<DirectBacktestResult | null>(null);
  const [running, setRunning] = useState(false);
  const [directRunning, setDirectRunning] = useState(false);
  const [promotedStrategies, setPromotedStrategies] = useState<BacktestResult["results"]>([]);

  function toggleTicker(t: string) {
    setSelectedTickers((prev) =>
      prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]
    );
  }

  function toggleFeature(f: string) {
    setSelectedFeatures((prev) =>
      prev.includes(f) ? prev.filter((x) => x !== f) : [...prev, f]
    );
  }

  async function runDirectBacktest() {
    setDirectRunning(true);
    setDirectResult(null);
    try {
      const res = await fetch(`${API}/backtest/direct`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_type: modelType,
          features: selectedFeatures,
          target,
          threshold,
          top_n: topN,
          holding_weeks: holdingWeeks,
          apply_liquidity_filter: applyLiquidityFilter,
          tickers: selectedTickers,
          min_train_years: 5,
        }),
      });
      const d: DirectBacktestResult = await res.json();
      setDirectResult(d);
    } catch {
      setDirectResult({ status: "error", reason: "Request failed" });
    } finally {
      setDirectRunning(false);
    }
  }

  async function triggerPipeline(endpoint: string, label: string, body?: object) {
    setPipelineStatus(`${label}...`);
    try {
      const res = await fetch(`${API}/pipeline/${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      const d = await res.json();
      setPipelineStatus(`${label} queued — task: ${d.task_id}`);
    } catch {
      setPipelineStatus(`${label} failed`);
    }
  }

  async function startResearch() {
    setRunning(true);
    setResearchResult(null);
    try {
      const res = await fetch(
        `${API}/strategies/research/start?n_iterations=${nIterations}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model_type: modelType, target, threshold, top_n: topN, holding_weeks: holdingWeeks, features: [] }),
        }
      );
      const d = await res.json();
      setResearchResult({ status: d.status, task_id: d.task_id });
    } catch {
      setResearchResult({ status: "error" });
    } finally {
      setRunning(false);
    }
  }

  async function loadPromotedStrategies() {
    try {
      const res = await fetch(`${API}/strategies`);
      const data: Array<{ id: number; name: string; status: string; notes: string }> = await res.json();
      // Parse notes JSON for metrics
      const parsed = data.filter((s) => ["candidate", "promoted"].includes(s.status)).map((s) => {
        try {
          const m = JSON.parse(s.notes || "{}");
          return { status: s.status, strategy_id: s.id, ...m };
        } catch {
          return { status: s.status, strategy_id: s.id };
        }
      });
      setPromotedStrategies(parsed);
    } catch {}
  }

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Strategy Lab</h1>
        <p className="text-slate-400 text-sm mt-1">Configure and run backtests. Research only — no live trading.</p>
      </div>

      {/* Stock selection */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-6 space-y-4">
        <h2 className="text-lg font-semibold text-white">1. Stock Universe</h2>
        <p className="text-sm text-slate-400">{selectedTickers.length} selected</p>
        <div className="flex flex-wrap gap-2">
          {SP500_TICKERS.map((t) => (
            <button
              key={t}
              onClick={() => toggleTicker(t)}
              className={`px-2 py-1 rounded text-xs font-mono border transition-colors ${
                selectedTickers.includes(t)
                  ? "bg-blue-600 border-blue-500 text-white"
                  : "bg-slate-700 border-slate-600 text-slate-300 hover:border-slate-400"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Data Pipeline */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-6 space-y-4">
        <h2 className="text-lg font-semibold text-white">2. Data Pipeline</h2>
        <div className="flex gap-3 flex-wrap">
          {[
            { label: "Snapshot Universe", endpoint: "snapshot-universe", body: { tickers: selectedTickers } },
            { label: "Ingest Prices", endpoint: "ingest", body: { tickers: selectedTickers } },
            { label: "Compute Features", endpoint: "features", body: { tickers: selectedTickers } },
            { label: "Macro (VIX/Yield/Sectors)", endpoint: "macro" },
            { label: "News & Sentiment", endpoint: "news", body: { tickers: selectedTickers } },
            { label: "Fundamentals", endpoint: "financials", body: { tickers: selectedTickers } },
            { label: "Statements (BS/IS/CF)", endpoint: "statements", body: { tickers: selectedTickers } },
            { label: "Social Sentiment", endpoint: "social", body: { tickers: selectedTickers } },
            { label: "Run All", endpoint: "run-all", body: { tickers: selectedTickers } },
          ].map(({ label, endpoint, body }) => (
            <button
              key={endpoint}
              onClick={() => triggerPipeline(endpoint, label, body)}
              className="px-3 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-medium"
            >
              {label}
            </button>
          ))}
        </div>
        {pipelineStatus && <p className="text-xs text-slate-400">{pipelineStatus}</p>}
      </div>

      {/* Feature Set Selector */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">3. Feature Set</h2>
          <span className="text-xs text-slate-400">{selectedFeatures.length} / {ALL_FEATURE_OPTIONS.length} selected</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {ALL_FEATURE_OPTIONS.map((f) => (
            <button key={f} onClick={() => toggleFeature(f)}
              className={`px-2 py-0.5 rounded text-xs font-mono border transition-colors ${
                selectedFeatures.includes(f)
                  ? "bg-teal-700 border-teal-600 text-white"
                  : "bg-slate-700 border-slate-600 text-slate-400 hover:border-slate-400"
              }`}>
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* Direct Backtest */}
      <div className="rounded-lg border border-indigo-700/50 bg-indigo-900/10 p-6 space-y-4">
        <h2 className="text-lg font-semibold text-white">4. Direct Backtest</h2>
        <p className="text-xs text-slate-400">Run walk-forward backtest immediately with selected features and config. Results appear inline.</p>

        <div className="grid grid-cols-3 gap-4">
          <div className="space-y-2">
            <label className="text-sm text-slate-300">Model</label>
            <select value={modelType} onChange={(e) => setModelType(e.target.value)}
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-white text-sm">
              {MODEL_TYPES.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-slate-300">Target</label>
            <select value={target} onChange={(e) => setTarget(e.target.value)}
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-white text-sm">
              {TARGETS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-slate-300">Holding Period</label>
            <select value={holdingWeeks} onChange={(e) => setHoldingWeeks(+e.target.value)}
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-white text-sm">
              {HOLDING_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-slate-300">Threshold: {threshold}</label>
            <input type="range" min={0.3} max={0.8} step={0.05} value={threshold}
              onChange={(e) => setThreshold(+e.target.value)} className="w-full accent-indigo-500" />
          </div>
          <div className="space-y-2">
            <label className="text-sm text-slate-300">Max Positions</label>
            <select value={topN} onChange={(e) => setTopN(+e.target.value)}
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-white text-sm">
              {TOP_N_OPTIONS.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={applyLiquidityFilter}
              onChange={(e) => setApplyLiquidityFilter(e.target.checked)}
              className="h-4 w-4 accent-indigo-500"
            />
            Apply $5M liquidity filter
          </label>
        </div>

        <button onClick={runDirectBacktest} disabled={directRunning || selectedTickers.length === 0 || selectedFeatures.length === 0}
          className="px-6 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded text-sm font-medium">
          {directRunning ? "Running Backtest..." : "Run Direct Backtest"}
        </button>

        {directResult && (
          <div className="space-y-4 mt-4">
            {directResult.status === "failed" || directResult.status === "error" ? (
              <p className="text-red-400 text-sm">{directResult.reason || "Backtest failed"}</p>
            ) : (
              <>
                <div className="grid grid-cols-4 gap-3">
                  {Object.entries(directResult.avg_metrics || {}).slice(0, 8).map(([k, v]) => (
                    <StatBadge key={k} label={k} value={v != null ? v.toFixed(3) : "—"}
                      good={k === "sharpe" ? (v ?? 0) > 0.5 : k === "max_drawdown" ? (v ?? 0) > -0.25 : undefined} />
                  ))}
                </div>
                <p className="text-xs text-slate-400">{directResult.n_folds} walk-forward folds</p>
                {directResult.folds?.slice(0, 1)[0]?.equity_curve && directResult.folds[0].equity_curve.length > 0 && (
                  <EquityChart data={directResult.folds[0].equity_curve} />
                )}
                <div className="overflow-x-auto">
                  <table className="w-full text-xs text-slate-300">
                    <thead>
                      <tr className="border-b border-slate-700 text-slate-400">
                        <th className="text-left py-1 pr-3">Fold</th>
                        <th className="text-left py-1 pr-3">Test Period</th>
                        <th className="text-right py-1 pr-3">Sharpe</th>
                        <th className="text-right py-1 pr-3">Win Rate</th>
                        <th className="text-right py-1 pr-3">Trades</th>
                        <th className="text-right py-1">Max DD</th>
                      </tr>
                    </thead>
                    <tbody>
                      {directResult.folds?.map((f) => (
                        <tr key={f.fold} className="border-b border-slate-800">
                          <td className="py-1 pr-3">{f.fold}</td>
                          <td className="py-1 pr-3 font-mono">{f.test_start} → {f.test_end}</td>
                          <td className={`text-right py-1 pr-3 ${(f.metrics.sharpe ?? 0) > 0 ? "text-green-400" : "text-red-400"}`}>
                            {f.metrics.sharpe?.toFixed(3) ?? "—"}
                          </td>
                          <td className="text-right py-1 pr-3">{f.metrics.win_rate != null ? `${(f.metrics.win_rate * 100).toFixed(1)}%` : "—"}</td>
                          <td className="text-right py-1 pr-3">{f.metrics.n_trades ?? "—"}</td>
                          <td className={`text-right py-1 ${(f.metrics.max_drawdown ?? 0) < -0.2 ? "text-red-400" : "text-slate-300"}`}>
                            {f.metrics.max_drawdown != null ? `${(f.metrics.max_drawdown * 100).toFixed(1)}%` : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Research Loop Config */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-6 space-y-6">
        <h2 className="text-lg font-semibold text-white">5. Auto Research Loop</h2>
        <p className="text-xs text-slate-400">Runs mutated strategy proposals through walk-forward + acceptance gate automatically. Runs in background via Celery.</p>

        <div className="flex items-end gap-4">
          <div className="space-y-2">
            <label className="text-sm text-slate-300">Iterations</label>
            <input type="number" min={1} max={50} value={nIterations}
              onChange={(e) => setNIterations(+e.target.value)}
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-white text-sm" />
          </div>
        </div>

        <div className="flex gap-3">
          <button
            onClick={startResearch}
            disabled={running || selectedTickers.length === 0}
            className="px-6 py-2.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white rounded text-sm font-medium"
          >
            {running ? "Running..." : "Start Research Loop"}
          </button>
          <button onClick={loadPromotedStrategies}
            className="px-4 py-2 bg-slate-600 hover:bg-slate-500 text-white rounded text-sm">
            Load Candidate/Promoted Strategies
          </button>
        </div>

        {researchResult && (
          <div className="text-sm text-slate-400">
            Status: <span className="text-white">{researchResult.status}</span>
            {researchResult.task_id && <span> · Task: {researchResult.task_id}</span>}
            <p className="text-xs text-slate-500 mt-1">
              Research runs in the background via Celery. Check the Strategies page for results.
            </p>
          </div>
        )}
      </div>

      {/* Promoted strategies results */}
      {promotedStrategies && promotedStrategies.length > 0 && (
        <div className="rounded-lg border border-green-700/40 bg-green-900/10 p-6 space-y-4">
          <h2 className="text-lg font-semibold text-green-400">Candidate / Promoted Strategies</h2>
          {promotedStrategies.map((s, i) => s && (
            <div key={i} className="border border-slate-700 rounded-lg p-4 bg-slate-800 space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-white">Strategy #{s.strategy_id}</span>
                <span className={`px-2 py-0.5 text-white rounded text-xs ${s.status === "promoted" ? "bg-green-600" : "bg-yellow-600"}`}>
                  {s.status === "promoted" ? "PROMOTED" : "PAPER TEST"}
                </span>
                {s.outperforms_spy && <span className="px-2 py-0.5 bg-blue-600 text-white rounded text-xs">Beats SPY</span>}
              </div>
              <div className="grid grid-cols-4 gap-3">
                <StatBadge label="Avg Sharpe" value={s.avg_sharpe?.toFixed(3) ?? "—"} good={(s.avg_sharpe ?? 0) > 0.5} />
                <StatBadge label="Deflated SR" value={s.deflated_sharpe?.toFixed(3) ?? "—"} good={(s.deflated_sharpe ?? 0) > 0} />
                <StatBadge label="Win Rate" value={s.avg_win_rate != null ? `${(s.avg_win_rate * 100).toFixed(1)}%` : "—"} good={(s.avg_win_rate ?? 0) > 0.5} />
                <StatBadge label="Total Trades" value={s.total_trades?.toString() ?? "—"} />
                <StatBadge label="Permutation p-val" value={s.permutation_pvalue?.toFixed(3) ?? "—"} good={(s.permutation_pvalue ?? 1) < 0.1} />
                <StatBadge label="SPY Sharpe" value={s.spy_sharpe?.toFixed(3) ?? "—"} />
                <StatBadge label="Outperforms SPY" value={s.outperforms_spy ? "Yes" : "No"} good={s.outperforms_spy} />
                <StatBadge label="Benchmark Alpha" value={s.benchmark_alpha != null ? `${(s.benchmark_alpha * 100).toFixed(2)}%` : "—"} good={(s.benchmark_alpha ?? 0) > 0} />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Acceptance Gate */}
      <div className="rounded-lg border border-yellow-700/40 bg-yellow-900/10 p-5 text-sm text-yellow-200/70 space-y-2">
        <div className="font-medium text-yellow-400 mb-2">Acceptance Gate (All Must Pass)</div>
        <div className="grid grid-cols-2 gap-1 text-xs">
          <div>Avg Sharpe ≥ 0.5</div>
          <div>Avg Win Rate ≥ 45%</div>
          <div>Total Trades ≥ 30</div>
          <div>Max Drawdown ≥ -25%</div>
          <div>Avg Profit Factor ≥ 1.1</div>
          <div>Permutation p-value &lt; 0.10</div>
          <div>Deflated Sharpe &gt; 0</div>
          <div>Walk-forward only (no data leakage)</div>
        </div>
        <div className="text-yellow-500/60 text-xs mt-2">
          Expect 80–95% rejection rate. This is correct behavior, not a bug.
        </div>
      </div>
    </div>
  );
}
