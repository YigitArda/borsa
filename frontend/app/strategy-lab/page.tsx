"use client";

import { useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const MODEL_TYPES = ["lightgbm", "logistic_regression", "random_forest", "gradient_boosting", "catboost"];
const TARGETS = ["target_2pct_1w", "target_3pct_1w", "risk_target_1w"];
const TOP_N_OPTIONS = [3, 5, 7, 10];
const HOLDING_OPTIONS = [
  { label: "1 week", value: 1 },
  { label: "2 weeks", value: 2 },
  { label: "4 weeks", value: 4 },
];

const SP500_TICKERS = [
  "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","BRK-B","JPM","V",
  "UNH","XOM","JNJ","MA","PG","HD","CVX","MRK","LLY","ABBV",
];

interface TaskResponse {
  task_id?: string;
  status: string;
  n_iterations?: number;
}

export default function StrategyLab() {
  const [modelType, setModelType] = useState("lightgbm");
  const [target, setTarget] = useState("target_2pct_1w");
  const [threshold, setThreshold] = useState(0.5);
  const [topN, setTopN] = useState(5);
  const [nIterations, setNIterations] = useState(5);
  const [selectedTickers, setSelectedTickers] = useState<string[]>(SP500_TICKERS.slice(0, 10));
  const [pipelineStatus, setPipelineStatus] = useState<string | null>(null);
  const [researchResult, setResearchResult] = useState<TaskResponse | null>(null);
  const [macroStatus, setMacroStatus] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  function toggleTicker(t: string) {
    setSelectedTickers((prev) =>
      prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]
    );
  }

  async function runPipeline() {
    setPipelineStatus("Ingesting prices...");
    try {
      const res = await fetch(`${API}/pipeline/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tickers: selectedTickers }),
      });
      const d = await res.json();
      setPipelineStatus(`Ingest queued — task: ${d.task_id}. Then run features.`);
    } catch {
      setPipelineStatus("Error");
    }
  }

  async function runFeatures() {
    setPipelineStatus("Computing features...");
    try {
      const res = await fetch(`${API}/pipeline/features`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tickers: selectedTickers }),
      });
      const d = await res.json();
      setPipelineStatus(`Features queued — task: ${d.task_id}`);
    } catch {
      setPipelineStatus("Error");
    }
  }

  async function runMacro() {
    setMacroStatus("Ingesting macro data (VIX, 10Y, S&P, Nasdaq)...");
    try {
      const res = await fetch(`${API}/pipeline/macro`, { method: "POST" });
      const d = await res.json();
      setMacroStatus(`Macro queued — task: ${d.task_id}`);
    } catch {
      setMacroStatus("Error");
    }
  }

  async function startResearch() {
    setRunning(true);
    setResearchResult(null);
    try {
      const config = { model_type: modelType, target, threshold, top_n: topN, features: [] };
      const res = await fetch(
        `${API}/strategies/research/start?n_iterations=${nIterations}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(config),
        }
      );
      const d = await res.json();
      setResearchResult(d);
    } catch {
      setResearchResult({ status: "error" });
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Strategy Lab</h1>
        <p className="text-slate-400 text-sm mt-1">Configure and run backtests. Research only — no live trading.</p>
      </div>

      {/* Stock selection */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-6 space-y-4">
        <h2 className="text-lg font-semibold text-white">1. Stock Universe</h2>
        <p className="text-sm text-slate-400">Select tickers ({selectedTickers.length} selected)</p>
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
          <button onClick={runPipeline} className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded text-sm font-medium">
            Ingest Prices
          </button>
          <button onClick={runFeatures} className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded text-sm font-medium">
            Compute Features
          </button>
          <button onClick={runMacro} className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded text-sm font-medium">
            Ingest Macro (VIX / Yield)
          </button>
        </div>
        {pipelineStatus && <p className="text-xs text-slate-400">{pipelineStatus}</p>}
        {macroStatus && <p className="text-xs text-slate-400">{macroStatus}</p>}
      </div>

      {/* Research config */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-6 space-y-6">
        <h2 className="text-lg font-semibold text-white">3. Research Loop Config</h2>

        <div className="grid grid-cols-2 gap-6">
          <div className="space-y-2">
            <label className="text-sm text-slate-300">Model Type</label>
            <select
              value={modelType}
              onChange={(e) => setModelType(e.target.value)}
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-white text-sm"
            >
              {MODEL_TYPES.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>

          <div className="space-y-2">
            <label className="text-sm text-slate-300">Target</label>
            <select
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-white text-sm"
            >
              {TARGETS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>

          <div className="space-y-2">
            <label className="text-sm text-slate-300">Threshold: {threshold}</label>
            <input
              type="range" min={0.3} max={0.8} step={0.05} value={threshold}
              onChange={(e) => setThreshold(+e.target.value)}
              className="w-full accent-blue-500"
            />
          </div>

          <div className="space-y-2">
            <label className="text-sm text-slate-300">Max Positions / Week</label>
            <select
              value={topN}
              onChange={(e) => setTopN(+e.target.value)}
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-white text-sm"
            >
              {TOP_N_OPTIONS.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>

          <div className="space-y-2">
            <label className="text-sm text-slate-300">Research Iterations</label>
            <input
              type="number" min={1} max={50} value={nIterations}
              onChange={(e) => setNIterations(+e.target.value)}
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-white text-sm"
            />
          </div>
        </div>

        <button
          onClick={startResearch}
          disabled={running || selectedTickers.length === 0}
          className="px-6 py-2.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white rounded text-sm font-medium transition-colors"
        >
          {running ? "Running Research Loop..." : "Start Research Loop"}
        </button>

        {researchResult && (
          <div className="text-sm text-slate-400">
            Status: <span className="text-white">{researchResult.status}</span>
            {researchResult.task_id && <span> · Task: {researchResult.task_id}</span>}
          </div>
        )}
      </div>

      {/* Acceptance Gate */}
      <div className="rounded-lg border border-yellow-700/40 bg-yellow-900/10 p-5 text-sm text-yellow-200/70 space-y-1">
        <div className="font-medium text-yellow-400 mb-2">Acceptance Gate Criteria</div>
        <div className="grid grid-cols-2 gap-1">
          <div>Avg Sharpe ≥ 0.5</div>
          <div>Avg Win Rate ≥ 45%</div>
          <div>Total Trades ≥ 30</div>
          <div>Max Drawdown ≥ -25%</div>
          <div>Avg Profit Factor ≥ 1.1</div>
          <div>Walk-forward only (no data leakage)</div>
        </div>
        <div className="text-yellow-500/60 text-xs mt-2">
          Expect 80–95% rejection rate. This is correct behavior, not a bug.
        </div>
      </div>
    </div>
  );
}
