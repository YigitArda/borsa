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

  return (
    <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
      <h1>Hisseler</h1>
      <p style={{ marginBottom: "10px", color: "#666", fontSize: "11px" }}>
        Aktif hisse listesi. Ayrintilar icin bir ticker secin.
      </p>

      {error && <div className="alert alert-danger">Hisse listesi yuklenemedi: {error}</div>}

      <div className="box">
        <div className="box-head">Universe</div>
        <div className="box-body" style={{ padding: 0 }}>
          <table className="data-table" style={{ marginBottom: 0 }}>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Ad</th>
                <th>Sector</th>
              </tr>
            </thead>
            <tbody>
              {stocks.length === 0 ? (
                <tr>
                  <td colSpan={3} style={{ color: "#666" }}>
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
