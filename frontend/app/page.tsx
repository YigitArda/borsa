import { api } from "@/lib/api";

async function getStocks() {
  try { return await api.get<any[]>("/stocks"); } catch { return []; }
}
async function getStrategies() {
  try { return await api.get<any[]>("/strategies?status=promoted"); } catch { return []; }
}
async function getPaper() {
  try { return await api.get<any>("/weekly-picks/paper?limit=5"); } catch { return null; }
}
async function getKillSwitch() {
  try { return await api.get<any>("/research/kill-switch/status"); } catch { return null; }
}

export default async function HomePage() {
  const [stocks, strategies, paper, killSwitch] = await Promise.all([
    getStocks(), getStrategies(), getPaper(), getKillSwitch()
  ]);

  const hitRate = paper?.summary?.hit_rate_2pct;
  const openTrades = paper?.summary?.open ?? 0;
  const closedTrades = paper?.summary?.closed ?? 0;
  const avgReturn = paper?.summary?.avg_realized_return;
  const ksActive = killSwitch?.active ?? false;

  return (
    <div>
      <h1>📊 Ana Sayfa — Araştırma Özeti</h1>

      {ksActive && (
        <div className="alert alert-danger">
          🛑 <b>DİKKAT:</b> Kill switch aktif — tahmin üretimi durduruldu.
          {killSwitch?.warnings?.length > 0 && (
            <> Sebep: {killSwitch.warnings[0]?.reason}</>
          )}
        </div>
      )}

      <table className="data-table" style={{ marginBottom: "12px" }}>
        <thead>
          <tr>
            <th>📦 Takip Edilen Hisse</th>
            <th>✅ Promoted Strateji</th>
            <th>📄 Toplam Trade</th>
            <th>🎯 Hit Rate (≥%2)</th>
            <th>💹 Ort. Getiri</th>
            <th>🔓 Açık Trade</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><b>{stocks.length}</b></td>
            <td><b>{strategies.length}</b></td>
            <td><b>{closedTrades}</b> kapandı</td>
            <td>
              {hitRate != null ? (
                <span className={hitRate >= 0.45 ? "text-green" : "text-red"}>
                  {(hitRate * 100).toFixed(1)}%
                </span>
              ) : <span className="text-muted">—</span>}
            </td>
            <td>
              {avgReturn != null ? (
                <span className={avgReturn >= 0 ? "text-green" : "text-red"}>
                  {avgReturn >= 0 ? "+" : ""}{(avgReturn * 100).toFixed(2)}%
                </span>
              ) : <span className="text-muted">—</span>}
            </td>
            <td><b>{openTrades}</b></td>
          </tr>
        </tbody>
      </table>

      {paper?.trades && paper.trades.length > 0 && (
        <div className="box" style={{ marginBottom: "12px" }}>
          <div className="box-head">📈 Son Paper Trade Sinyalleri</div>
          <div className="box-body" style={{ padding: 0 }}>
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th>Hafta</th>
                  <th>Hisse</th>
                  <th>P(≥%2)</th>
                  <th>Beklenen Getiri</th>
                  <th>Gerçekleşen</th>
                  <th>Durum</th>
                </tr>
              </thead>
              <tbody>
                {paper.trades.slice(0, 8).map((t: any, i: number) => (
                  <tr key={i} className={t.hit_2pct ? "highlight" : ""}>
                    <td style={{ fontFamily: "monospace", fontSize: "10px" }}>{t.week_starting}</td>
                    <td>
                      <a href={`/stocks/${t.ticker}`}><b>{t.ticker}</b></a>
                      {t.confidence === "high" && <> <span className="badge badge-success">YÜKSEK</span></>}
                    </td>
                    <td className={t.prob_2pct >= 0.6 ? "text-green" : ""}>
                      {t.prob_2pct != null ? `${(t.prob_2pct * 100).toFixed(1)}%` : "—"}
                    </td>
                    <td>
                      {t.expected_return != null
                        ? <span className={t.expected_return >= 0 ? "text-green" : "text-red"}>
                            {t.expected_return >= 0 ? "+" : ""}{(t.expected_return * 100).toFixed(1)}%
                          </span>
                        : "—"}
                    </td>
                    <td>
                      {t.realized_return != null
                        ? <span className={t.realized_return >= 0 ? "text-green" : "text-red"}>
                            {t.realized_return >= 0 ? "+" : ""}{(t.realized_return * 100).toFixed(2)}%
                          </span>
                        : "—"}
                    </td>
                    <td>
                      <span className={`badge ${t.status === "closed" ? "badge-info" : t.status === "open" ? "badge-warning" : "badge-info"}`}>
                        {t.status === "closed" ? "KAPANDI" : t.status === "open" ? "AÇIK" : t.status?.toUpperCase()}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="box">
        <div className="box-head">📦 Hisse Evreni ({stocks.length} hisse)</div>
        <div className="box-body" style={{ padding: 0 }}>
          <table className="data-table" style={{ marginBottom: 0 }}>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Şirket Adı</th>
                <th>Sektör</th>
                <th>Detay</th>
              </tr>
            </thead>
            <tbody>
              {stocks.map((s: any) => (
                <tr key={s.ticker}>
                  <td><b><a href={`/stocks/${s.ticker}`}>{s.ticker}</a></b></td>
                  <td>{s.name}</td>
                  <td style={{ color: "#336699" }}>{s.sector}</td>
                  <td><a href={`/stocks/${s.ticker}/research`}>araştır &raquo;</a></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div style={{
        textAlign: "center", padding: "6px", background: "#e8f0f8",
        border: "1px solid #c0c0c0", fontSize: "10px",
        fontFamily: "Tahoma,sans-serif", color: "#666", marginTop: "8px"
      }}>
        Borsa Research Engine v1.0 &nbsp;|&nbsp;
        Bu sistem yalnızca araştırma amaçlıdır, yatırım tavsiyesi değildir &nbsp;|&nbsp;
        <a href="/admin">Yönetim Paneli</a>
      </div>
    </div>
  );
}
