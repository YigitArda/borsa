"use client";

import { useState } from "react";
import { api } from "@/lib/api";

type TrinityScore = {
  ticker: string;
  rank: number;
  combined_score: number;
  total_score: number;
  fisher_curvature: number;
  shannon_entropy: number;
  lz_complexity: number;
  regime: string;
  pre_explosion: boolean;
};

type TrinityResponse = {
  results: TrinityScore[];
  queued_tickers: string[];
  created_tickers: string[];
  insufficient_price_tickers: string[];
  ingest_task_id: string | null;
  message: string | null;
};

const DEMO_TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "V", "UNH"];

export default function TrinityScreenerPage() {
  const [tickers, setTickers] = useState<string>(DEMO_TICKERS.join(", "));
  const [preExplosionOnly, setPreExplosionOnly] = useState(false);
  const [scores, setScores] = useState<TrinityScore[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [screened, setScreened] = useState(false);
  const [queued, setQueued] = useState<TrinityResponse | null>(null);

  async function runScreener() {
    const tickerList = tickers
      .split(/[,\s]+/)
      .map((t) => t.trim().toUpperCase())
      .filter(Boolean);

    if (tickerList.length === 0) {
      setError("En az bir ticker yaz.");
      return;
    }

    setLoading(true);
    setError(null);
    setScores([]);
    setQueued(null);

    try {
      const data = await api.post<TrinityResponse | TrinityScore[]>("/scientific/trinity/screen", {
        tickers: tickerList,
        pre_explosion_only: preExplosionOnly,
        lookback_days: 400,
      });
      const response = Array.isArray(data)
        ? { results: data, queued_tickers: [], created_tickers: [], insufficient_price_tickers: [], ingest_task_id: null, message: null }
        : data;
      const sorted = [...(response.results ?? [])].sort((a, b) => b.combined_score - a.combined_score);
      setScores(sorted);
      setQueued(response);
      setScreened(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Tarama basarisiz.");
    } finally {
      setLoading(false);
    }
  }

  function scoreBadge(score: number) {
    if (score >= 0.7) return "badge-success";
    if (score >= 0.4) return "badge-warning";
    return "badge-danger";
  }

  const preExplosion = scores.filter((s) => s.pre_explosion);

  return (
    <div style={{ maxWidth: "1100px", margin: "0 auto" }}>
      <h1>Trinity Screener</h1>

      <div className="info-box" style={{ marginBottom: "12px" }}>
        <b>Bu tarama ne yapar?</b> Yazdigin ticker'larin son fiyat/hacim gecmisini veritabanindan ceker,
        getiri serisini hesaplar ve hareket oncesi duzen/sikisma sinyali arar.
        Bu ekran hizli eleme aracidir; sonuc tek basina alim karari degildir.
      </div>

      <div className="alert alert-info" style={{ marginBottom: "12px" }}>
        <b>Isleyis:</b> Ticker yazarsin, backend `stocks` ve `prices_daily` tablolarindan fiyatlari bulur,
        en az 60 gunluk kapanis verisi olanlari skorlar. Pre-explosion filtresi aciksa yaklasik 252 gunluk
        fiyat/hacim gecmisi gerekir.
      </div>

      {error && <div className="alert alert-danger">{error}</div>}

      {queued?.queued_tickers?.length ? (
        <div className="alert alert-warning" style={{ marginBottom: "12px" }}>
          <b>Veri hazirlaniyor:</b> {queued.queued_tickers.join(", ")} icin fiyat verisi eksik oldugu icin
          otomatik fiyat guncelleme kuyruga alindi.
          {queued.ingest_task_id && <> Task: <span style={{ fontFamily: "monospace" }}>{queued.ingest_task_id}</span>.</>}
          {" "}Birkac dakika sonra taramayi tekrar calistir.
        </div>
      ) : null}

      <div className="box">
        <div className="box-head">Tarama Evreni</div>
        <div className="box-body">
          <label style={{ fontSize: "11px", display: "block", marginBottom: "6px" }}>
            Ticker listesi (virgul veya boslukla ayir). Ornek: AAPL MSFT NVDA
            <textarea
              value={tickers}
              onChange={(e) => setTickers(e.target.value)}
              rows={3}
              style={{ display: "block", width: "100%", marginTop: "4px", fontFamily: "monospace", fontSize: "11px" }}
            />
          </label>
          <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
            <label style={{ display: "inline-flex", alignItems: "center", gap: "4px", fontSize: "11px" }}>
              <input
                type="checkbox"
                checked={preExplosionOnly}
                onChange={(e) => setPreExplosionOnly(e.target.checked)}
              />
              Sadece pre-explosion adaylari
            </label>
            <button onClick={runScreener} disabled={loading}>
              {loading ? "Taraniyor..." : "Taramayi Baslat"}
            </button>
          </div>
        </div>
      </div>

      {screened && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "8px", margin: "10px 0" }}>
            <div className="box" style={{ marginBottom: 0 }}>
              <div className="box-head">Taranan</div>
              <div className="box-body"><div style={{ fontSize: "22px", fontWeight: "bold" }}>{scores.length}</div></div>
            </div>
            <div className="box" style={{ marginBottom: 0 }}>
              <div className="box-head">Guclu Skor</div>
              <div className="box-body">
                <div style={{ fontSize: "22px", fontWeight: "bold", color: "#006600" }}>
                  {scores.filter((s) => s.combined_score >= 0.7).length}
                </div>
              </div>
            </div>
            <div className="box" style={{ marginBottom: 0 }}>
              <div className="box-head">Pre-Explosion</div>
              <div className="box-body">
                <div style={{ fontSize: "22px", fontWeight: "bold", color: "#cc6600" }}>
                  {preExplosion.length}
                </div>
              </div>
            </div>
            <div className="box" style={{ marginBottom: 0 }}>
              <div className="box-head">Ortalama Skor</div>
              <div className="box-body">
                <div style={{ fontSize: "22px", fontWeight: "bold" }}>
                  {scores.length > 0
                    ? (scores.reduce((s, x) => s + x.combined_score, 0) / scores.length).toFixed(3)
                    : "-"}
                </div>
              </div>
            </div>
          </div>

          {preExplosion.length > 0 && (
            <div className="alert alert-warning" style={{ marginBottom: "10px" }}>
              <b>Pre-explosion adaylari:</b>{" "}
              {preExplosion.map((s) => s.ticker).join(", ")}. Bu, fiyat/hacim yapisinda hareket oncesi
              sikisma ihtimali oldugunu soyler; detay sayfasinda dogrulanmalidir.
            </div>
          )}

          <div className="box">
            <div className="box-head">Tarama Sonuclari</div>
            <div className="box-body" style={{ padding: 0 }}>
              <table className="data-table" style={{ marginBottom: 0 }}>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Ticker</th>
                    <th>Toplam Skor</th>
                    <th>Entropy</th>
                    <th>Complexity</th>
                    <th>Curvature</th>
                    <th>Rejim</th>
                    <th>Pre-Explosion</th>
                  </tr>
                </thead>
                <tbody>
                  {scores.length === 0 ? (
                    <tr>
                      <td colSpan={8} style={{ color: "#666" }}>
                        Sonuc yok. En az 60 gunluk fiyat verisi olmayan ticker'lar otomatik fiyat guncelleme
                        kuyruguna alindiysa birkac dakika sonra tekrar tara.
                      </td>
                    </tr>
                  ) : (
                    scores.map((s, i) => (
                      <tr key={s.ticker} className={s.pre_explosion ? "highlight" : ""}>
                        <td style={{ color: "#666" }}>{s.rank || i + 1}</td>
                        <td><b style={{ fontFamily: "monospace" }}>{s.ticker}</b></td>
                        <td>
                          <span className={`badge ${scoreBadge(s.combined_score)}`}>
                            {s.combined_score.toFixed(3)}
                          </span>
                        </td>
                        <td className={s.shannon_entropy <= 0.4 ? "text-green" : s.shannon_entropy > 0.7 ? "text-red" : ""}>
                          {s.shannon_entropy.toFixed(3)}
                        </td>
                        <td className={s.lz_complexity <= 0.3 ? "text-green" : s.lz_complexity > 0.6 ? "text-red" : ""}>
                          {s.lz_complexity.toFixed(3)}
                        </td>
                        <td>{s.fisher_curvature.toFixed(3)}</td>
                        <td>
                          <span className={`badge ${s.regime === "TREND" || s.regime === "SQUEEZE" ? "badge-success" : s.regime === "CHAOS" ? "badge-danger" : "badge-info"}`}>
                            {s.regime}
                          </span>
                        </td>
                        <td>
                          {s.pre_explosion ? (
                            <span className="badge badge-warning">EVET</span>
                          ) : (
                            <span style={{ color: "#666", fontSize: "10px" }}>-</span>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="box" style={{ marginTop: "10px" }}>
            <div className="box-head">Trinity Skorlari Ne Demek?</div>
            <div className="box-body" style={{ fontSize: "11px" }}>
              <div><b>Entropy:</b> Getiriler ne kadar daginik? Dusuk deger daha duzenli fiyat davranisi demektir.</div>
              <div><b>Complexity:</b> Fiyat yonleri ne kadar karmasik? Dusuk deger daha okunabilir pattern demektir.</div>
              <div><b>Curvature:</b> Getiri dagilimi rejim degisimi sinyali veriyor mu?</div>
              <div><b>Pre-Explosion:</b> Guclu skor + 52 hafta araliginda uygun konum + hacim teyidi.</div>
              <div style={{ marginTop: "6px", color: "#666" }}>
                Not: Yeni ticker icin once fiyat pipeline'i calismis olmalidir; aksi halde veritabaninda skorlanacak veri bulunmaz.
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
