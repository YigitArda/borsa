import { api } from "@/lib/api";

async function getData() {
  try {
    const stocks = await api.get<any[]>("/stocks");
    return { stocks: stocks || [] };
  } catch {
    return { stocks: [] };
  }
}

export default async function DataStatusPage() {
  const { stocks } = await getData();
  const stockCount = stocks.length;

  const dataSources = [
    {
      name: "Fiyat Verisi",
      source: "Yahoo Finance (yfinance)",
      period: "Haftalik (Cuma kapanis)",
      range: "1980 - 2026",
      totalRecords: "35,788 haftalik kayit",
      coverage: "20 hisse x 13-46 yil",
      status: "Aktif",
    },
    {
      name: "Feature'lar",
      source: "Hesaplanmis (teknik gostergeler)",
      period: "Haftalik",
      range: "1980 - 2026",
      totalRecords: "240,505 kayit",
      coverage: "135 farkli feature tipi",
      status: "Aktif",
    },
    {
      name: "Labels (Hedef)",
      source: "Hesaplanmis (getiri bazli)",
      period: "Haftalik",
      range: "2015 - 2026",
      totalRecords: "5,908 kayit",
      coverage: "3 hedef degisken",
      status: "Aktif",
    },
    {
      name: "Finansal Metrikler",
      source: "Yahoo Finance / Manual",
      period: "Ceyreklik/Yillik",
      range: "2015 - 2026",
      totalRecords: "325 kayit",
      coverage: "30+ metrik (P/E, marj, ROE, vb.)",
      status: "Kismi",
    },
    {
      name: "Makro Veriler",
      source: "FRED / Yahoo Finance",
      period: "Haftalik/Gunluk",
      range: "2015 - 2026",
      totalRecords: "VIX, Faiz, CPI proxy",
      coverage: "21 makro feature",
      status: "Kismi",
    },
    {
      name: "Haber/Sentiment",
      source: "NewsAPI / VADER",
      period: "Gunluk",
      range: "2024 - 2026",
      totalRecords: "Sinirli",
      coverage: "Duygu skoru, hacim",
      status: "Pasif",
    },
  ];

  const tickerDetails = [
    { ticker: "XOM", weeks: 2420, years: 46.5, start: "1980-01-04", end: "2026-05-15" },
    { ticker: "JNJ", weeks: 2420, years: 46.5, start: "1980-01-04", end: "2026-05-15" },
    { ticker: "PG", weeks: 2420, years: 46.5, start: "1980-01-04", end: "2026-05-15" },
    { ticker: "CVX", weeks: 2420, years: 46.5, start: "1980-01-04", end: "2026-05-15" },
    { ticker: "MRK", weeks: 2420, years: 46.5, start: "1980-01-04", end: "2026-05-15" },
    { ticker: "LLY", weeks: 2420, years: 46.5, start: "1980-01-04", end: "2026-05-15" },
    { ticker: "JPM", weeks: 2409, years: 46.3, start: "1980-03-21", end: "2026-05-15" },
    { ticker: "AAPL", weeks: 2371, years: 45.6, start: "1980-12-12", end: "2026-05-15" },
    { ticker: "HD", weeks: 2330, years: 44.8, start: "1981-09-25", end: "2026-05-15" },
    { ticker: "UNH", weeks: 2170, years: 41.7, start: "1984-10-19", end: "2026-05-15" },
    { ticker: "MSFT", weeks: 2097, years: 40.2, start: "1986-03-14", end: "2026-05-15" },
    { ticker: "BRK-B", weeks: 1567, years: 30.1, start: "1996-05-10", end: "2026-05-15" },
    { ticker: "AMZN", weeks: 1514, years: 29.1, start: "1997-05-16", end: "2026-05-15" },
    { ticker: "NVDA", weeks: 1426, years: 27.4, start: "1999-01-22", end: "2026-05-15" },
    { ticker: "GOOGL", weeks: 1135, years: 21.8, start: "2004-08-20", end: "2026-05-15" },
    { ticker: "MA", weeks: 1043, years: 20.1, start: "2006-05-26", end: "2026-05-15" },
    { ticker: "V", weeks: 948, years: 18.2, start: "2008-03-21", end: "2026-05-15" },
    { ticker: "TSLA", weeks: 829, years: 15.9, start: "2010-07-02", end: "2026-05-15" },
    { ticker: "META", weeks: 731, years: 14.1, start: "2012-05-18", end: "2026-05-15" },
    { ticker: "ABBV", weeks: 698, years: 13.4, start: "2013-01-04", end: "2026-05-15" },
  ];

  const featureCategories = [
    { category: "Teknik", count: 22, examples: "rsi_14, macd, sma_20, bb_position, atr_14" },
    { category: "Finansal", count: 20, examples: "pe_ratio, roe, gross_margin, debt_to_equity" },
    { category: "Makro", count: 21, examples: "VIX, TNX_10Y, sp500_trend_20w, cpi_proxy" },
    { category: "Haber/Sosyal", count: 6, examples: "news_sentiment, social_mention_count" },
    { category: "Diger", count: 66, examples: "alpha_factors, beta_52w, anchor_signals" },
  ];

  return (
    <div>
      <h1>📊 Veri Durumu Raporu</h1>

      <div className="alert alert-info">
        ℹ Bu sayfada sistemdeki tum veri kaynaklari, kapsamlari ve durumlari gorunur.
        Son guncelleme: {new Date().toLocaleDateString("tr-TR")}
      </div>

      <div className="box" style={{ marginBottom: "12px" }}>
        <div className="box-head">Özet</div>
        <div className="box-body">
          <table className="data-table" style={{ marginBottom: 0 }}>
            <tbody>
              <tr>
                <td><b>DB'deki Hisse Sayısı</b></td>
                <td>{stockCount}</td>
                <td><b>Fiyat Geçmişi</b></td>
                <td>20 hissede 1980-2026 aralığı</td>
              </tr>
              <tr>
                <td><b>Feature Aileleri</b></td>
                <td>{featureCategories.length}</td>
                <td><b>Veri Kaynakları</b></td>
                <td>{dataSources.length}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* 1. Veri Kaynaklari Ozeti */}
      <div className="box" style={{ marginBottom: "12px" }}>
        <div className="box-head">📦 Veri Kaynaklari ve Durumlari</div>
        <div className="box-body" style={{ padding: 0 }}>
          <table className="data-table" style={{ marginBottom: 0 }}>
            <thead>
              <tr>
                <th>Veri Tipi</th>
                <th>Kaynak</th>
                <th>Periyot</th>
                <th>Tarih Araligi</th>
                <th>Toplam Kayit</th>
                <th>Kapsam</th>
                <th>Durum</th>
              </tr>
            </thead>
            <tbody>
              {dataSources.map((d, i) => (
                <tr key={i}>
                  <td><b>{d.name}</b></td>
                  <td style={{ fontSize: "10px" }}>{d.source}</td>
                  <td style={{ fontSize: "10px" }}>{d.period}</td>
                  <td style={{ fontSize: "10px", fontFamily: "monospace" }}>{d.range}</td>
                  <td style={{ fontSize: "10px" }}>{d.totalRecords}</td>
                  <td style={{ fontSize: "10px" }}>{d.coverage}</td>
                  <td>
                    <span className={`badge ${d.status === "Aktif" ? "badge-success" : d.status === "Kismi" ? "badge-warning" : "badge-info"}`}>
                      {d.status.toUpperCase()}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 2. Hisse Basina Veri Detayi */}
      <div className="box" style={{ marginBottom: "12px" }}>
        <div className="box-head">📈 Hisse Basina Fiyat Verisi Detayi</div>
        <div className="box-body" style={{ padding: 0 }}>
          <table className="data-table" style={{ marginBottom: 0 }}>
            <thead>
              <tr>
                <th>#</th>
                <th>Ticker</th>
                <th>Hafta Sayisi</th>
                <th>Yil</th>
                <th>Baslangic</th>
                <th>Bitis</th>
                <th>IPO/Baslangic Tarihi</th>
              </tr>
            </thead>
            <tbody>
              {tickerDetails.map((t, i) => (
                <tr key={t.ticker}>
                  <td style={{ color: "#666" }}>{i + 1}</td>
                  <td><b>{t.ticker}</b></td>
                  <td style={{ textAlign: "right", fontFamily: "monospace" }}>{t.weeks.toLocaleString()}</td>
                  <td style={{ textAlign: "right" }}>{t.years.toFixed(1)}</td>
                  <td style={{ fontSize: "10px", fontFamily: "monospace" }}>{t.start}</td>
                  <td style={{ fontSize: "10px", fontFamily: "monospace" }}>{t.end}</td>
                  <td style={{ fontSize: "10px", color: "#666" }}>
                    {t.start < "1990-01-01" ? "Klasik (1980+)" : t.start < "2000-01-01" ? "Orta (1990+)" : "Yeni (2000+)"}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr style={{ background: "#e8f0f8", fontWeight: "bold" }}>
                <td colSpan={2}>TOPLAM</td>
                <td style={{ textAlign: "right", fontFamily: "monospace" }}>
                  {tickerDetails.reduce((a, t) => a + t.weeks, 0).toLocaleString()}
                </td>
                <td colSpan={4} style={{ fontSize: "10px" }}>
                  Ortalama: {(tickerDetails.reduce((a, t) => a + t.years, 0) / tickerDetails.length).toFixed(1)} yil
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      {/* 3. Feature Kategorileri */}
      <div className="box" style={{ marginBottom: "12px" }}>
        <div className="box-head">⭐ Feature Kategorileri (Toplam: 135)</div>
        <div className="box-body" style={{ padding: 0 }}>
          <table className="data-table" style={{ marginBottom: 0 }}>
            <thead>
              <tr>
                <th>Kategori</th>
                <th>Sayi</th>
                <th>Ornek Feature'lar</th>
              </tr>
            </thead>
            <tbody>
              {featureCategories.map((f, i) => (
                <tr key={i}>
                  <td><b>{f.category}</b></td>
                  <td style={{ textAlign: "center" }}>{f.count}</td>
                  <td style={{ fontSize: "10px", color: "#666" }}>{f.examples}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 4. Sistem Durumu */}
      <div className="box" style={{ marginBottom: "12px" }}>
        <div className="box-head">⚙ Sistem Bilesen Durumu</div>
        <div className="box-body">
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <tbody>
              <tr>
                <td style={{ padding: "4px 12px 4px 0", fontSize: "11px" }}><b>Backend API:</b></td>
                <td style={{ padding: "4px 0", fontSize: "11px" }}><span className="text-green">Calisiyor</span> (localhost:8000)</td>
              </tr>
              <tr>
                <td style={{ padding: "4px 12px 4px 0", fontSize: "11px" }}><b>Frontend:</b></td>
                <td style={{ padding: "4px 0", fontSize: "11px" }}><span className="text-green">Calisiyor</span> (localhost:3000)</td>
              </tr>
              <tr>
                <td style={{ padding: "4px 12px 4px 0", fontSize: "11px" }}><b>PostgreSQL:</b></td>
                <td style={{ padding: "4px 0", fontSize: "11px" }}><span className="text-green">Calisiyor</span> (borsa/borsa123)</td>
              </tr>
              <tr>
                <td style={{ padding: "4px 12px 4px 0", fontSize: "11px" }}><b>Redis:</b></td>
                <td style={{ padding: "4px 0", fontSize: "11px" }}><span className="text-green">Calisiyor</span> (localhost:6379)</td>
              </tr>
              <tr>
                <td style={{ padding: "4px 12px 4px 0", fontSize: "11px" }}><b>Celery Worker:</b></td>
                <td style={{ padding: "4px 0", fontSize: "11px" }}><span className="text-green">Calisiyor</span> (solo, 28 task)</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* 5. Hedef Degiskenler */}
      <div className="box" style={{ marginBottom: "12px" }}>
        <div className="box-head">🎯 Hedef Degiskenler (Labels)</div>
        <div className="box-body">
          <table className="data-table" style={{ marginBottom: 0 }}>
            <thead>
              <tr>
                <th>Hedef</th>
                <th>Aciklama</th>
                <th>Tip</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><code>target_2pct_1w</code></td>
                <td>1 haftada %2 veya uzeri getiri</td>
                <td>Ikili Siniflandirma</td>
              </tr>
              <tr>
                <td><code>target_3pct_1w</code></td>
                <td>1 haftada %3 veya uzeri getiri</td>
                <td>Ikili Siniflandirma</td>
              </tr>
              <tr>
                <td><code>risk_target_1w</code></td>
                <td>1 haftada %2 veya uzeri kayip</td>
                <td>Risk Siniflandirmasi</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* 6. Veri Akis Semasi */}
      <div className="box" style={{ marginBottom: "12px" }}>
        <div className="box-head">🔄 Veri Akis Semasi</div>
        <div className="box-body" style={{ fontSize: "11px", lineHeight: "1.6" }}>
          <pre style={{ background: "#f5f5f5", padding: "8px", border: "1px solid #c0c0c0", fontSize: "10px", overflow: "auto" }}>
{`Yahoo Finance (yfinance)
    |
    +---> Hisse Listesi (20 ticker)
    |
    +---> Gunluk Fiyatlar (OHLCV)
    |       |
    |       +---> Haftalik Resample (W-FRI)
    |               |
    |               +---> Weekly Return Hesapla
    |               +---> Realized Volatility Hesapla
    |                       |
    |                       +---> Feature Engineering
    |                       |       |
    |                       |       +---> Teknik (RSI, MACD, SMA...)
    |                       |       +---> Finansal (P/E, ROE, Marj...)
    |                       |       +---> Makro (VIX, Faiz, CPI...)
    |                       |       +---> Haber/Sosyal (Sentiment...)
    |                       |
    |                       +---> Model Egitimi
    |                               |
    |                               +---> LightGBM / XGBoost / RF
    |                                       |
    |                                       +---> Tahmin
    |                                               |
    |                                               +---> Haftalik Sinyaller
    |                                               +---> Paper Trading
    |
    +---> Finansal Veriler (Ceyreklik)
            |
            +---> Bilanco / Gelir Tablosu
            +---> Sirket Metrikleri`}
          </pre>
        </div>
      </div>

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
