import { loadApi } from "@/lib/server-api";
import Link from "next/link";

export default async function HomePage() {
  const [stocksResult, strategiesResult, paperResult, killSwitchResult] = await Promise.all([
    loadApi<any[]>("/stocks"),
    loadApi<any[]>("/strategies?status=promoted"),
    loadApi<any>("/weekly-picks/paper?limit=8"),
    loadApi<any>("/research/kill-switch/status"),
  ]);

  const stocks = stocksResult.data ?? [];
  const strategies = strategiesResult.data ?? [];
  const paper = paperResult.data;
  const killSwitch = killSwitchResult.data;

  const hitRate = paper?.summary?.hit_rate_2pct;
  const openTrades = paper?.summary?.open ?? 0;
  const closedTrades = paper?.summary?.closed ?? 0;
  const avgReturn = paper?.summary?.avg_realized_return;
  const ksActive = killSwitch?.active ?? false;
  const hasData = closedTrades > 0;

  function pct(v: number | null | undefined, decimals = 1) {
    if (v == null) return "—";
    return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(decimals)}%`;
  }

  return (
    <div>
      {/* Başlık */}
      <h1>Borsa Arastirma Sistemi — Genel Bakis</h1>

      {/* Kill switch uyarısı */}
      {ksActive && (
        <div className="alert alert-danger">
          <b>SISTEM DURDURULDU:</b> Model yeni sinyal uretmiyor.
          {killSwitch?.warnings?.[0]?.reason && <> Sebep: {killSwitch.warnings[0].reason}</>}
          {" "}<Link href="/risk-warnings">Detay icin tiklayin &raquo;</Link>
        </div>
      )}

      {/* Sistemin ne yaptığını açıklayan kutu */}
      <div className="info-box" style={{ marginBottom: "12px" }}>
        <b>Bu sistem ne yapar?</b> — SP500 hisselerini her hafta analiz eder, makine ogrenmesi modelleri ile
        gelecek haftaki fiyat hareketini tahmin eder. Tahminler <b>gercek para ile islem icin degildir</b> —
        sadece arastirma ve test amaclidir. Model gecmis veri uzerinde egitilmis olup gelecegi garanti etmez.
      </div>

      {/* Ana metrik kartları */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "8px", marginBottom: "12px" }}>
        <div className="metric-card">
          <div className="metric-label">Takip Edilen Hisse</div>
          <div className="metric-value" style={{ color: "#003366" }}>{stocks.length}</div>
          <div className="metric-sub">SP500 evreni</div>
        </div>

        <div className="metric-card">
          <div className="metric-label">Onaylanmis Strateji</div>
          <div className="metric-value" style={{ color: strategies.length > 0 ? "#006600" : "#666" }}>
            {strategies.length}
          </div>
          <div className="metric-sub">aktif model</div>
        </div>

        <div className="metric-card">
          <div className="metric-label">Simule Edilen Islem</div>
          <div className="metric-value">{closedTrades}</div>
          <div className="metric-sub">{openTrades} acik bekliyor</div>
        </div>

        <div className="metric-card">
          <div className="metric-label">Basari Orani</div>
          <div
            className="metric-value"
            style={{ color: hitRate == null ? "#666" : hitRate >= 0.45 ? "#006600" : "#cc0000" }}
          >
            {hitRate != null ? `${(hitRate * 100).toFixed(1)}%` : "—"}
          </div>
          <div className="metric-sub">
            {hitRate == null ? "veri yok" : hitRate >= 0.45 ? "iyi seviye (≥%45)" : "yetersiz (<45%)"}
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-label">Ort. Gerceklesen Getiri</div>
          <div
            className="metric-value"
            style={{ color: avgReturn == null ? "#666" : avgReturn >= 0 ? "#006600" : "#cc0000" }}
          >
            {avgReturn != null ? pct(avgReturn, 2) : "—"}
          </div>
          <div className="metric-sub">islem basina</div>
        </div>
      </div>

      {/* Basari oranı açıklaması */}
      {hasData && hitRate != null && (
        <div className={`alert ${hitRate >= 0.45 ? "alert-success" : "alert-warning"}`} style={{ marginBottom: "12px" }}>
          {hitRate >= 0.45 ? (
            <>
              <b>Model iyi calisiyor:</b> Kapatilan {closedTrades} islemin %{(hitRate * 100).toFixed(1)}'i hedef
              kazanima ulasti. Ortalama getiri {pct(avgReturn, 2)}.
            </>
          ) : (
            <>
              <b>Model henuz yeterli performans gostermiyor:</b> Kapatilan {closedTrades} islemin
              yalnizca %{(hitRate * 100).toFixed(1)}'i hedef kazanima ulasti.
              Daha fazla veri birikmesi ve strateji iyilestirmesi gerekiyor.
            </>
          )}
        </div>
      )}

      {!hasData && (
        <div className="alert alert-info" style={{ marginBottom: "12px" }}>
          <b>Sistem yeni baslatildi.</b> Henuz kapanmis islem yok.
          Sinyaller uretmek icin{" "}
          <Link href="/strategy-lab">Strateji Laboratuvari</Link>
          {" "}sayfasindan pipeline baslatabilirsiniz.
        </div>
      )}

      {/* Son paper trade sinyalleri */}
      {paper?.trades && paper.trades.length > 0 && (
        <div className="box" style={{ marginBottom: "12px" }}>
          <div className="box-head">
            Son Simule Edilen Islemler
            <span style={{ fontWeight: "normal", marginLeft: "8px", fontSize: "10px" }}>
              — Model tahminleri gercek fiyatlarla karsilastirilir
            </span>
          </div>
          <div className="box-body" style={{ padding: 0 }}>
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th>Hafta</th>
                  <th>Hisse</th>
                  <th title="Modelin o hissenin 1 haftada en az %2 kazanma olasiligi tahmini">Kazanma Olasiligi</th>
                  <th title="Modelin beklettigi ortalama getiri">Beklenen Getiri</th>
                  <th title="Pozisyon kapandiktan sonra gerceklesen getiri">Gerceklesen</th>
                  <th>Sonuc</th>
                </tr>
              </thead>
              <tbody>
                {paper.trades.slice(0, 8).map((t: any, i: number) => (
                  <tr key={i} className={t.hit_2pct === true ? "highlight" : ""}>
                    <td style={{ fontFamily: "monospace", fontSize: "10px" }}>{t.week_starting}</td>
                    <td>
                      <Link href={`/stocks/${t.ticker}`}><b className="col-ticker">{t.ticker}</b></Link>
                      {t.confidence === "high" && (
                        <> <span className="badge badge-success">YUKSEK GUVEN</span></>
                      )}
                    </td>
                    <td>
                      {t.prob_2pct != null ? (
                        <span className={t.prob_2pct >= 0.6 ? "text-green" : ""}>
                          %{(t.prob_2pct * 100).toFixed(0)}
                          <span style={{ fontSize: "9px", color: "#666", marginLeft: "3px" }}>
                            ({t.prob_2pct >= 0.65 ? "yuksek" : t.prob_2pct >= 0.5 ? "orta" : "dusuk"})
                          </span>
                        </span>
                      ) : "—"}
                    </td>
                    <td className={t.expected_return != null ? (t.expected_return >= 0 ? "text-green" : "text-red") : ""}>
                      {pct(t.expected_return, 1)}
                    </td>
                    <td className={t.realized_return != null ? (t.realized_return >= 0 ? "text-green" : "text-red") : ""}>
                      {t.status === "open" ? (
                        <span className="text-muted">acik</span>
                      ) : pct(t.realized_return, 2)}
                    </td>
                    <td>
                      {t.status === "open" && <span className="badge badge-warning">BEKLIYOR</span>}
                      {t.status === "closed" && t.hit_2pct === true && <span className="badge badge-success">HEDEF TUTTU</span>}
                      {t.status === "closed" && t.hit_2pct === false && <span className="badge badge-danger">HEDEF TUTMADI</span>}
                      {t.status === "pending_data" && <span className="badge badge-info">VERI BEKLENIYOR</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ padding: "4px 8px", background: "#f8f8f8", borderTop: "1px solid #c0c0c0", fontSize: "10px", color: "#666" }}>
            <Link href="/weekly-picks">Tum sinyalleri goster &raquo;</Link>
            {"  ·  "}
            <span title="Bu islemler gercek para ile yapilmamistir. Sadece modelin tahmin kalitesini olcmek icin simule edilmektedir.">
              Bu islemler simule edilmistir, gercek degildir.
            </span>
          </div>
        </div>
      )}

      {/* Hızlı adımlar */}
      <div className="box" style={{ marginBottom: "12px" }}>
        <div className="box-head">Nasil Baslarim?</div>
        <div className="box-body">
          <div className="step-row">
            <div className={`step-item ${strategies.length > 0 ? "done" : "active"}`}>
              <div style={{ fontWeight: "bold" }}>1. Strateji Hazirla</div>
              <div style={{ marginTop: "2px" }}>
                <Link href="/strategy-lab">Strateji Laboratuvari</Link>'nda
                model egit ve backtest yap
              </div>
            </div>
            <div className={`step-item ${paper?.trades?.length > 0 ? "done" : strategies.length > 0 ? "active" : ""}`}>
              <div style={{ fontWeight: "bold" }}>2. Sinyalleri Gozlemle</div>
              <div style={{ marginTop: "2px" }}>
                <Link href="/weekly-picks">Haftalik sinyalleri</Link> takip et,
                modelin tahminlerini gerceklesmeyle karsilastir
              </div>
            </div>
            <div className={`step-item ${hasData && hitRate != null && hitRate >= 0.45 ? "done" : ""}`}>
              <div style={{ fontWeight: "bold" }}>3. Performansi Degerlendir</div>
              <div style={{ marginTop: "2px" }}>
                <Link href="/model-comparison">Model karsilastirma</Link> ve{" "}
                <Link href="/research/calibration">tahmin guvenilirligi</Link>ni incele
              </div>
            </div>
            <div className="step-item">
              <div style={{ fontWeight: "bold" }}>4. Riskleri Izle</div>
              <div style={{ marginTop: "2px" }}>
                <Link href="/risk-warnings">Risk uyarilari</Link> sayfasini duzenli kontrol et
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Hisse evreni */}
      <div className="box">
        <div className="box-head">
          Takip Edilen Hisseler ({stocks.length} hisse)
          <span style={{ fontWeight: "normal", marginLeft: "8px", fontSize: "10px" }}>
            — SP500'den secilmis en likit hisseler
          </span>
        </div>
        <div className="box-body" style={{ padding: 0 }}>
          <table className="data-table" style={{ marginBottom: 0 }}>
            <thead>
              <tr>
                <th>Sembol</th>
                <th>Sirket Adi</th>
                <th>Sektor</th>
                <th>Arastir</th>
              </tr>
            </thead>
            <tbody>
              {stocks.slice(0, 20).map((s: any) => (
                <tr key={s.ticker}>
                  <td><b><Link href={`/stocks/${s.ticker}`} className="col-ticker">{s.ticker}</Link></b></td>
                  <td>{s.name}</td>
                  <td style={{ color: "#336699", fontSize: "10px" }}>{s.sector}</td>
                  <td><Link href={`/stocks/${s.ticker}`}>Grafik & Veri &raquo;</Link></td>
                </tr>
              ))}
              {stocks.length > 20 && (
                <tr>
                  <td colSpan={4} style={{ color: "#666", fontStyle: "italic" }}>
                    + {stocks.length - 20} hisse daha — <Link href="/stocks">Tamamini goster</Link>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Uyarı notu */}
      <div style={{
        textAlign: "center", padding: "6px", background: "#e8f0f8",
        border: "1px solid #c0c0c0", fontSize: "10px",
        fontFamily: "Tahoma,sans-serif", color: "#666", marginTop: "8px",
      }}>
        Borsa Research Engine v1.0 &nbsp;|&nbsp;
        Bu sistem yalnizca arastirma amaclidir — <b>yatirim tavsiyesi degildir</b> &nbsp;|&nbsp;
        <Link href="/admin">Sistem Yonetimi</Link>
      </div>
    </div>
  );
}
