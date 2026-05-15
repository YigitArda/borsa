import { api } from "@/lib/api";
import Tooltip from "@/components/Tooltip";
import { getTooltip } from "@/lib/tooltips";

export default async function WeeklyPicksPage() {
  const picks = await api.get<any[]>("/weekly-picks").catch(() => []);
  const paper = await api.get<any>("/weekly-picks/paper?limit=20").catch(() => null);

  return (
    <div>
      <h1>📈 Haftalık Sinyaller</h1>

      <div className="alert alert-info">
        ℹ <b>Bilgi:</b> Sinyaller her Cuma akşamı güncellenir.
        Olasılık tahminleri geçmiş veriye dayalıdır, garanti değildir.
      </div>

      {picks.length === 0 ? (
        <div className="alert alert-warning">
          ⚠ Bu hafta için sinyal bulunamadı.
          <a href="/strategy-lab"> Pipeline çalıştırmak için tıklayın.</a>
        </div>
      ) : (
        <div className="box">
          <div className="box-head">
            📊 Bu Haftanın Sinyalleri
            {picks[0]?.week_starting && (
              <span style={{ fontWeight: "normal", marginLeft: "8px" }}>
                — Hafta: {picks[0].week_starting}
              </span>
            )}
          </div>
          <div className="box-body" style={{ padding: 0 }}>
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Ticker</th>
                  <th>Şirket</th>
                  <th>Sektör</th>
                  <th><Tooltip text={getTooltip("P(≥%2)") || "1 haftada %2+ getiri olasiligi"} position="top">P(≥%2)</Tooltip></th>
                  <th><Tooltip text="1 haftada %2+ kayip olasiligi" position="top">P(≤-%2)</Tooltip></th>
                  <th><Tooltip text={getTooltip("Beklenen Getiri") || "Model tahmini ortalama getiri"} position="top">Beklenen Getiri</Tooltip></th>
                  <th><Tooltip text={getTooltip("Güven") || "Model güven seviyesi"} position="top">Güven</Tooltip></th>
                  <th>Sinyal Özeti</th>
                </tr>
              </thead>
              <tbody>
                {picks.map((p: any) => (
                  <tr key={p.ticker}>
                    <td style={{ color: "#666" }}>{p.rank}</td>
                    <td>
                      <b><a href={`/stocks/${p.ticker}`}>{p.ticker}</a></b>
                      {p.confidence === "high" && <> <span className="badge badge-success">YEN</span></>}
                    </td>
                    <td style={{ fontSize: "10px" }}>{p.name}</td>
                    <td style={{ fontSize: "10px", color: "#336699" }}>{p.sector}</td>
                    <td>
                      <span className={p.prob_2pct >= 0.6 ? "text-green" : ""}>
                        {p.prob_2pct != null ? `${(p.prob_2pct * 100).toFixed(1)}%` : "—"}
                      </span>
                    </td>
                    <td>
                      <span className={p.prob_loss_2pct >= 0.3 ? "text-red" : "text-muted"}>
                        {p.prob_loss_2pct != null ? `${(p.prob_loss_2pct * 100).toFixed(1)}%` : "—"}
                      </span>
                    </td>
                    <td>
                      {p.expected_return != null ? (
                        <span className={p.expected_return >= 0 ? "text-green" : "text-red"}>
                          {p.expected_return >= 0 ? "+" : ""}{(p.expected_return * 100).toFixed(2)}%
                        </span>
                      ) : "—"}
                    </td>
                    <td>
                      <span className={`badge ${
                        p.confidence === "high" ? "badge-success" :
                        p.confidence === "medium" ? "badge-warning" : "badge-info"
                      }`}>
                        {p.confidence === "high" ? "YÜKSEK" :
                         p.confidence === "medium" ? "ORTA" : "DÜŞÜK"}
                      </span>
                    </td>
                    <td style={{ fontSize: "10px", color: "#666", maxWidth: "150px" }}>
                      {p.signal_summary ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {paper?.summary && (
        <div className="box" style={{ marginTop: "12px" }}>
          <div className="box-head">📋 Paper Trading Özeti</div>
          <div className="box-body">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Toplam</th>
                  <th>Açık</th>
                  <th>Kapandı</th>
                  <th><Tooltip text={getTooltip("Hit Rate") || "Hedef %2 getiriyi yakalama orani"} position="top">Hit Rate ≥%2</Tooltip></th>
                  <th>Ort. Olasılık</th>
                  <th>Ort. Gerçekleşen</th>
                  <th><Tooltip text={getTooltip("Kalibrasyon Hatası") || "Tahmin ile gerceklesme arasi fark"} position="top">Kalibrasyon Hatası</Tooltip></th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td><b>{paper.summary.total}</b></td>
                  <td>{paper.summary.open}</td>
                  <td>{paper.summary.closed}</td>
                  <td>
                    {paper.summary.hit_rate_2pct != null ? (
                      <span className={paper.summary.hit_rate_2pct >= 0.45 ? "text-green" : "text-red"}>
                        <b>{(paper.summary.hit_rate_2pct * 100).toFixed(1)}%</b>
                      </span>
                    ) : "—"}
                  </td>
                  <td>
                    {paper.summary.avg_prob_2pct != null
                      ? `${(paper.summary.avg_prob_2pct * 100).toFixed(1)}%` : "—"}
                  </td>
                  <td>
                    {paper.summary.avg_realized_return != null ? (
                      <span className={paper.summary.avg_realized_return >= 0 ? "text-green" : "text-red"}>
                        {paper.summary.avg_realized_return >= 0 ? "+" : ""}
                        {(paper.summary.avg_realized_return * 100).toFixed(2)}%
                      </span>
                    ) : "—"}
                  </td>
                  <td>
                    {paper.summary.calibration_error_2pct != null ? (
                      <span className={Math.abs(paper.summary.calibration_error_2pct) <= 0.05 ? "text-green" : "text-red"}>
                        {paper.summary.calibration_error_2pct >= 0 ? "+" : ""}
                        {(paper.summary.calibration_error_2pct * 100).toFixed(1)}%
                      </span>
                    ) : "—"}
                  </td>
                </tr>
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
