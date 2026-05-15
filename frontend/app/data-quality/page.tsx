import { api } from "@/lib/api";

interface StockReport {
  ticker: string;
  name: string;
  weekly_price_rows: number;
  daily_price_rows: number;
  feature_rows: number;
  latest_week: string | null;
  status: string;
}

interface DQReport {
  stocks: StockReport[];
  macro_freshness: Record<string, string>;
  total_stocks: number;
  stocks_with_data: number;
}

async function getDQReport(): Promise<DQReport | null> {
  try { return await api.get<DQReport>("/data-quality"); } catch { return null; }
}

export default async function DataQuality() {
  const report = await getDQReport();

  if (!report) {
    return <div className="p-8 text-slate-400">Could not load data quality report. Is the API running?</div>;
  }

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Data Quality</h1>
        <p className="text-slate-400 text-sm mt-1">Coverage and freshness of all data sources.</p>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-3 gap-4">
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <div className="text-xs text-slate-400">Total Stocks</div>
          <div className="text-2xl font-bold text-white mt-1">{report.total_stocks}</div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <div className="text-xs text-slate-400">Stocks with Data</div>
          <div className="text-2xl font-bold text-green-400 mt-1">{report.stocks_with_data}</div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <div className="text-xs text-slate-400">Missing Data</div>
          <div className="text-2xl font-bold text-red-400 mt-1">{report.total_stocks - report.stocks_with_data}</div>
        </div>
      </div>

      {/* Macro Freshness */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-5">
        <h2 className="text-lg font-semibold text-white mb-3">Macro Data Freshness</h2>
        <div className="grid grid-cols-3 gap-3">
          {Object.entries(report.macro_freshness).map(([code, latest]) => (
            <div key={code} className="bg-slate-700 rounded p-3">
              <div className="text-xs text-slate-400">{code}</div>
              <div className="text-sm text-white font-mono">{latest}</div>
            </div>
          ))}
        </div>
        {Object.keys(report.macro_freshness).length === 0 && (
          <p className="text-slate-500 text-sm">No macro data ingested yet. Run the pipeline first.</p>
        )}
      </div>

      {/* Stock Table */}
      <div className="rounded-lg border border-slate-700 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-800 text-slate-400">
            <tr>
              <th className="px-4 py-3 text-left">Ticker</th>
              <th className="px-4 py-3 text-right">Daily Rows</th>
              <th className="px-4 py-3 text-right">Weekly Rows</th>
              <th className="px-4 py-3 text-right">Feature Rows</th>
              <th className="px-4 py-3 text-center">Latest Week</th>
              <th className="px-4 py-3 text-center">Status</th>
            </tr>
          </thead>
          <tbody>
            {report.stocks.map((s) => (
              <tr key={s.ticker} className="border-t border-slate-700 hover:bg-slate-800/50">
                <td className="px-4 py-2 font-bold text-blue-400">{s.ticker}</td>
                <td className="px-4 py-2 text-right text-slate-300 font-mono">{s.daily_price_rows.toLocaleString()}</td>
                <td className="px-4 py-2 text-right text-slate-300 font-mono">{s.weekly_price_rows.toLocaleString()}</td>
                <td className="px-4 py-2 text-right text-slate-300 font-mono">{s.feature_rows.toLocaleString()}</td>
                <td className="px-4 py-2 text-center text-slate-400 font-mono">{s.latest_week ?? "—"}</td>
                <td className="px-4 py-2 text-center">
                  <span className={`text-xs px-2 py-0.5 rounded ${s.status === "ok" ? "text-green-400 bg-green-400/10" : "text-red-400 bg-red-400/10"}`}>
                    {s.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
