import Link from "next/link";
import { api } from "@/lib/api";

interface StockSummary {
  id: number;
  ticker: string;
  name: string;
  sector: string | null;
}

async function getStocks(): Promise<StockSummary[]> {
  try {
    return await api.get<StockSummary[]>("/stocks");
  } catch {
    return [];
  }
}

export default async function StocksPage() {
  const stocks = await getStocks();

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white mb-1">Hisseler</h1>
        <p className="text-slate-400 text-sm">
          Aktif hisse listesi. Ayrintilar, fiyat gecmisi ve research ozeti icin bir ticker secin.
        </p>
      </div>

      <div className="rounded-lg border border-slate-700 bg-slate-800 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700">
          <div className="text-sm text-slate-300">{stocks.length} aktif hisse</div>
          <div className="text-xs text-slate-500 font-mono">/stocks/[ticker]</div>
        </div>

        {stocks.length === 0 ? (
          <div className="p-6 text-slate-400 text-sm">
            Aktif hisse bulunamadi. Veri senkronizasyonunu kontrol edin.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-900 text-slate-400">
                <tr>
                  <th className="px-4 py-3 text-left">Ticker</th>
                  <th className="px-4 py-3 text-left">Ad</th>
                  <th className="px-4 py-3 text-left">Sector</th>
                </tr>
              </thead>
              <tbody>
                {stocks.map((stock) => (
                  <tr key={stock.id} className="border-t border-slate-700 hover:bg-slate-700/40">
                    <td className="px-4 py-3">
                      <Link href={`/stocks/${stock.ticker}`} className="font-mono text-blue-300 hover:underline">
                        {stock.ticker}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-white">{stock.name}</td>
                    <td className="px-4 py-3 text-slate-400">{stock.sector || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
