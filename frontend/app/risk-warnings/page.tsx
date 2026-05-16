import { loadApi } from "@/lib/server-api";
import Link from "next/link";

export default async function RiskWarningsPage() {
  const [warningsResult, killSwitchResult] = await Promise.all([
    loadApi<any>("/research/risk-warnings"),
    loadApi<any>("/research/kill-switch/status"),
  ]);

  const data = warningsResult.data ?? { warnings: [], count: 0 };
  const ks = killSwitchResult.data;
  const ksActive = ks?.active ?? false;

  const highCount = data.warnings?.filter((w: any) => w.severity === "high").length ?? 0;
  const medCount = data.warnings?.filter((w: any) => w.severity === "medium").length ?? 0;
  const lowCount = data.warnings?.filter((w: any) => w.severity === "low").length ?? 0;

  return (
    <div>
      <h1>Risk Uyarilari ve Sistem Durumu</h1>

      <div className="info-box" style={{ marginBottom: "12px" }}>
        <b>Bu sayfa ne gosteriyor?</b> — Sistem kendi kendini otomatik olarak denetliyor.
        Model performansi duseerse, veri kalitesi bozulursa ya da tahminler tutarsizlasirsa
        burada uyari cikiyor. <b>Kirmizi uyari varsa</b> yeni sinyallere guvenilmemeli,
        <b> yesil durumda</b> sistem normal calisiyor demektir.
      </div>

      {/* Kill switch durumu */}
      {ksActive ? (
        <div className="alert alert-danger" style={{ marginBottom: "12px" }}>
          <b>SISTEM DURDURULDU:</b> Model yeni sinyal uretmiyor.
          {ks?.warnings?.[0]?.reason && (
            <> Sebep: {ks.warnings[0].reason}</>
          )}
          <br />
          <span style={{ fontSize: "10px" }}>
            Sistem durdurulunca eski sinyallere guvenilmez. Arastirmaci manuel inceleme yapip
            sistemi yeniden baslatmalidir.
          </span>
        </div>
      ) : (
        <div className="alert alert-success" style={{ marginBottom: "12px" }}>
          <b>Sistem aktif:</b> Kill switch devrede degil. Model normal sekilde sinyal uretiyor.
        </div>
      )}

      {/* Ozet sayaclari */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "8px", marginBottom: "12px" }}>
        <div className="metric-card">
          <div className="metric-label">Toplam Uyari</div>
          <div
            className="metric-value"
            style={{ color: data.count > 0 ? "#cc0000" : "#006600" }}
          >
            {data.count ?? 0}
          </div>
          <div className="metric-sub">aktif uyari</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Kritik (Yuksek)</div>
          <div className="metric-value" style={{ color: highCount > 0 ? "#cc0000" : "#006600" }}>
            {highCount}
          </div>
          <div className="metric-sub">hemen incelenmeli</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Orta</div>
          <div className="metric-value" style={{ color: medCount > 0 ? "#cc6600" : "#006600" }}>
            {medCount}
          </div>
          <div className="metric-sub">izlenmeli</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Dusuk</div>
          <div className="metric-value" style={{ color: "#666" }}>
            {lowCount}
          </div>
          <div className="metric-sub">bilgi amacli</div>
        </div>
      </div>

      {/* Uyari listesi */}
      {data.count === 0 ? (
        <div className="alert alert-success">
          <b>Aktif risk uyarisi bulunmuyor.</b> Tum stratejiler kabul edilebilir sinirlar icinde calisiyor.
          Sistem duzenli olarak kendini denetlemeye devam ediyor.
        </div>
      ) : (
        <div className="box" style={{ marginBottom: "12px" }}>
          <div className="box-head">
            Aktif Uyarilar ({data.count} adet)
            <span style={{ fontWeight: "normal", marginLeft: "8px", fontSize: "10px" }}>
              — Otomatik tespit edilmistir
            </span>
          </div>
          <div className="box-body" style={{ padding: 0 }}>
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th>Strateji</th>
                  <th>Onem</th>
                  <th>Ne Demek?</th>
                  <th>Uyari Aciklamasi</th>
                </tr>
              </thead>
              <tbody>
                {data.warnings?.map((w: any, i: number) => (
                  <tr key={i}>
                    <td>
                      {w.strategy_id ? (
                        <Link href={`/strategies/${w.strategy_id}`}>Strateji #{w.strategy_id}</Link>
                      ) : (
                        <span className="text-muted">Sistem geneli</span>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${
                        w.severity === "high" ? "badge-danger" :
                        w.severity === "medium" ? "badge-warning" : "badge-info"
                      }`}>
                        {w.severity === "high" ? "KRITIK" :
                         w.severity === "medium" ? "ORTA" : "DUSUK"}
                      </span>
                    </td>
                    <td style={{ fontSize: "10px", color: "#555" }}>
                      {w.severity === "high"
                        ? "Bu stratejiye guvenilmez, yeni sinyal alinmamali"
                        : w.severity === "medium"
                        ? "Performans dusme riski var, izlenmelidir"
                        : "Bilgi amacli, acil eylem gerekmez"}
                    </td>
                    <td style={{ fontSize: "11px" }}>{w.warning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Ne yapilmali rehberi */}
      <div className="box">
        <div className="box-head">Uyari Durumunda Ne Yapilmali?</div>
        <div className="box-body">
          <div className="step-row">
            <div className="step-item" style={{ textAlign: "left" }}>
              <div style={{ fontWeight: "bold", marginBottom: "3px" }}>Kritik Uyari</div>
              <div style={{ fontSize: "10px" }}>
                Yeni sinyallere guvenme. Modeli yeniden test et,
                veri kalitesini kontrol et. Sistemi durdur.
              </div>
            </div>
            <div className="step-item" style={{ textAlign: "left" }}>
              <div style={{ fontWeight: "bold", marginBottom: "3px" }}>Orta Uyari</div>
              <div style={{ fontSize: "10px" }}>
                Sinyalleri dikkatli yorumla. Ek dogrulama yap.{" "}
                <Link href="/research/calibration">Kalibrasyon</Link>
                {" "}ve <Link href="/model-comparison">model karsilastirma</Link>naya bak.
              </div>
            </div>
            <div className="step-item" style={{ textAlign: "left" }}>
              <div style={{ fontWeight: "bold", marginBottom: "3px" }}>Dusuk Uyari</div>
              <div style={{ fontSize: "10px" }}>
                Normal calisma devam eder.
                Uyariyi kayit altina al, zamanla izle.
              </div>
            </div>
            <div className="step-item" style={{ textAlign: "left" }}>
              <div style={{ fontWeight: "bold", marginBottom: "3px" }}>Uyari Yok</div>
              <div style={{ fontSize: "10px" }}>
                Sistem saglikh calisiyor.{" "}
                <Link href="/weekly-picks">Sinyallere</Link> bakabilirsin.
              </div>
            </div>
          </div>
        </div>
      </div>

      <div style={{
        textAlign: "center", padding: "6px", background: "#e8f0f8",
        border: "1px solid #c0c0c0", fontSize: "10px",
        fontFamily: "Tahoma,sans-serif", color: "#666", marginTop: "8px",
      }}>
        Risk uyarilari otomatik hesaplanir &nbsp;|&nbsp;
        Bu sistem yalnizca arastirma amaclidir — <b>yatirim tavsiyesi degildir</b>
      </div>
    </div>
  );
}
