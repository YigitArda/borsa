import PriceChart from "@/components/charts/PriceChart";
import ReturnDistributionChart from "@/components/charts/ReturnDistributionChart";
import { loadApi } from "@/lib/server-api";

interface SocialRow {
  week_ending: string;
  mention_count: number | null;
  sentiment_polarity: number | null;
  mention_momentum: number | null;
  hype_risk: number | null;
  abnormal_attention: number | null;
}

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
  behavioral: Record<string, number | null>;
  social: SocialRow[];
  news: { headline: string; published_at: string; source: string; sentiment_score: number | null; sentiment_label: string }[];
  signals: {
    week_starting: string;
    prob_2pct: number | null;
    prob_loss_2pct: number | null;
    expected_return: number | null;
    confidence: string | null;
    rank: number | null;
    signal_summary: string | null;
  }[];
}

interface GoodWeekFeatures {
  ticker: string;
  n_good: number;
  n_bad: number;
  features: Record<string, { good_avg: number | null; bad_avg: number | null; diff: number | null }>;
}

interface PriceRow {
  week_ending: string;
  close: number;
  weekly_return: number | null;
  realized_volatility: number | null;
}

function fmt(v: number | null | undefined, pct = false, decimals = 2): string {
  if (v == null) return "-";
  return pct ? `${(v * 100).toFixed(decimals)}%` : v.toFixed(decimals);
}

function sentimentColor(label: string | null) {
  if (label === "positive") return "text-green-400";
  if (label === "negative") return "text-red-400";
  return "text-slate-400";
}

function MetricCard({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
      <div className="text-xs text-slate-400">{label}</div>
      <div className={`text-xl font-bold mt-1 ${color || "text-white"}`}>{value}</div>
    </div>
  );
}

