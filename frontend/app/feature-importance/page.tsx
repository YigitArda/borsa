import { api } from "@/lib/api";

interface Strategy {
  id: number;
  name: string;
  status: string;
}

interface ImportanceData {
  strategy_id: number;
  feature_importance: Record<string, number>;
  shap_importance: Record<string, number>;
}

async function getStrategies(): Promise<Strategy[]> {
  try {
    const promoted = await api.get<Strategy[]>("/strategies?status=promoted");
    if (promoted.length > 0) return promoted;
    // Fall back to all strategies if none are promoted yet
    return await api.get<Strategy[]>("/strategies?limit=5");
  } catch { return []; }
}

async function getImportance(id: number): Promise<ImportanceData | null> {
  try { return await api.get<ImportanceData>(`/research/feature-importance/${id}`); } catch { return null; }
}

function ImportanceTable({ data, title }: { data: Record<string, number>; title: string }) {
  const sorted = Object.entries(data).sort((a, b) => b[1] - a[1]).slice(0, 15);
  const max = sorted[0]?.[1] ?? 1;
  if (sorted.length === 0) return null;

  return (
    <div className="box" style={{ marginBottom: "8px" }}>
      <div className="box-head">{title}</div>
      <div className="box-body" style={{ padding: 0 }}>
        <table className="data-table" style={{ marginBottom: 0 }}>
          <thead>
            <tr>
              <th style={{ width: "24px" }}>#</th>
              <th>Feature</th>
              <th style={{ width: "120px" }}>Bar</th>
              <th style={{ width: "60px", textAlign: "right" }}>Skor</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(([fname, val], i) => {
              const pct = max > 0 ? (val / max) * 100 : 0;
              return (
                <tr key={fname}>
                  <td style={{ color: "#666", textAlign: "center" }}>{i + 1}</td>
                  <td style={{ fontFamily: "monospace", fontSize: "11px" }}>{fname}</td>
                  <td>
                    <div style={{
                      height: "10px", background: "#d4d0c8", border: "1px solid #999",
                      borderRadius: "1px", overflow: "hidden",
                    }}>
                      <div style={{
                        height: "100%", width: `${pct}%`,
                        background: "linear-gradient(to right, #336699, #6699cc)",
                      }} />
                    </div>
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "monospace", fontSize: "11px" }}>
                    {(val * 100).toFixed(1)}%
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default async function FeatureImportancePage() {
  const strategies = await getStrategies();

  const importances = await Promise.all(
    strategies.map(async (s) => ({ strategy: s, data: await getImportance(s.id) }))
  );

  const hasData = importances.some(
    ({ data }) =>
      data &&
      (Object.keys(data.feature_importance).length > 0 ||
        Object.keys(data.shap_importance).length > 0)
  );

  return (
    <div>
      <h1>Feature Importance</h1>

      <div className="alert alert-info">
        Model ve SHAP tabanlı feature importance skorları. SHAP, walk-forward fold ortalamasıdır.
      </div>

      {strategies.length === 0 && (
        <div className="alert alert-warning">
          Henüz strateji bulunamadı.
        </div>
      )}

      {strategies.length > 0 && !hasData && (
        <div className="alert alert-warning">
          Stratejiler var fakat feature importance verisi yok. Model eğitimi sonrasında burada görünecek.
        </div>
      )}

      {importances.map(({ strategy, data }) => {
        if (!data) return null;
        const hasFI = Object.keys(data.feature_importance).length > 0;
        const hasSHAP = Object.keys(data.shap_importance).length > 0;
        if (!hasFI && !hasSHAP) return null;

        return (
          <div key={strategy.id} style={{ marginBottom: "16px" }}>
            <div style={{
              background: "linear-gradient(to bottom, #336699, #003366)",
              color: "white", padding: "4px 8px", fontSize: "12px", fontWeight: "bold",
              display: "flex", justifyContent: "space-between", alignItems: "center",
            }}>
              <span>Strateji #{strategy.id} — {strategy.name}</span>
              <span className={`badge ${strategy.status === "promoted" ? "badge-success" : "badge-info"}`}>
                {strategy.status.toUpperCase()}
              </span>
            </div>

            <div style={{ padding: "8px 0" }}>
              {hasSHAP && (
                <ImportanceTable
                  data={data.shap_importance}
                  title="SHAP Importance (Walk-Forward Fold Ortalaması)"
                />
              )}
              {hasFI && (
                <ImportanceTable
                  data={data.feature_importance}
                  title="Model Feature Importance (Son Model Run)"
                />
              )}
            </div>
          </div>
        );
      })}

      <div style={{
        textAlign: "center", padding: "6px", background: "#e8f0f8",
        border: "1px solid #c0c0c0", fontSize: "10px",
        fontFamily: "Tahoma,sans-serif", color: "#666", marginTop: "8px"
      }}>
        Bu sistem yalnızca araştırma amaçlıdır, yatırım tavsiyesi değildir
      </div>
    </div>
  );
}
