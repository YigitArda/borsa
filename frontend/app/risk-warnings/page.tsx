import { api } from "@/lib/api";

export default async function RiskWarningsPage() {
  const data = await api.get<any>("/research/risk-warnings").catch(
    () => ({ warnings: [], count: 0 })
  );

  return (
    <div>
      <h1>⚠️ Risk Uyarıları</h1>

      <div className="alert alert-info">
        ℹ Sistem kendi kendini denetliyor. Aşağıdaki uyarılar otomatik tespit edilmiştir.
      </div>

      {data.count === 0 ? (
        <div className="alert alert-success">
          ✅ Aktif risk uyarısı bulunmuyor. Tüm stratejiler kabul edilebilir parametreler dahilinde.
        </div>
      ) : (
        <div className="box">
          <div className="box-head">⚠️ Aktif Uyarılar ({data.count} adet)</div>
          <div className="box-body" style={{ padding: 0 }}>
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th>Strateji</th>
                  <th>Önem</th>
                  <th>Uyarı</th>
                </tr>
              </thead>
              <tbody>
                {data.warnings.map((w: any, i: number) => (
                  <tr key={i}>
                    <td>
                      {w.strategy_id
                        ? <a href={`/strategies/${w.strategy_id}`}>#{w.strategy_id}</a>
                        : "—"}
                    </td>
                    <td>
                      <span className={`badge ${
                        w.severity === "high" ? "badge-danger" :
                        w.severity === "medium" ? "badge-warning" : "badge-info"
                      }`}>
                        {w.severity === "high" ? "YÜKSEK" :
                         w.severity === "medium" ? "ORTA" : "DÜŞÜK"}
                      </span>
                    </td>
                    <td style={{ fontSize: "11px" }}>{w.warning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

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
