import { api } from "@/lib/api";

export default async function DataQualityPage() {
  const report = await api.get<any>("/data-quality").catch(() => null);
  if (!report) return (
    <div className="alert alert-danger">
      ❌ Veri kalitesi raporu alınamadı. API çalışıyor mu?
    </div>
  );

  return (
    <div>
      <h1>📋 Veri Kalitesi Raporu</h1>

      <div className="info-box" style={{ marginBottom: "12px" }}>
        <b>Neden onemli?</b> Modelin tahmini ancak kullandigi veri kadar guvenilirdir.
        Eksik fiyat, eski makro seri veya az feature varsa sinyal kaliteli gorunse bile karar zayif olabilir.
        Sinyallere bakmadan once bu sayfada "TAMAM" durumunu kontrol et.
      </div>

      <div className="alert alert-info" style={{ marginBottom: "12px" }}>
        <b>Pratik kural:</b> Eksik veri varsa once Strategy Laboratuvari'ndan pipeline'i calistir.
        Veri tamamlanmadan uretilen backtest ve sinyaller arastirma icin bile temkinli okunmalidir.
      </div>

      <table className="data-table" style={{ width: "400px", marginBottom: "12px" }}>
        <thead>
          <tr><th>Metrik</th><th>Değer</th></tr>
        </thead>
        <tbody>
          <tr><td>Toplam Hisse</td><td><b>{report.total_stocks}</b></td></tr>
          <tr>
            <td>Verisi Olan Hisse</td>
            <td>
              <span className={report.stocks_with_data === report.total_stocks ? "text-green" : "text-red"}>
                <b>{report.stocks_with_data}</b>
              </span>
            </td>
          </tr>
          <tr>
            <td>Eksik Veri</td>
            <td>
              <span className={(report.total_stocks - report.stocks_with_data) === 0 ? "text-green" : "text-red"}>
                <b>{report.total_stocks - report.stocks_with_data}</b>
              </span>
            </td>
          </tr>
        </tbody>
      </table>

      {report.macro_freshness && Object.keys(report.macro_freshness).length > 0 && (
        <div className="box" style={{ marginBottom: "12px" }}>
          <div className="box-head">📡 Makro Veri Tazeliği</div>
          <div className="box-body" style={{ padding: 0 }}>
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr><th>Gösterge</th><th>Son Güncelleme</th></tr>
              </thead>
              <tbody>
                {Object.entries(report.macro_freshness).map(([code, date]: any) => (
                  <tr key={code}>
                    <td><b>{code}</b></td>
                    <td style={{ fontFamily: "monospace", fontSize: "10px" }}>{date}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="box">
        <div className="box-head">📦 Hisse Bazlı Veri Durumu</div>
        <div className="box-body" style={{ padding: 0 }}>
          <table className="data-table" style={{ marginBottom: 0 }}>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Günlük Fiyat</th>
                <th>Haftalık Fiyat</th>
                <th>Feature Satır</th>
                <th>Son Hafta</th>
                <th>Durum</th>
              </tr>
            </thead>
            <tbody>
              {report.stocks?.map((s: any) => (
                <tr key={s.ticker}>
                  <td><b><a href={`/stocks/${s.ticker}`}>{s.ticker}</a></b></td>
                  <td style={{ fontFamily: "monospace" }}>{s.daily_price_rows?.toLocaleString()}</td>
                  <td style={{ fontFamily: "monospace" }}>{s.weekly_price_rows?.toLocaleString()}</td>
                  <td style={{ fontFamily: "monospace" }}>{s.feature_rows?.toLocaleString()}</td>
                  <td style={{ fontFamily: "monospace", fontSize: "10px" }}>{s.latest_week ?? "—"}</td>
                  <td>
                    <span className={`badge ${s.status === "ok" ? "badge-success" : "badge-danger"}`}>
                      {s.status === "ok" ? "TAMAM" : "EKSİK"}
                    </span>
                  </td>
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
        Bu sistem yalnızca araştırma amaçlıdır, yatırım tavsiyesi değildir
      </div>
    </div>
  );
}
