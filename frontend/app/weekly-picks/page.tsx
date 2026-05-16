import { api } from "@/lib/api";
import Link from "next/link";

export default async function WeeklyPicksPage() {
  const picks = await api.get<any[]>("/weekly-picks").catch(() => []);
  const paper = await api.get<any>("/weekly-picks/paper?limit=20").catch(() => null);

  function pct(v: number | null | undefined, decimals = 1) {
    if (v == null) return "—";
    return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(decimals)}%`;
  }

  const summary = paper?.summary;
  const hitRate = summary?.hit_rate_2pct;

  return (
    <div>
      <h1>Bu Haftanin Sinyalleri</h1>

      <div className="info-box" style={{ marginBottom: "12px" }}>
        <b>Bu sayfa ne gosteriyor?</b> — Model, SP500 hisselerini analiz ederek "bu hisse gelecek haftada
        en az %2 kazanir mi?" sorusuna cevap ariyor. <b>Kazanma Olasiligi</b> yuksek olan hisseler one cikiyor.
        Bu tahminler <b>gercek yatirim tavsiyesi degildir</b> — modelin ne kadar iyi calistigini olcmek icin kullanilir.
        Her Cuma aksami guncellenir.
      </div>

      {picks.length === 0 ? (
        <div className="alert alert-warning">
          <b>Bu hafta icin sinyal bulunamadi.</b> Sinyal uretmek icin{" "}
          <Link href="/strategy-lab">Strateji Laboratuvari</Link>
          {" "}sayfasindan pipeline baslatabilirsiniz.
        </div>
      ) : (
        <div className="box" style={{ marginBottom: "12px" }}>
          <div className="box-head">
            Bu Haftanin Onerileri
            {picks[0]?.week_starting && (
              <span style={{ fontWeight: "normal", marginLeft: "8px", fontSize: "10px" }}>
                — Hafta baslangici: {picks[0].week_starting}
              </span>
            )}
          </div>
          <div className="box-body" style={{ padding: 0 }}>
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Hisse</th>
                  <th>Sirket</th>
                  <th>Sektor</th>
                  <th title="Modelin bu hissenin 1 haftada en az %2 kazanma olasiligi tahmini — yuksek oldukca iyi">
                    Kazanma Olasiligi
                  </th>
                  <th title="Modelin bu hissenin 1 haftada en az %2 kaybetme olasiligi tahmini — dusuk oldukca iyi">
                    Kayip Olasiligi
                  </th>
                  <th title="Modelin bekledigi ortalama getiri — pozitif oldukca iyi">
                    Beklenen Getiri
                  </th>
                  <th>Guven Seviyesi</th>
                  <th>Sinyal Ozeti</th>
                </tr>
              </thead>
              <tbody>
                {picks.map((p: any) => (
                  <tr key={p.ticker}>
                    <td style={{ color: "#666" }}>{p.rank}</td>
                    <td>
                      <b><Link href={`/stocks/${p.ticker}`} className="col-ticker">{p.ticker}</Link></b>
                      {p.confidence === "high" && (
                        <> <span className="badge badge-success">YUKSEK GUVEN</span></>
                      )}
                    </td>
                    <td style={{ fontSize: "10px" }}>{p.name}</td>
                    <td style={{ fontSize: "10px", color: "#336699" }}>{p.sector}</td>
                    <td>
                      <span className={p.prob_2pct >= 0.65 ? "text-green" : ""}>
                        {p.prob_2pct != null ? (
                          <>
                            %{(p.prob_2pct * 100).toFixed(0)}
                            <span style={{ fontSize: "9px", color: "#666", marginLeft: "3px" }}>
                              ({p.prob_2pct >= 0.65 ? "yuksek" : p.prob_2pct >= 0.5 ? "orta" : "dusuk"})
                            </span>
                          </>
                        ) : "—"}
                      </span>
                    </td>
                    <td>
                      <span className={p.prob_loss_2pct >= 0.3 ? "text-red" : "text-muted"}>
                        {p.prob_loss_2pct != null ? `%${(p.prob_loss_2pct * 100).toFixed(0)}` : "—"}
                      </span>
                    </td>
                    <td className={p.expected_return != null ? (p.expected_return >= 0 ? "text-green" : "text-red") : ""}>
                      {pct(p.expected_return, 2)}
                    </td>
                    <td>
                      <span className={`badge ${
                        p.confidence === "high" ? "badge-success" :
                        p.confidence === "medium" ? "badge-warning" : "badge-info"
                      }`}>
                        {p.confidence === "high" ? "YUKSEK" :
                         p.confidence === "medium" ? "ORTA" : "DUSUK"}
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
          <div style={{ padding: "4px 8px", background: "#f8f8f8", borderTop: "1px solid #c0c0c0", fontSize: "10px", color: "#666" }}>
            <b>Nasil okunur?</b> Kazanma Olasiligi %65+ olan hisseler en guclu sinyallerdir.
            Gerceklesmeler asagidaki "Simule Edilen Islemler" tablosunda izlenir.
          </div>
        </div>
      )}

      {/* Ozet metrik kartlari */}
      {summary && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "8px", marginBottom: "12px" }}>
          <div className="metric-card">
            <div className="metric-label">Toplam Islem</div>
            <div className="metric-value">{summary.total ?? 0}</div>
            <div className="metric-sub">{summary.open ?? 0} acik, {summary.closed ?? 0} kapali</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Basari Orani</div>
            <div
              className="metric-value"
              style={{ color: hitRate == null ? "#666" : hitRate >= 0.45 ? "#006600" : "#cc0000" }}
            >
              {hitRate != null ? `%${(hitRate * 100).toFixed(1)}` : "—"}
            </div>
            <div className="metric-sub">
              {hitRate == null ? "veri yok" : hitRate >= 0.45 ? "iyi seviye" : "yetersiz"}
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Ort. Kazanma Olasiligi</div>
            <div className="metric-value" style={{ fontSize: "20px" }}>
              {summary.avg_prob_2pct != null ? `%${(summary.avg_prob_2pct * 100).toFixed(0)}` : "—"}
            </div>
            <div className="metric-sub">model tahmini</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Ort. Gerceklesen Getiri</div>
            <div
              className="metric-value"
              style={{
                fontSize: "20px",
                color: summary.avg_realized_return == null ? "#666"
                  : summary.avg_realized_return >= 0 ? "#006600" : "#cc0000"
              }}
            >
              {pct(summary.avg_realized_return, 2)}
            </div>
            <div className="metric-sub">islem basina</div>
          </div>
        </div>
      )}

      {/* Basari orani yorumu */}
      {hitRate != null && (summary?.closed ?? 0) > 0 && (
        <div className={`alert ${hitRate >= 0.45 ? "alert-success" : "alert-warning"}`} style={{ marginBottom: "12px" }}>
          {hitRate >= 0.45 ? (
            <>
              <b>Model iyi calisiyor:</b> Kapatilan {summary.closed} islemin
              %{(hitRate * 100).toFixed(1)}&apos;i en az %2 kazanima ulasti.
              Ortalama gerceklesen getiri {pct(summary.avg_realized_return, 2)}.
            </>
          ) : (
            <>
              <b>Model henuz yeterli performans gostermiyor:</b> Kapatilan {summary.closed} islemin
              yalnizca %{(hitRate * 100).toFixed(1)}&apos;i hedef kazanima ulasti.
              Daha fazla veri ve strateji iyilestirmesi gerekiyor.
            </>
          )}
        </div>
      )}

      {/* Paper trades gecmisi */}
      {paper?.trades && paper.trades.length > 0 && (
        <div className="box" style={{ marginBottom: "12px" }}>
          <div className="box-head">
            Simule Edilen Islemler
            <span style={{ fontWeight: "normal", marginLeft: "8px", fontSize: "10px" }}>
              — Modelin tahminleri gercek fiyatlarla karsilastirilir
            </span>
          </div>
          <div className="box-body" style={{ padding: 0 }}>
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th>Hafta</th>
                  <th>Hisse</th>
                  <th title="Modelin tahmini kazanma olasiligi">Kazanma Olasiligi</th>
                  <th title="Modelin bekledigi getiri">Beklenen Getiri</th>
                  <th title="Pozisyon kapandiktan sonra gercekten ne oldu">Gerceklesen</th>
                  <th>Sonuc</th>
                </tr>
              </thead>
              <tbody>
                {paper.trades.slice(0, 20).map((t: any, i: number) => (
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
            Sari satir: en az %2 kazanim hedefine ulasan islemler.
            {" "}Bu islemler simule edilmistir — gercek para ile yapilmamistir.
          </div>
        </div>
      )}

      {/* Kalibrasyon bilgisi */}
      {summary?.calibration_error_2pct != null && (
        <div className={`alert ${Math.abs(summary.calibration_error_2pct) <= 0.05 ? "alert-success" : "alert-warning"}`}>
          <b>Tahmin Kalibrasyon Durumu:</b>{" "}
          {Math.abs(summary.calibration_error_2pct) <= 0.05 ? (
            <>Model tahminleri gerceklesmeyle iyi uyusuyor (hata: {pct(summary.calibration_error_2pct, 1)}).</>
          ) : (
            <>
              Model tahminleri gerceklesmeyle {summary.calibration_error_2pct > 0 ? "fazla iyimser" : "fazla kotumser"}{" "}
              (hata: {pct(summary.calibration_error_2pct, 1)}).{" "}
              <Link href="/research/calibration">Detayli kalibrasyon analizi &raquo;</Link>
            </>
          )}
        </div>
      )}

      <div style={{
        textAlign: "center", padding: "6px", background: "#e8f0f8",
        border: "1px solid #c0c0c0", fontSize: "10px",
        fontFamily: "Tahoma,sans-serif", color: "#666", marginTop: "8px",
      }}>
        Bu sistem yalnizca arastirma amaclidir — <b>yatirim tavsiyesi degildir</b>
      </div>
    </div>
  );
}
