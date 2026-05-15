import { api } from "@/lib/api";
import PriceChart from "@/components/charts/PriceChart";
import ReturnDistributionChart from "@/components/charts/ReturnDistributionChart";

interface StockResearch {
  ticker: string;
  name: string;
  sector: string;
  industry: string;
  risk: {
    avg_weekly_return: number;
    weekly_volatility: number;
    annualized_sharpe: number;
    skewness: number;
    win_rate: number;
    max_drawdown: number;
    total_weeks: number;
  };
  distribution: { bucket: number; count: number }[];
  best_weeks: { week_ending: string; return: number }[];
  worst_weeks: { week_ending: string; return: number }[];
  technicals: Record<string, number | null>;
  financials: Record<string, number | null>;
  news: { headline: string; published_at: string; source: string; sentiment_score: number | null; sentiment_label: string }[];
  signals: { week_ending: string; probability: number; rank: number }[];
}

interface PriceRow {
  week_ending: string;
  close: number;
  weekly_return: number | null;
  realized_volatility: number | null;
}

async function getResearch(ticker: string): Promise<StockResearch | null> {
  try { return await api.get<StockResearch>(`/stocks/${ticker}/research`); } catch { return null; }
}

async function getPrices(ticker: string): Promise<PriceRow[]> {
  try { return await api.get<PriceRow[]>(`/stocks/${ticker}/prices?limit=104`); } catch { return []; }
}

function fmt(v: number | null | undefined, pct = false, decimals = 2): string {
  if (v == null) return "—";
  return pct ? `${(v * 100).toFixed(decimals)}%` : v.toFixed(decimals);
}

function sentimentColor(label: string | null) {
  if (label === "positive") return "text-green-400";
  if (label === "negative") return "text-red-400";
  return "text-slate-400";
}

