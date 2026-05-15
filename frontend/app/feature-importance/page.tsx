import { api } from "@/lib/api";

interface Strategy {
  id: number;
  name: string;
  status: string;
}

interface Importance {
  strategy_id: number;
  feature_importance: Record<string, number>;
}

async function getStrategies(): Promise<Strategy[]> {
  try { return await api.get<Strategy[]>("/strategies?status=promoted"); } catch { return []; }
}

async function getImportance(id: number): Promise<Importance | null> {
  try { return await api.get<Importance>(`/research/feature-importance/${id}`); } catch { return null; }
}

function Bar({ label, value, max }: { label: string; value: number; max: number }) {
  const width = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="flex items-center gap-3">
      <div className="w-40 text-xs text-slate-300 truncate text-right">{label}</div>
      <div className="flex-1 bg-slate-700 rounded h-4 overflow-hidden">
        <div className="h-4 bg-blue-500 rounded" style={{ width: `${width}%` }} />
      </div>
      <div className="w-14 text-xs text-slate-400 text-right">{(value * 100).toFixed(1)}%</div>
    </div>
  );
}

export default async function FeatureImportancePage() {
  const strategies = await getStrategies();

  const importances = await Promise.all(
    strategies.map(async (s) => ({ strategy: s, data: await getImportance(s.id) }))
  );

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Feature Importance</h1>
        <p className="text-slate-400 text-sm mt-1">Feature importances from promoted strategies' latest model runs.</p>
      </div>

      {importances.length === 0 && (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-8 text-center text-slate-400">
          No promoted strategies yet.
        </div>
      )}

      {importances.map(({ strategy, data }) => {
        if (!data || Object.keys(data.feature_importance).length === 0) return null;
        const sorted = Object.entries(data.feature_importance).sort((a, b) => b[1] - a[1]).slice(0, 20);
        const max = sorted[0]?.[1] ?? 1;
        return (
          <div key={strategy.id} className="rounded-lg border border-slate-700 bg-slate-800 p-6 space-y-3">
            <h2 className="text-lg font-semibold text-white">{strategy.name}</h2>
            {sorted.map(([fname, val]) => (
              <Bar key={fname} label={fname} value={val} max={max} />
            ))}
          </div>
        );
      })}
    </div>
  );
}
