import { loadApi } from "@/lib/server-api";

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

async function loadStrategies() {
  const promoted = await loadApi<Strategy[]>("/strategies?status=promoted");
  if ((promoted.data ?? []).length > 0) {
    return promoted;
  }
  const fallback = await loadApi<Strategy[]>("/strategies?limit=5");
  return {
    data: fallback.data ?? promoted.data ?? [],
    error: promoted.error ?? fallback.error,
  };
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
              <th style={{ width: "60px", textAlign: "right" }}>Score</th>
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
  const strategiesResult = await loadStrategies();
  const strategies = strategiesResult.data ?? [];

  const importances = await Promise.all(
    strategies.map(async (strategy) => {
      const result = await loadApi<ImportanceData>(`/research/feature-importance/${strategy.id}`);
      return { strategy, ...result };
    })
  );

  const errors = [
    strategiesResult.error,
    ...importances.map(({ error }) => error),
  ].filter(Boolean) as string[];

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
        Model ve SHAP tabanli feature importance skorlar. SHAP, walk-forward fold ortalamasidir.
      </div>

      {errors.length > 0 && (
        <div className="alert alert-warning">
          Some feature importance data could not be loaded: {errors.join(" · ")}
        </div>
      )}

      {strategies.length === 0 && (
        <div className="alert alert-warning">
          Henuz strateji bulunamadi.
        </div>
      )}

      {strategies.length > 0 && !hasData && (
        <div className="alert alert-warning">
          Stratejiler var fakat feature importance verisi yok. Model egitimi sonrasinda burada gorunecek.
        </div>
      )}

      {importances.map(({ strategy, data, error }) => {
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
              <span>Strateji #{strategy.id} - {strategy.name}</span>
              <span className={`badge ${strategy.status === "promoted" ? "badge-success" : "badge-info"}`}>
                {strategy.status.toUpperCase()}
              </span>
            </div>

            {error && (
              <div className="alert alert-warning" style={{ marginTop: "8px" }}>
                {error}
              </div>
            )}

            <div style={{ padding: "8px 0" }}>
              {hasSHAP && (
                <ImportanceTable
                  data={data.shap_importance}
                  title="SHAP Importance (Walk-Forward Fold Average)"
                />
              )}
              {hasFI && (
                <ImportanceTable
                  data={data.feature_importance}
                  title="Model Feature Importance (Last Model Run)"
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
        Bu sistem yalnizca arastirma amaclidir, yatirim tavsiyesi degildir
      </div>
    </div>
  );
}