export default async function StockPage({ params }: { params: { ticker: string } }) {
  const ticker = params.ticker.toUpperCase();
  const [research, prices] = await Promise.all([getResearch(ticker), getPrices(ticker)]);

  if (!research) {
    return <div className="text-slate-400 p-8">Stock not found: {ticker}</div>;
  }

  const r = research.risk;

  const technicalItems = [
    { label: "RSI (14)", key: "rsi_14", pct: false },
    { label: "MACD Hist", key: "macd_hist", pct: false },
    { label: "BB Position", key: "bb_position", pct: false },
    { label: "Volume Z-Score", key: "volume_zscore", pct: false },
    { label: "vs SMA 50", key: "price_to_sma50", pct: true },
    { label: "vs SMA 200", key: "price_to_sma200", pct: true },
    { label: "Return 1W", key: "return_1w", pct: true },
    { label: "Return 4W", key: "return_4w", pct: true },
    { label: "Return 12W", key: "return_12w", pct: true },
    { label: "52W High Dist", key: "high_52w_distance", pct: true },
    { label: "52W Low Dist", key: "low_52w_distance", pct: true },
    { label: "Trend Strength", key: "trend_strength", pct: false },
    { label: "Realized Vol", key: "realized_vol", pct: false },
    { label: "ATR (14)", key: "atr_14", pct: false },
  ];

  const financialItems = [
    { label: "P/E (TTM)", key: "pe_ratio" },
    { label: "Fwd P/E", key: "forward_pe" },
    { label: "P/B", key: "price_to_book" },
    { label: "EV/EBITDA", key: "ev_to_ebitda" },
    { label: "Gross Margin", key: "gross_margin", pct: true },
    { label: "Op. Margin", key: "operating_margin", pct: true },
    { label: "Net Margin", key: "net_margin", pct: true },
    { label: "ROE", key: "roe", pct: true },
    { label: "ROA", key: "roa", pct: true },
    { label: "Rev. Growth", key: "revenue_growth", pct: true },
    { label: "EPS Growth", key: "earnings_growth", pct: true },
    { label: "D/E Ratio", key: "debt_to_equity" },
    { label: "Current Ratio", key: "current_ratio" },
    { label: "Beta", key: "beta" },
    { label: "Market Cap", key: "market_cap" },
  ];

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-white">{ticker}</h1>
        <p className="text-slate-400 mt-1">{research.name} · {research.sector} · {research.industry}</p>
      </div>

      {/* Risk metrics row */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: "Win Rate", value: fmt(r.win_rate, true), color: r.win_rate > 0.5 ? "text-green-400" : "text-slate-300" },
          { label: "Avg Weekly Return", value: fmt(r.avg_weekly_return, true), color: (r.avg_weekly_return || 0) > 0 ? "text-green-400" : "text-red-400" },
          { label: "Annualized Sharpe", value: fmt(r.annualized_sharpe), color: (r.annualized_sharpe || 0) > 0.5 ? "text-green-400" : "text-yellow-400" },
          { label: "Max Drawdown", value: fmt(r.max_drawdown, true), color: "text-red-400" },
          { label: "Weekly Vol", value: fmt(r.weekly_volatility, true), color: "text-slate-300" },
          { label: "Skewness", value: fmt(r.skewness), color: "text-slate-300" },
          { label: "Total Weeks", value: r.total_weeks?.toString(), color: "text-slate-300" },
        ].map(({ label, value, color }) => (
          <div key={label} className="rounded-lg border border-slate-700 bg-slate-800 p-4">
            <div className="text-xs text-slate-400">{label}</div>
            <div className={`text-xl font-bold mt-1 ${color}`}>{value}</div>
          </div>
        ))}
      </div>

      {/* Price chart */}
      {prices.length > 0 && (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <h2 className="text-lg font-semibold text-white mb-4">Price History (2 Years)</h2>
          <PriceChart data={prices} />
        </div>
      )}

      {/* Return distribution */}
      {research.distribution.length > 0 && (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <h2 className="text-lg font-semibold text-white mb-4">Weekly Return Distribution</h2>
          <ReturnDistributionChart data={research.distribution} />
        </div>
      )}

      {/* Best / Worst weeks */}
      <div className="grid grid-cols-2 gap-6">
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <h2 className="text-base font-semibold text-green-400 mb-3">Top 10 Best Weeks</h2>
          <table className="w-full text-sm">
            <thead><tr className="text-slate-400 text-xs"><th className="text-left pb-2">Week</th><th className="text-right pb-2">Return</th></tr></thead>
            <tbody>
              {research.best_weeks.map((w) => (
                <tr key={w.week_ending} className="border-t border-slate-700">
                  <td className="py-1.5 text-slate-300 font-mono text-xs">{w.week_ending}</td>
                  <td className="py-1.5 text-right text-green-400 font-mono">{fmt(w.return, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <h2 className="text-base font-semibold text-red-400 mb-3">Top 10 Worst Weeks</h2>
          <table className="w-full text-sm">
            <thead><tr className="text-slate-400 text-xs"><th className="text-left pb-2">Week</th><th className="text-right pb-2">Return</th></tr></thead>
            <tbody>
              {research.worst_weeks.map((w) => (
                <tr key={w.week_ending} className="border-t border-slate-700">
                  <td className="py-1.5 text-slate-300 font-mono text-xs">{w.week_ending}</td>
                  <td className="py-1.5 text-right text-red-400 font-mono">{fmt(w.return, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Technical indicators */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
        <h2 className="text-lg font-semibold text-white mb-4">Latest Technical Indicators</h2>
        <div className="grid grid-cols-4 gap-3">
          {technicalItems.map(({ label, key, pct }) => {
            const val = research.technicals[key];
            return (
              <div key={key} className="bg-slate-700/50 rounded p-3">
                <div className="text-xs text-slate-400 mb-1">{label}</div>
                <div className="text-sm font-mono text-white">{fmt(val, pct)}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Financial metrics */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
        <h2 className="text-lg font-semibold text-white mb-4">Financial Metrics</h2>
        <div className="grid grid-cols-5 gap-3">
          {financialItems.map(({ label, key, pct }) => {
            const val = research.financials[key];
            return (
              <div key={key} className="bg-slate-700/50 rounded p-3">
                <div className="text-xs text-slate-400 mb-1">{label}</div>
                <div className="text-sm font-mono text-white">{fmt(val, pct)}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Signal history */}
      {research.signals.length > 0 && (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <h2 className="text-lg font-semibold text-white mb-4">Signal History (Last 12 Weeks)</h2>
          <div className="space-y-2">
            {research.signals.map((s) => (
              <div key={s.week_ending} className="flex items-center gap-4">
                <span className="text-xs font-mono text-slate-400 w-28">{s.week_ending}</span>
                <div className="flex-1 bg-slate-700 rounded-full h-2">
                  <div
                    className="bg-blue-500 rounded-full h-2 transition-all"
                    style={{ width: `${(s.probability * 100).toFixed(0)}%` }}
                  />
                </div>
                <span className="text-xs font-mono text-blue-400 w-12">{fmt(s.probability, true, 1)}</span>
                <span className="text-xs text-slate-400">Rank #{s.rank}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* News */}
      {research.news.length > 0 && (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <h2 className="text-lg font-semibold text-white mb-4">Recent News</h2>
          <div className="space-y-3">
            {research.news.map((n, i) => (
              <div key={i} className="border-t border-slate-700 pt-3 first:border-0 first:pt-0">
                <div className="flex items-start gap-2">
                  <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${sentimentColor(n.sentiment_label)} bg-current/10`}>
                    {n.sentiment_label}
                  </span>
                  <span className="text-sm text-slate-200 leading-snug">{n.headline}</span>
                </div>
                <div className="text-xs text-slate-500 mt-1">
                  {n.source} · {n.published_at?.slice(0, 10)}
                  {n.sentiment_score != null && ` · score: ${n.sentiment_score.toFixed(2)}`}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
