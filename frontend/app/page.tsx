import { loadApi } from "@/lib/server-api";
import Tooltip from "@/components/Tooltip";
import { getTooltip } from "@/lib/tooltips";

export default async function HomePage() {
  const [stocksResult, strategiesResult, paperResult, killSwitchResult] = await Promise.all([
    loadApi<any[]>("/stocks"),
    loadApi<any[]>("/strategies?status=promoted"),
    loadApi<any>("/weekly-picks/paper?limit=5"),
    loadApi<any>("/research/kill-switch/status"),
  ]);

  const stocks = stocksResult.data ?? [];
  const strategies = strategiesResult.data ?? [];
  const paper = paperResult.data;
  const killSwitch = killSwitchResult.data;
  const errors = [stocksResult.error, strategiesResult.error, paperResult.error, killSwitchResult.error].filter(Boolean) as string[];

  const hitRate = paper?.summary?.hit_rate_2pct;
  const openTrades = paper?.summary?.open ?? 0;
  const closedTrades = paper?.summary?.closed ?? 0;
  const avgReturn = paper?.summary?.avg_realized_return;
  const ksActive = killSwitch?.active ?? false;

  return (
    <div>
      <h1>Ana Sayfa - Arastirma Ozeti</h1>

      {errors.length > 0 && (
        <div className="alert alert-warning">
          <b>Veri kaynağı uyarısı:</b> {errors.join(" · ")}
        </div>
      )}

      {ksActive && (
        <div className="alert alert-danger">
          <b>Dikkat:</b> Kill switch aktif - tahmin uretimi durduruldu.
          {killSwitch?.warnings?.length > 0 && (
            <> Sebep: {killSwitch.warnings[0]?.reason}</>
          )}
        </div>
      )}

      <table className="data-table" style={{ marginBottom: "12px" }}>
        <thead>
          <tr>
            <th>
              <Tooltip text="Sistemde izlenen hisse sayisi" position="top">Takip Edilen Hisse</Tooltip>
            </th>
            <th>
              <Tooltip text="Kabul kapisindan gecmis onayli strateji sayisi" position="top">Promoted Strateji</Tooltip>
            </th>
            <th>
              <Tooltip text="Paper trading'de kapandiginiz toplam islem" position="top">Toplam Trade</Tooltip>
            </th>
            <th>
              <Tooltip text={getTooltip("Hit Rate") || "Hedeflenen %2 getiriyi yakalama orani"} position="top">Hit Rate (&gt;= %2)</Tooltip>
            </th>
            <th>
              <Tooltip text="Paper trading'deki ortalama gerceklesen getiri" position="top">Ort. Getiri</Tooltip>
            </th>
            <th>
              <Tooltip text="Hala acik olan (kapanmamis) pozisyon sayisi" position="top">Acik Trade</Tooltip>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><b>{stocks.length}</b></td>
            <td><b>{strategies.length}</b></td>
            <td><b>{closedTrades}</b> kapandi</td>
            <td>
              {hitRate != null ? (
                <span className={hitRate >= 0.45 ? "text-green" : "text-red"}>
                  {(hitRate * 100).toFixed(1)}%
                </span>
              ) : <span className="text-muted">-</span>}
            </td>
            <td>
              {avgReturn != null ? (
                <span className={avgReturn >= 0 ? "text-green" : "text-red"}>
                  {avgReturn >= 0 ? "+" : ""}{(avgReturn * 100).toFixed(2)}%
                </span>
              ) : <span className="text-muted">-</span>}
            </td>
            <td><b>{openTrades}</b></td>
          </tr>
        </tbody>
      </table>

      {paper?.trades && paper.trades.length > 0 && (
        <div className="box" style={{ marginBottom: "12px" }}>
          <div className="box-head">Son Paper Trade Sinyalleri</div>
          <div className="box-body" style={{ padding: 0 }}>
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th>Hafta</th>
                  <th>Hisse</th>
                  <th>
                    <Tooltip text={getTooltip("P(>= %2)") || "1 haftada %2+ getiri olasiligi"} position="top">P(&gt;= %2)</Tooltip>
                  </th>
                  <th>
                    <Tooltip text={getTooltip("Beklenen Getiri") || "Modelin tahmini ortalama getirisi"} position="top">Beklenen Getiri</Tooltip>
                  </th>
                  <th>
                    <Tooltip text="Gerceklesen getiri (kapandiysa)" position="top">Gerceklesen</Tooltip>
                  </th>
                  <th>Durum</th>
                </tr>
              </thead>
              <tbody>
                {paper.trades.slice(0, 8).map((t: any, i: number) => (
                  <tr key={i} className={t.hit_2pct ? "highlight" : ""}>
                    <td style={{ fontFamily: "monospace", fontSize: "10px" }}>{t.week_starting}</td>
                    <td>
                      <a href={`/stocks/${t.ticker}`}><b>{t.ticker}</b></a>
                      {t.confidence === "high" && <> <span className="badge badge-success">YUKSEK</span></>}
                    </td>
                    <td className={t.prob_2pct >= 0.6 ? "text-green" : ""}>
                      {t.prob_2pct != null ? `${(t.prob_2pct * 100).toFixed(1)}%` : "-"}
                    </td>
                    <td>
                      {t.expected_return != null
                        ? <span className={t.expected_return >= 0 ? "text-green" : "text-red"}>
                            {t.expected_return >= 0 ? "+" : ""}{(t.expected_return * 100).toFixed(1)}%
                          </span>
                        : "-"}
                    </td>
                    <td>
                      {t.realized_return != null
                        ? <span className={t.realized_return >= 0 ? "text-green" : "text-red"}>
                            {t.realized_return >= 0 ? "+" : ""}{(t.realized_return * 100).toFixed(2)}%
                          </span>
                        : "-"}
                    </td>
                    <td>
                      <span className={`badge ${t.status === "closed" ? "badge-info" : t.status === "open" ? "badge-warning" : "badge-info"}`}>
                        {t.status === "closed" ? "KAPANDI" : t.status === "open" ? "ACIK" : t.status?.toUpperCase()}
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
        <div className="box-head">Hisse Evreni ({stocks.length} hisse)</div>
        <div className="box-body" style={{ padding: 0 }}>
          <table className="data-table" style={{ marginBottom: 0 }}>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Sirket Adi</th>
                <th>Sektor</th>
                <th>Detay</th>
              </tr>
            </thead>
            <tbody>
              {stocks.map((s: any) => (
                <tr key={s.ticker}>
                  <td><b><a href={`/stocks/${s.ticker}`}>{s.ticker}</a></b></td>
                  <td>{s.name}</td>
                  <td style={{ color: "#336699" }}>{s.sector}</td>
                  <td><a href={`/stocks/${s.ticker}`}>arastir &raquo;</a></td>
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
        Borsa Research Engine v1.0 | Bu sistem yalnizca arastirma amaclidir, yatirim tavsiyesi degildir | <a href="/admin">Yonetim Paneli</a>
      </div>
    </div>
  );
}
