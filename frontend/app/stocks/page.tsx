import Link from "next/link";
import { loadApi } from "@/lib/server-api";

interface StockSummary {
  id: number;
  ticker: string;
  name: string;
  sector: string | null;
}

export default async function StocksPage() {
  const { data: stocksData, error } = await loadApi<StockSummary[]>("/stocks");
  const stocks = stocksData ?? [];
  const sectors = Array.from(new Set(stocks.map((s) => s.sector || "Bilinmeyen"))).sort();

  return (
    <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
      <h1>Hisseler</h1>

      <div className="info-box" style={{ marginBottom: "12px" }}>
        <b>Bu sayfa ne ise yarar?</b> Modelin izledigi hisse evrenini gosterir.
        Bir ticker'a tiklayinca fiyat gecmisi, feature'lar, haberler ve model sinyalleri tek hisse bazinda incelenir.
        Once veri kalitesi, sonra sinyal, sonra hisse detayi kontrol edilmelidir.
      </div>

      {error && <div className="alert alert-danger">Hisse listesi yuklenemedi: {error}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "8px", marginBottom: "12px" }}>
        <div className="metric-card">
          <div className="metric-label">Toplam Hisse</div>
          <div className="metric-value">{stocks.length}</div>
          <div className="metric-sub">aktif izleme evreni</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Sektor Sayisi</div>
          <div className="metric-value">{sectors.length}</div>
          <div className="metric-sub">dagilim kontrolu icin</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Sonraki Adim</div>
          <div className="metric-value" style={{ fontSize: "18px" }}>Detay</div>
          <div className="metric-sub">ticker sec ve veriyi incele</div>
        </div>
      </div>

      <div className="alert alert-info" style={{ marginBottom: "12px" }}>
        <b>Okuma notu:</b> Bu liste alim listesi degildir. Sadece sistemin veri topladigi ve modelin tarayabildigi
        evrendir. Tek hisse kararinda haftalik sinyal, veri kalitesi ve risk uyarilari birlikte okunmalidir.
      </div>

      <div className="box">
        <div className="box-head">Takip Edilen Hisse Evreni</div>
        <div className="box-body" style={{ padding: 0 }}>
          <table className="data-table" style={{ marginBottom: 0 }}>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Sirket</th>
                <th>Sektor</th>
                <th>Incele</th>
              </tr>
            </thead>
            <tbody>
              {stocks.length === 0 ? (
                <tr>
                  <td colSpan={4} style={{ color: "#666" }}>
                    {error ? "Aktif hisse verisi su anda alinmadi." : "Aktif hisse bulunamadi."}
                  </td>
                </tr>
              ) : (
                stocks.map((stock) => (
                  <tr key={stock.id}>
                    <td>
                      <Link href={`/stocks/${stock.ticker}`} prefetch={false}>
                        <b>{stock.ticker}</b>
                      </Link>
                    </td>
                    <td>{stock.name}</td>
                    <td>{stock.sector || "-"}</td>
                    <td>
                      <Link href={`/stocks/${stock.ticker}`} prefetch={false}>
                        Grafik, feature ve haber &raquo;
                      </Link>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
