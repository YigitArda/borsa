import { api } from "@/lib/api";
import PriceChart from "@/components/charts/PriceChart";

interface StockDetail {
  ticker: string;
  name: string;
  sector: string;
  industry: string;
  total_weeks_analyzed: number;
  weeks_with_2pct_return: number;
  historical_hit_rate: number | null;
}

interface PriceRow {
  week_ending: string;
  close: number;
  weekly_return: number | null;
  realized_volatility: number | null;
}

async function getAnalysis(ticker: string): Promise<StockDetail | null> {
  try { return await api.get<StockDetail>(`/stocks/${ticker}/analysis`); } catch { return null; }
}

async function getPrices(ticker: string): Promise<PriceRow[]> {
  try { return await api.get<PriceRow[]>(`/stocks/${ticker}/prices?limit=104`); } catch { return []; }
}

export default async function StockPage({ params }: { params: { ticker: string } }) {
  const ticker = params.ticker.toUpperCase();
  const [analysis, prices] = await Promise.all([getAnalysis(ticker), getPrices(ticker)]);

  if (!analysis) {
    return <div className="text-slate-400 p-8">Stock not found: {ticker}</div>;
  }

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">{ticker}</h1>
        <p className="text-slate-400">{analysis.name} · {analysis.sector} · {analysis.industry}</p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-4">
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <div className="text-xs text-slate-400">Weeks Analyzed</div>
          <div className="text-2xl font-bold text-white mt-1">{analysis.total_weeks_analyzed}</div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <div className="text-xs text-slate-400">Weeks ≥2% Return</div>
          <div className="text-2xl font-bold text-green-400 mt-1">{analysis.weeks_with_2pct_return}</div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <div className="text-xs text-slate-400">Historical Hit Rate</div>
          <div className="text-2xl font-bold text-blue-400 mt-1">
            {analysis.historical_hit_rate != null ? `${(analysis.historical_hit_rate * 100).toFixed(1)}%` : "—"}
          </div>
        </div>
      </div>

      {/* Price chart */}
      {prices.length > 0 && (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <h2 className="text-lg font-semibold text-white mb-4">Price History (2 years)</h2>
          <PriceChart data={prices} />
        </div>
      )}
    </div>
  );
}
