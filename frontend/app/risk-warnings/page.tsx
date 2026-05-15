import { api } from "@/lib/api";

interface Warning {
  strategy_id: number;
  name: string;
  warning: string;
  severity: "high" | "medium" | "low";
}

interface WarningsResponse {
  warnings: Warning[];
  count: number;
}

async function getWarnings(): Promise<WarningsResponse> {
  try { return await api.get<WarningsResponse>("/research/risk-warnings"); }
  catch { return { warnings: [], count: 0 }; }
}

const severityStyle = {
  high: "text-red-400 bg-red-400/10 border-red-700",
  medium: "text-yellow-400 bg-yellow-400/10 border-yellow-700",
  low: "text-blue-400 bg-blue-400/10 border-blue-700",
};

export default async function RiskWarnings() {
  const { warnings, count } = await getWarnings();

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Risk Warnings</h1>
        <p className="text-slate-400 text-sm mt-1">
          System self-diagnostics — degrading strategies, data drift, anomalies.
        </p>
      </div>

      {count === 0 ? (
        <div className="rounded-lg border border-green-700/40 bg-green-900/10 p-6 text-green-400">
          No active warnings. All promoted strategies are within acceptable parameters.
        </div>
      ) : (
        <div className="space-y-4">
          {warnings.map((w, i) => (
            <div key={i} className={`rounded-lg border p-5 ${severityStyle[w.severity] || severityStyle.low}`}>
              <div className="flex items-center justify-between mb-2">
                <span className="font-semibold">{w.name}</span>
                <span className={`text-xs px-2 py-0.5 rounded uppercase font-medium ${severityStyle[w.severity]}`}>
                  {w.severity}
                </span>
              </div>
              <p className="text-sm opacity-80">{w.warning}</p>
              <p className="text-xs opacity-50 mt-1">Strategy ID: {w.strategy_id}</p>
            </div>
          ))}
        </div>
      )}

      <div className="rounded-lg border border-slate-700 bg-slate-800 p-5 text-sm text-slate-400 space-y-2">
        <div className="font-medium text-slate-300">What triggers a warning?</div>
        <ul className="list-disc list-inside space-y-1">
          <li>Promoted strategy recent 3-fold avg Sharpe &lt; 0.2</li>
          <li>Prediction probability distribution shifted significantly</li>
          <li>Feature data staleness &gt; 2 weeks</li>
          <li>Walk-forward OOS worse than IS by &gt; 50%</li>
        </ul>
      </div>
    </div>
  );
}
