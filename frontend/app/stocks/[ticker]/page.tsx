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
  if (label === "positive") return "text-green";
  if (label === "negative") return "text-red";
  return "text-muted";
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
      <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
        <div className="alert alert-danger">
          {researchResult.error || `Stock not found: ${ticker}`}
        </div>
      </div>
    );
  }

  const risk = research.risk;
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
    <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
      <h1>{ticker}</h1>
      <p style={{ marginBottom: "10px", color: "#666", fontSize: "11px" }}>
        {research.name} · {research.sector} · {research.industry}
      </p>

      {auxErrors.length > 0 && <div className="alert alert-warning">{auxErrors.join(" · ")}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: "8px", marginBottom: "12px" }}>
        <MetricCard label="Win Rate" value={fmt(risk.win_rate, true)} color={risk.win_rate > 0.5 ? "text-green" : "text-red"} />
        <MetricCard label="Avg Weekly Return" value={fmt(risk.avg_weekly_return, true)} color={risk.avg_weekly_return > 0 ? "text-green" : "text-red"} />
        <MetricCard label="Annualized Sharpe" value={fmt(risk.annualized_sharpe)} color={risk.annualized_sharpe > 0.5 ? "text-green" : "text-red"} />
        <MetricCard label="Max Drawdown" value={fmt(risk.max_drawdown, true)} color="text-red" />
        <MetricCard label="Weekly Vol" value={fmt(risk.weekly_volatility, true)} />
        <MetricCard label="Skewness" value={fmt(risk.skewness)} />
        <MetricCard label="Total Weeks" value={risk.total_weeks.toString()} />
        <MetricCard label="Ticker" value={research.ticker} />
      </div>

      {prices.length > 0 && (
        <div className="box">
          <div className="box-head">Price History (2 Years)</div>
          <div className="box-body">
            <PriceChart data={prices} />
          </div>
        </div>
      )}

      {research.distribution.length > 0 && (
        <div className="box" style={{ marginTop: "12px" }}>
          <div className="box-head">Weekly Return Distribution</div>
          <div className="box-body">
            <ReturnDistributionChart data={research.distribution} />
          </div>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "12px", marginTop: "12px" }}>
        <div className="box">
          <div className="box-head">Top 10 Best Weeks</div>
          <div className="box-body" style={{ padding: 0 }}>
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th>Week</th>
                  <th>Return</th>
                </tr>
              </thead>
              <tbody>
                {research.best_weeks.map((week) => (
                  <tr key={week.week_ending}>
                    <td style={{ fontFamily: "monospace", fontSize: "10px" }}>{week.week_ending}</td>
                    <td className="text-green">{fmt(week.return, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="box">
          <div className="box-head">Top 10 Worst Weeks</div>
          <div className="box-body" style={{ padding: 0 }}>
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th>Week</th>
                  <th>Return</th>
                </tr>
              </thead>
              <tbody>
                {research.worst_weeks.map((week) => (
                  <tr key={week.week_ending}>
                    <td style={{ fontFamily: "monospace", fontSize: "10px" }}>{week.week_ending}</td>
                    <td className="text-red">{fmt(week.return, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {topGoodWeekFeatures.length > 0 && goodWeekFeatures && (
        <div className="box" style={{ marginTop: "12px" }}>
          <div className="box-head">Common Features in Good Entry Weeks (&gt;=2%)</div>
          <div className="box-body">
            <p style={{ fontSize: "10px", color: "#666", marginBottom: "8px" }}>
              Top features that differ most between winning weeks ({goodWeekFeatures.n_good}) and losing weeks ({goodWeekFeatures.n_bad}).
            </p>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Feature</th>
                  <th>Good Weeks Avg</th>
                  <th>Bad Weeks Avg</th>
                  <th>Difference</th>
                </tr>
              </thead>
              <tbody>
                {topGoodWeekFeatures.map(([name, values]) => (
                  <tr key={name}>
                    <td style={{ fontFamily: "monospace", color: "#336699" }}>{name}</td>
                    <td>{values.good_avg?.toFixed(3) ?? "-"}</td>
                    <td>{values.bad_avg?.toFixed(3) ?? "-"}</td>
                    <td className={tone(values.diff)}>
                      {values.diff != null ? (values.diff > 0 ? "+" : "") + values.diff.toFixed(3) : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="box" style={{ marginTop: "12px" }}>
        <div className="box-head">Latest Technical Indicators</div>
        <div className="box-body">
          <MetricGrid
            items={technicalItems.map(({ label, key, pct }) => ({
              label,
              value: fmt(research.technicals[key], pct),
              pct,
            }))}
          />
        </div>
      </div>

      <div className="box" style={{ marginTop: "12px" }}>
        <div className="box-head">Financial Metrics</div>
        <div className="box-body">
          <MetricGrid
            items={financialItems.map(({ label, key, pct }) => ({
              label,
              value: fmt(research.financials[key], pct),
              pct,
            }))}
          />
        </div>
      </div>

      {research.signals.length > 0 && (
        <div className="box" style={{ marginTop: "12px" }}>
          <div className="box-head">Signal History (Last 12 Weeks)</div>
          <div className="box-body">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Week</th>
                  <th>Signal</th>
                  <th>Loss Prob</th>
                  <th>Expected</th>
                  <th>Confidence</th>
                </tr>
              </thead>
              <tbody>
                {research.signals.map((signal) => (
                  <tr key={signal.week_starting}>
                    <td style={{ fontFamily: "monospace", fontSize: "10px" }}>{signal.week_starting}</td>
                    <td>
                      <div style={{ width: "220px", background: "#d4d0c8", border: "1px solid #999" }}>
                        <div
                          style={{
                            width: `${((signal.prob_2pct ?? 0) * 100).toFixed(0)}%`,
                            height: "10px",
                            background: "linear-gradient(to right, #336699, #6699cc)",
                          }}
                        />
                      </div>
                      <div style={{ fontSize: "10px", color: "#666", marginTop: "2px" }}>
                        {fmt(signal.prob_2pct, true, 1)}
                      </div>
                    </td>
                    <td className="text-red">{fmt(signal.prob_loss_2pct, true, 1)}</td>
                    <td className={tone(signal.expected_return)}>{fmt(signal.expected_return, true, 1)}</td>
                    <td>
                      <span className={`badge ${confidenceBadge(signal.confidence)}`}>{signal.confidence ?? "-"}</span>
                      {signal.rank != null && <span style={{ marginLeft: "6px", color: "#666", fontSize: "10px" }}>#{signal.rank}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ marginTop: "8px", fontSize: "10px", color: "#666" }}>
              Signal summary entries are shown as live labels when available.
            </div>
          </div>
        </div>
      )}

      {Object.keys(research.behavioral ?? {}).length > 0 && (
        <div className="box" style={{ marginTop: "12px" }}>
          <div className="box-head">Behavioral Finance Signals</div>
          <div className="box-body">
            <MetricGrid
              items={[
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
              ]
                .map(({ key, label, pct }) => {
                  const value = (research.behavioral ?? {})[key];
                  if (value == null) return null;
                  return {
                    label,
                    value: pct ? fmt(value, true, 1) : value.toFixed(2),
                    tone: value > 0 ? "text-green" : value < 0 ? "text-red" : "text-muted",
                  };
                })
                .filter(Boolean) as Array<{ label: string; value: string; tone: string }>}
            />
          </div>
        </div>
      )}

      {(research.social ?? []).length > 0 && (
        <div className="box" style={{ marginTop: "12px" }}>
          <div className="box-head">Social Sentiment (Last 12 Weeks)</div>
          <div className="box-body" style={{ padding: 0 }}>
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th>Week</th>
                  <th>Mentions</th>
                  <th>Sentiment</th>
                  <th>Momentum</th>
                  <th>Hype Risk</th>
                  <th>Abnormal</th>
                </tr>
              </thead>
              <tbody>
                {research.social.map((row) => (
                  <tr key={row.week_ending}>
                    <td style={{ fontFamily: "monospace", fontSize: "10px" }}>{row.week_ending?.slice(0, 10)}</td>
                    <td>{row.mention_count ?? "-"}</td>
                    <td className={sentimentColor(row.sentiment_polarity != null ? (row.sentiment_polarity > 0 ? "positive" : row.sentiment_polarity < 0 ? "negative" : "neutral") : null)}>
                      {row.sentiment_polarity?.toFixed(3) ?? "-"}
                    </td>
                    <td className={tone(row.mention_momentum)}>{row.mention_momentum?.toFixed(2) ?? "-"}</td>
                    <td className={row.hype_risk != null && row.hype_risk > 0.7 ? "text-red" : "text-muted"}>
                      {row.hype_risk?.toFixed(2) ?? "-"}
                    </td>
                    <td>{row.abnormal_attention?.toFixed(2) ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {research.news.length > 0 && (
        <div className="box" style={{ marginTop: "12px" }}>
          <div className="box-head">Recent News</div>
          <div className="box-body">
            {research.news.map((news, index) => (
              <div key={index} style={{ borderTop: index === 0 ? "none" : "1px solid #c0c0c0", paddingTop: index === 0 ? 0 : "8px", marginTop: index === 0 ? 0 : "8px" }}>
                <div style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                  <span className={`badge ${news.sentiment_label === "positive" ? "badge-success" : news.sentiment_label === "negative" ? "badge-danger" : "badge-info"}`}>
                    {news.sentiment_label}
                  </span>
                  <span>{news.headline}</span>
                </div>
                <div style={{ fontSize: "10px", color: "#666", marginTop: "4px" }}>
                  {news.source} · {news.published_at?.slice(0, 10)}
                  {news.sentiment_score != null && ` · score: ${news.sentiment_score.toFixed(2)}`}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function MetricCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="box" style={{ marginBottom: 0 }}>
      <div className="box-head">{label}</div>
      <div className="box-body">
        <div style={{ fontSize: "20px", fontWeight: "bold" }} className={color}>
          {value}
        </div>
      </div>
    </div>
  );
}

function MetricGrid({
  items,
}: {
  items: Array<{ label: string; value: string; pct?: boolean; tone?: string }>;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0, 1fr))", gap: "8px" }}>
      {items.map((item) => (
        <div key={item.label} style={{ background: "#f8f8f8", border: "1px solid #c0c0c0", padding: "8px" }}>
          <div style={{ fontSize: "10px", color: "#666", marginBottom: "4px" }}>{item.label}</div>
          <div style={{ fontFamily: "monospace", fontSize: "11px", fontWeight: "bold" }} className={item.tone}>
            {item.value}
          </div>
        </div>
      ))}
    </div>
  );
}

function tone(value: number | null | undefined): string {
  if (value == null) return "text-muted";
  return value >= 0 ? "text-green" : "text-red";
}

function confidenceBadge(confidence: string | null): string {
  if (confidence === "high") return "badge-success";
  if (confidence === "medium") return "badge-warning";
  return "badge-info";
}