export default async function StockPage({ params }: { params: { ticker: string } }) {
  const ticker = params.ticker.toUpperCase();

  const [researchResult, pricesResult, goodWeekResult] = await Promise.all([
    loadApi<StockResearch>(`/stocks/${ticker}/research`),
    loadApi<PriceRow[]>(`/stocks/${ticker}/prices?limit=104`),
    loadApi<GoodWeekFeatures>(`/stocks/${ticker}/good-week-features`),
  ]);

  const research = researchResult.data;
  const prices = pricesResult.data ?? [];
  const goodWeekFeatures = goodWeekResult.data;
  const auxErrors = [pricesResult.error, goodWeekResult.error].filter(Boolean) as string[];

  if (!research) {
    return (
      <div className="max-w-6xl mx-auto space-y-4">
        <div className="rounded-lg border border-red-700/40 bg-red-900/10 p-4 text-sm text-red-300">
          {researchResult.error || `Stock not found: ${ticker}`}
        </div>
      </div>
    );
  }

  const r = research.risk;
  const technicalItems = [
    { label: "RSI (14)", key: "rsi_14", pct: false },
    { label: "MACD Hist", key: "macd_hist", pct: false },
    { label: "Momentum", key: "momentum", pct: true },
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

  const topGoodWeekFeatures = goodWeekFeatures ? Object.entries(goodWeekFeatures.features).slice(0, 12) : [];

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-white">{ticker}</h1>
        <p className="text-slate-400 mt-1">{research.name} · {research.sector} · {research.industry}</p>
      </div>

      {auxErrors.length > 0 && (
        <div className="rounded-lg border border-yellow-700/40 bg-yellow-900/10 p-4 text-sm text-yellow-300">
          {auxErrors.join(" · ")}
        </div>
      )}

      <div className="grid grid-cols-4 gap-4">
        <MetricCard label="Win Rate" value={fmt(r.win_rate, true)} color={r.win_rate > 0.5 ? "text-green-400" : "text-slate-300"} />
        <MetricCard label="Avg Weekly Return" value={fmt(r.avg_weekly_return, true)} color={(r.avg_weekly_return || 0) > 0 ? "text-green-400" : "text-red-400"} />
        <MetricCard label="Annualized Sharpe" value={fmt(r.annualized_sharpe)} color={(r.annualized_sharpe || 0) > 0.5 ? "text-green-400" : "text-yellow-400"} />
        <MetricCard label="Max Drawdown" value={fmt(r.max_drawdown, true)} color="text-red-400" />
        <MetricCard label="Weekly Vol" value={fmt(r.weekly_volatility, true)} />
        <MetricCard label="Skewness" value={fmt(r.skewness)} />
        <MetricCard label="Total Weeks" value={r.total_weeks?.toString() ?? "-"} />
      </div>

      {prices.length > 0 && (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <h2 className="text-lg font-semibold text-white mb-4">Price History (2 Years)</h2>
          <PriceChart data={prices} />
        </div>
      )}

      {research.distribution.length > 0 && (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <h2 className="text-lg font-semibold text-white mb-4">Weekly Return Distribution</h2>
          <ReturnDistributionChart data={research.distribution} />
        </div>
      )}

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

      {topGoodWeekFeatures.length > 0 && goodWeekFeatures && (
        <div className="rounded-lg border border-teal-700/40 bg-teal-900/10 p-4">
          <h2 className="text-lg font-semibold text-teal-300 mb-1">Common Features in Good Entry Weeks (&gt;=2%)</h2>
          <p className="text-xs text-slate-400 mb-4">
            Top features that differ most between winning weeks ({goodWeekFeatures.n_good}) and losing weeks ({goodWeekFeatures.n_bad}).
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-slate-300">
              <thead>
                <tr className="border-b border-slate-700 text-slate-400">
                  <th className="text-left py-1 pr-4">Feature</th>
                  <th className="text-right py-1 pr-4">Good Weeks Avg</th>
                  <th className="text-right py-1 pr-4">Bad Weeks Avg</th>
                  <th className="text-right py-1">Difference</th>
                </tr>
              </thead>
              <tbody>
                {topGoodWeekFeatures.map(([fname, vals]) => (
                  <tr key={fname} className="border-b border-slate-800">
                    <td className="py-1.5 pr-4 font-mono text-teal-400">{fname}</td>
                    <td className="text-right py-1.5 pr-4">{vals.good_avg?.toFixed(3) ?? "-"}</td>
                    <td className="text-right py-1.5 pr-4">{vals.bad_avg?.toFixed(3) ?? "-"}</td>
                    <td className={`text-right py-1.5 font-mono ${(vals.diff ?? 0) > 0 ? "text-green-400" : "text-red-400"}`}>
                      {vals.diff != null ? (vals.diff > 0 ? "+" : "") + vals.diff.toFixed(3) : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
        <h2 className="text-lg font-semibold text-white mb-4">Latest Technical Indicators</h2>
        <div className="grid grid-cols-5 gap-3">
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

      {research.signals.length > 0 && (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <h2 className="text-lg font-semibold text-white mb-4">Signal History (Last 12 Weeks)</h2>
          <div className="space-y-2">
            {research.signals.map((s) => (
              <div key={s.week_starting} className="space-y-1">
                <div className="flex items-center gap-4">
                  <span className="text-xs font-mono text-slate-400 w-28">{s.week_starting}</span>
                  <div className="flex-1 bg-slate-700 rounded-full h-2">
                    <div
                      className="bg-blue-500 rounded-full h-2 transition-all"
                      style={{ width: `${((s.prob_2pct ?? 0) * 100).toFixed(0)}%` }}
                    />
                  </div>
                  <span className="text-xs font-mono text-blue-400 w-12">{fmt(s.prob_2pct, true, 1)}</span>
                  {s.prob_loss_2pct != null && (
                    <span className="text-xs font-mono text-red-400 w-12">v{fmt(s.prob_loss_2pct, true, 1)}</span>
                  )}
                  {s.expected_return != null && (
                    <span className={`text-xs font-mono w-14 ${s.expected_return > 0 ? "text-green-400" : "text-red-400"}`}>
                      E[r]={fmt(s.expected_return, true, 1)}
                    </span>
                  )}
                  <span className={`text-xs px-1.5 py-0.5 rounded ${
                    s.confidence === "high" ? "bg-green-700 text-green-200" :
                    s.confidence === "medium" ? "bg-yellow-700 text-yellow-200" :
                    "bg-slate-700 text-slate-300"
                  }`}>{s.confidence ?? "-"}</span>
                  {s.rank != null && <span className="text-xs text-slate-500">#{s.rank}</span>}
                </div>
                {s.signal_summary && (
                  <div className="text-xs text-slate-500 font-mono pl-32">{s.signal_summary}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {Object.keys(research.behavioral ?? {}).length > 0 && (
        <div className="rounded-lg border border-purple-700/40 bg-purple-900/10 p-4">
          <h2 className="text-lg font-semibold text-purple-300 mb-1">Behavioral Finance Signals</h2>
          <p className="text-xs text-slate-400 mb-4">Anchoring, disposition, herding and overreaction indicators (latest week)</p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {[
              { key: "anchor_proximity_high", label: "52w High Proximity", pct: true },
              { key: "anchor_proximity_low", label: "52w Low Proximity", pct: true },
              { key: "anchor_breakout_signal", label: "Breakout Signal", pct: false },
              { key: "disposition_gain_proxy", label: "Gain Proxy", pct: true },
              { key: "disposition_selling_risk", label: "Selling Risk", pct: false },
              { key: "herding_score", label: "Herding Score", pct: true },
              { key: "overreaction_reversal", label: "Overreaction Rev.", pct: true },
              { key: "extreme_move_flag", label: "Extreme Move", pct: false },
              { key: "ngram_bullish_score", label: "N-gram Bullish", pct: true },
              { key: "ngram_bearish_score", label: "N-gram Bearish", pct: true },
              { key: "erm_score", label: "EPS Revision Mom.", pct: true },
              { key: "forward_pe_change", label: "Fwd PE Change", pct: false },
            ].map(({ key, label, pct }) => {
              const val = (research.behavioral ?? {})[key];
              if (val == null) return null;
              const isPositive = val > 0;
              const isNeutral = val === 0;
              return (
                <div key={key} className="bg-slate-800/60 rounded p-3 border border-slate-700">
                  <div className="text-xs text-slate-400 mb-1 truncate">{label}</div>
                  <div className={`text-sm font-mono font-semibold ${
                    isNeutral ? "text-slate-300" : isPositive ? "text-green-400" : "text-red-400"
                  }`}>
                    {pct ? fmt(val, true, 1) : val.toFixed(2)}
                  </div>
                </div>
              );
            }).filter(Boolean)}
          </div>
        </div>
      )}

      {(research.social ?? []).length > 0 && (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <h2 className="text-lg font-semibold text-white mb-4">Social Sentiment (Last 12 Weeks)</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-slate-300">
              <thead>
                <tr className="border-b border-slate-700 text-slate-400">
                  <th className="text-left py-1 pr-3">Week</th>
                  <th className="text-right py-1 pr-3">Mentions</th>
                  <th className="text-right py-1 pr-3">Sentiment</th>
                  <th className="text-right py-1 pr-3">Momentum</th>
                  <th className="text-right py-1 pr-3">Hype Risk</th>
                  <th className="text-right py-1">Abnormal</th>
                </tr>
              </thead>
              <tbody>
                {(research.social ?? []).map((s) => (
                  <tr key={s.week_ending} className="border-b border-slate-800 hover:bg-slate-700/30">
                    <td className="py-1.5 pr-3 font-mono text-slate-400">{s.week_ending?.slice(0, 10)}</td>
                    <td className="text-right py-1.5 pr-3">{s.mention_count ?? "-"}</td>
                    <td className={`text-right py-1.5 pr-3 font-mono ${
                      (s.sentiment_polarity ?? 0) > 0.1 ? "text-green-400" :
                      (s.sentiment_polarity ?? 0) < -0.1 ? "text-red-400" : "text-slate-400"
                    }`}>{s.sentiment_polarity?.toFixed(3) ?? "-"}</td>
                    <td className={`text-right py-1.5 pr-3 font-mono ${
                      (s.mention_momentum ?? 0) > 0 ? "text-green-400" : "text-red-400"
                    }`}>{s.mention_momentum?.toFixed(2) ?? "-"}</td>
                    <td className={`text-right py-1.5 pr-3 ${
                      (s.hype_risk ?? 0) > 0.7 ? "text-orange-400 font-semibold" : "text-slate-300"
                    }`}>{s.hype_risk?.toFixed(2) ?? "-"}</td>
                    <td className="text-right py-1.5 font-mono">{s.abnormal_attention?.toFixed(2) ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {research.news.length > 0 && (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <h2 className="text-lg font-semibold text-white mb-4">Recent News</h2>
          <div className="space-y-3">
            {research.news.map((n, i) => (
              <div key={i} className="border-t border-slate-700 pt-3 first:border-0 first:pt-0">
                <div className="flex items-start gap-2">
                  <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${sentimentColor(n.sentiment_label)}`}>
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
