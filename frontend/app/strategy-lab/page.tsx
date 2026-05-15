"use client";

import { useState } from "react";

interface RunResult {
  task_id?: string;
  status: string;
  results?: Array<{ status: string; strategy_id?: number; avg_sharpe?: number; total_trades?: number; reason?: string }>;
}

export default function StrategyLab() {
  const [nIterations, setNIterations] = useState(5);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const [pipelineStatus, setPipelineStatus] = useState<string | null>(null);

  async function startPipeline() {
    setPipelineStatus("Running...");
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/pipeline/run-all`, { method: "POST" });
      const data = await res.json();
      setPipelineStatus(`Queued — task: ${data.task_id}`);
    } catch {
      setPipelineStatus("Error starting pipeline");
    }
  }

  async function startResearch() {
    setRunning(true);
    setResult(null);
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/strategies/research/start?n_iterations=${nIterations}`,
        { method: "POST" }
      );
      const data = await res.json();
      setResult(data);
    } catch {
      setResult({ status: "error" });
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Strategy Lab</h1>
        <p className="text-slate-400 text-sm mt-1">Run the data pipeline and research loop. Research only — no live trading.</p>
      </div>

      {/* Pipeline trigger */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-6 space-y-4">
        <h2 className="text-lg font-semibold text-white">1. Data Pipeline</h2>
        <p className="text-sm text-slate-400">Ingest S&P 500 prices from yfinance and compute features. Runs in background via Celery.</p>
        <button
          onClick={startPipeline}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded text-sm font-medium transition-colors"
        >
          Run Full Pipeline
        </button>
        {pipelineStatus && <p className="text-xs text-slate-400">{pipelineStatus}</p>}
      </div>

      {/* Research loop */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-6 space-y-4">
        <h2 className="text-lg font-semibold text-white">2. Research Loop</h2>
        <p className="text-sm text-slate-400">
          Proposes strategy mutations, runs walk-forward backtest, and promotes strategies that pass the acceptance gate.
        </p>

        <div className="flex items-center gap-4">
          <label className="text-sm text-slate-300">Iterations:</label>
          <input
            type="number"
            min={1}
            max={50}
            value={nIterations}
            onChange={(e) => setNIterations(Number(e.target.value))}
            className="w-20 px-3 py-1.5 bg-slate-700 border border-slate-600 rounded text-white text-sm"
          />
          <button
            onClick={startResearch}
            disabled={running}
            className="px-4 py-2 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white rounded text-sm font-medium transition-colors"
          >
            {running ? "Running..." : "Start Research Loop"}
          </button>
        </div>

        {result && (
          <div className="mt-4 space-y-2">
            <p className="text-sm font-medium text-white">Result: <span className="text-slate-400">{result.status}</span></p>
            {result.task_id && <p className="text-xs text-slate-400">Task ID: {result.task_id}</p>}
          </div>
        )}
      </div>

      {/* Acceptance Gate info */}
      <div className="rounded-lg border border-yellow-700/40 bg-yellow-900/10 p-5 text-sm text-yellow-200/70 space-y-1">
        <div className="font-medium text-yellow-400 mb-2">Acceptance Gate Criteria</div>
        <div>Avg Sharpe ≥ 0.5</div>
        <div>Avg Win Rate ≥ 45%</div>
        <div>Total Trades ≥ 30</div>
        <div>Max Drawdown ≥ -25%</div>
        <div>Avg Profit Factor ≥ 1.1</div>
        <div className="text-yellow-500/60 text-xs mt-2">
          Strategies that pass all criteria are promoted. Expect 80-95% rejection rate — this is correct behavior.
        </div>
      </div>
    </div>
  );
}
