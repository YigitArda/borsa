"use client";

import { useState } from "react";
import EquityChart from "@/components/charts/EquityChart";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const MODEL_TYPES = ["lightgbm", "logistic_regression", "random_forest", "gradient_boosting", "catboost", "xgboost", "neural_network"];
const TARGETS = ["target_2pct_1w", "target_3pct_1w", "risk_target_1w"];
const TOP_N_OPTIONS = [3, 5, 7, 10];
const HOLDING_OPTIONS = [
  { label: "1 hafta", value: 1 },
  { label: "2 hafta", value: 2 },
  { label: "4 hafta", value: 4 },
];

const ALL_FEATURE_OPTIONS = [
  "rsi_14","macd","macd_signal","macd_hist","sma_20","sma_50","sma_200","ema_12","ema_26",
  "bb_position","atr_14","volume_zscore","return_1w","return_4w","return_12w","momentum",
  "high_52w_distance","low_52w_distance","trend_strength","price_to_sma50","price_to_sma200","realized_vol",
  "pe_ratio","forward_pe","price_to_sales","price_to_book","ev_to_ebitda",
  "gross_margin","operating_margin","net_margin","roe","roa","revenue_growth","earnings_growth",
  "debt_to_equity","current_ratio","beta",
  "VIX","VIX_WEEKLY","VIX_CHANGE_W","TNX_10Y","FED_RATE_PROXY","RISK_ON_SCORE",
  "sp500_trend_20w","nasdaq_trend_20w","cpi_proxy_trend_26w",
  "news_sentiment_score","news_volume","news_earnings_flag",
  "social_mention_count","social_mention_momentum","social_sentiment_polarity",
  "pe_percentile_sector","pb_percentile_sector","ev_ebitda_percentile_sector",
];

const SP500_TICKERS = [
  "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","BRK-B","JPM","V",
  "UNH","XOM","JNJ","MA","PG","HD","CVX","MRK","LLY","ABBV",
];

interface BacktestResult {
  status: string;
  task_id?: string;
  results?: Array<{
    status: string;
    strategy_id?: number;
    avg_sharpe?: number;
    avg_win_rate?: number;
    total_trades?: number;
    deflated_sharpe?: number;
    permutation_pvalue?: number;
    outperforms_spy?: boolean;
    spy_sharpe?: number;
    benchmark_alpha?: number;
  }>;
}

interface DirectBacktestResult {
  status: string;
  n_folds?: number;
  avg_metrics?: Record<string, number | null>;
  folds?: Array<{
    fold: number;
    test_start: string;
    test_end: string;
    metrics: Record<string, number>;
    equity_curve: Array<{ date: string; equity: number }>;
  }>;
  reason?: string;
}

function StatBox({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div style={{ border: "1px solid #c0c0c0", padding: "4px 8px", background: "#f8f8f8" }}>
      <div style={{ fontSize: "9px", color: "#666", fontFamily: "Tahoma,sans-serif" }}>{label}</div>
      <div style={{
        fontSize: "11px", fontFamily: "monospace", marginTop: "2px",
        color: good === true ? "#006600" : good === false ? "#cc0000" : "#000",
        fontWeight: good !== undefined ? "bold" : "normal",
      }}>
        {value}
      </div>
    </div>
  );
}

export default function StrategyLab() {
  const [modelType, setModelType] = useState("lightgbm");
  const [target, setTarget] = useState("target_2pct_1w");
  const [threshold, setThreshold] = useState(0.5);
  const [topN, setTopN] = useState(5);
  const [holdingWeeks, setHoldingWeeks] = useState(1);
  const [applyLiquidityFilter, setApplyLiquidityFilter] = useState(true);
  const [nIterations, setNIterations] = useState(5);
  const [selectedTickers, setSelectedTickers] = useState<string[]>(SP500_TICKERS.slice(0, 10));
  const [selectedFeatures, setSelectedFeatures] = useState<string[]>(ALL_FEATURE_OPTIONS.slice(0, 22));
  const [pipelineStatus, setPipelineStatus] = useState<string | null>(null);
  const [researchResult, setResearchResult] = useState<BacktestResult | null>(null);
  const [directResult, setDirectResult] = useState<DirectBacktestResult | null>(null);
  const [running, setRunning] = useState(false);
  const [directRunning, setDirectRunning] = useState(false);
  const [promotedStrategies, setPromotedStrategies] = useState<BacktestResult["results"]>([]);

  function toggleTicker(t: string) {
    setSelectedTickers(prev => prev.includes(t) ? prev.filter(x => x !== t) : [...prev, t]);
  }
  function toggleFeature(f: string) {
    setSelectedFeatures(prev => prev.includes(f) ? prev.filter(x => x !== f) : [...prev, f]);
  }

  async function runDirectBacktest() {
    setDirectRunning(true);
    setDirectResult(null);
    try {
      const res = await fetch(`${API}/backtest/direct`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_type: modelType, features: selectedFeatures, target,
          threshold, top_n: topN, holding_weeks: holdingWeeks,
          apply_liquidity_filter: applyLiquidityFilter,
          tickers: selectedTickers, min_train_years: 5,
        }),
      });
      setDirectResult(await res.json());
    } catch {
      setDirectResult({ status: "error", reason: "Request failed" });
    } finally {
      setDirectRunning(false);
    }
  }

  async function triggerPipeline(endpoint: string, label: string, body?: object) {
    setPipelineStatus(`${label}...`);
    try {
      const res = await fetch(`${API}/pipeline/${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      const d = await res.json();
      setPipelineStatus(`${label} kuyruğa alındı — task: ${d.task_id}`);
    } catch {
      setPipelineStatus(`${label} başarısız`);
    }
  }

  async function startResearch() {
    setRunning(true);
    setResearchResult(null);
    try {
      const res = await fetch(
        `${API}/strategies/research/start?n_iterations=${nIterations}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model_type: modelType, target, threshold, top_n: topN, holding_weeks: holdingWeeks, features: [] }),
        }
      );
      const d = await res.json();
      setResearchResult({ status: d.status, task_id: d.task_id });
    } catch {
      setResearchResult({ status: "error" });
    } finally {
      setRunning(false);
    }
  }

  async function loadPromotedStrategies() {
    try {
      const res = await fetch(`${API}/strategies`);
      const data: Array<{ id: number; name: string; status: string; notes: string }> = await res.json();
      const parsed = data.filter(s => ["candidate", "promoted"].includes(s.status)).map(s => {
        try {
          const m = JSON.parse(s.notes || "{}");
          return { status: s.status, strategy_id: s.id, ...m };
        } catch {
          return { status: s.status, strategy_id: s.id };
        }
      });
      setPromotedStrategies(parsed);
    } catch {}
  }

  const sectionStyle = {
    border: "1px solid #c0c0c0",
    marginBottom: "12px",
  };
  const sectionHeadStyle = {
    background: "linear-gradient(to bottom, #6699cc, #336699)",
    color: "#fff", fontSize: "11px", fontWeight: "bold" as const,
    padding: "3px 8px", fontFamily: "Tahoma,sans-serif",
  };
  const sectionBodyStyle = { padding: "8px", background: "#fff" };

  return (
    <div>
      <h1>🔬 Strateji Lab</h1>

      <div className="alert alert-info">
        ℹ Backtest çalıştır, araştırma döngüsü başlat. Sadece araştırma amaçlıdır.
      </div>

      {/* 1. Hisse Evreni */}
      <div style={sectionStyle}>
        <div style={sectionHeadStyle}>1. Hisse Evreni</div>
        <div style={sectionBodyStyle}>
          <p style={{ marginBottom: "6px", fontSize: "11px", color: "#666" }}>
            {selectedTickers.length} hisse seçildi
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "4px" }}>
            {SP500_TICKERS.map(t => (
              <button
                key={t}
                onClick={() => toggleTicker(t)}
                style={{
                  padding: "2px 8px", fontSize: "10px", fontFamily: "monospace",
                  border: selectedTickers.includes(t) ? "1px solid #264d7a" : "1px solid #999",
                  background: selectedTickers.includes(t)
                    ? "linear-gradient(to bottom, #6699cc, #336699)"
                    : "linear-gradient(to bottom, #fff, #d4d0c8)",
                  color: selectedTickers.includes(t) ? "#fff" : "#000",
                  cursor: "pointer",
                }}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 2. Pipeline */}
      <div style={sectionStyle}>
        <div style={sectionHeadStyle}>2. Veri Pipeline</div>
        <div style={sectionBodyStyle}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "4px" }}>
            {[
              { label: "Evren Snapshot", endpoint: "snapshot-universe", body: { tickers: selectedTickers } },
              { label: "Fiyat Al", endpoint: "ingest", body: { tickers: selectedTickers } },
              { label: "Feature Hesapla", endpoint: "features", body: { tickers: selectedTickers } },
              { label: "Makro (VIX/Faiz)", endpoint: "macro" },
              { label: "Haberler", endpoint: "news", body: { tickers: selectedTickers } },
              { label: "Finansallar", endpoint: "financials", body: { tickers: selectedTickers } },
              { label: "Bilanço/Gelir/NA", endpoint: "statements", body: { tickers: selectedTickers } },
              { label: "Sosyal Duygu", endpoint: "social", body: { tickers: selectedTickers } },
              { label: "🔄 Tümünü Çalıştır", endpoint: "run-all", body: { tickers: selectedTickers } },
            ].map(({ label, endpoint, body }) => (
              <button key={endpoint} onClick={() => triggerPipeline(endpoint, label, body)}>
                {label}
              </button>
            ))}
          </div>
          {pipelineStatus && (
            <p style={{ marginTop: "6px", fontSize: "10px", color: "#336699" }}>
              {pipelineStatus}
            </p>
          )}
        </div>
      </div>

      {/* 3. Feature Seçimi */}
      <div style={sectionStyle}>
        <div style={sectionHeadStyle}>
          3. Feature Seti &nbsp;
          <span style={{ fontWeight: "normal" }}>
            ({selectedFeatures.length} / {ALL_FEATURE_OPTIONS.length} seçildi)
          </span>
        </div>
        <div style={sectionBodyStyle}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "3px" }}>
            {ALL_FEATURE_OPTIONS.map(f => (
              <button key={f} onClick={() => toggleFeature(f)} style={{
                padding: "1px 6px", fontSize: "10px", fontFamily: "monospace",
                border: selectedFeatures.includes(f) ? "1px solid #264d7a" : "1px solid #999",
                background: selectedFeatures.includes(f)
                  ? "linear-gradient(to bottom, #4d8a4d, #2d6a2d)"
                  : "linear-gradient(to bottom, #fff, #d4d0c8)",
                color: selectedFeatures.includes(f) ? "#fff" : "#000",
                cursor: "pointer",
              }}>
                {f}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 4. Direkt Backtest */}
      <div style={sectionStyle}>
        <div style={sectionHeadStyle}>4. Direkt Backtest (Walk-Forward)</div>
        <div style={sectionBodyStyle}>
          <table style={{ borderCollapse: "collapse", marginBottom: "8px" }}>
            <tbody>
              <tr>
                <td style={{ padding: "3px 8px 3px 0", fontSize: "11px" }}>Model:</td>
                <td style={{ padding: "3px 8px 3px 0" }}>
                  <select value={modelType} onChange={e => setModelType(e.target.value)}>
                    {MODEL_TYPES.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                </td>
                <td style={{ padding: "3px 8px 3px 0", fontSize: "11px" }}>Hedef:</td>
                <td style={{ padding: "3px 8px 3px 0" }}>
                  <select value={target} onChange={e => setTarget(e.target.value)}>
                    {TARGETS.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </td>
                <td style={{ padding: "3px 8px 3px 0", fontSize: "11px" }}>Holding:</td>
                <td style={{ padding: "3px 8px 3px 0" }}>
                  <select value={holdingWeeks} onChange={e => setHoldingWeeks(+e.target.value)}>
                    {HOLDING_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </td>
              </tr>
              <tr>
                <td style={{ padding: "3px 8px 3px 0", fontSize: "11px" }}>Eşik: {threshold}</td>
                <td style={{ padding: "3px 8px 3px 0" }}>
                  <input type="range" min={0.3} max={0.8} step={0.05} value={threshold}
                    onChange={e => setThreshold(+e.target.value)} style={{ width: "120px" }} />
                </td>
                <td style={{ padding: "3px 8px 3px 0", fontSize: "11px" }}>Max Pozisyon:</td>
                <td style={{ padding: "3px 8px 3px 0" }}>
                  <select value={topN} onChange={e => setTopN(+e.target.value)}>
                    {TOP_N_OPTIONS.map(n => <option key={n} value={n}>{n}</option>)}
                  </select>
                </td>
                <td colSpan={2} style={{ padding: "3px 8px 3px 0" }}>
                  <label style={{ fontSize: "11px" }}>
                    <input type="checkbox" checked={applyLiquidityFilter}
                      onChange={e => setApplyLiquidityFilter(e.target.checked)}
                      style={{ marginRight: "4px" }} />
                    $5M likidite filtresi
                  </label>
                </td>
              </tr>
            </tbody>
          </table>

          <button
            onClick={runDirectBacktest}
            disabled={directRunning || selectedTickers.length === 0 || selectedFeatures.length === 0}
          >
            {directRunning ? "⏳ Çalışıyor..." : "▶ Direkt Backtest Çalıştır"}
          </button>

          {directResult && (
            <div style={{ marginTop: "10px" }}>
              {directResult.status === "failed" || directResult.status === "error" ? (
                <div className="alert alert-danger">{directResult.reason || "Backtest başarısız"}</div>
              ) : (
                <>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginBottom: "8px" }}>
                    {Object.entries(directResult.avg_metrics || {}).slice(0, 8).map(([k, v]) => (
                      <StatBox key={k} label={k} value={v != null ? v.toFixed(3) : "—"}
                        good={k === "sharpe" ? (v ?? 0) > 0.5 : k === "max_drawdown" ? (v ?? 0) > -0.25 : undefined} />
                    ))}
                  </div>
                  <p style={{ fontSize: "10px", color: "#666", marginBottom: "6px" }}>
                    {directResult.n_folds} walk-forward fold
                  </p>
                  {directResult.folds?.slice(0, 1)[0]?.equity_curve?.length > 0 && (
                    <EquityChart data={directResult.folds![0].equity_curve} />
                  )}
                  <table className="data-table" style={{ marginTop: "8px" }}>
                    <thead>
                      <tr>
                        <th>Fold</th>
                        <th>Test Dönemi</th>
                        <th>Sharpe</th>
                        <th>Win Rate</th>
                        <th>İşlem</th>
                        <th>Max DD</th>
                      </tr>
                    </thead>
                    <tbody>
                      {directResult.folds?.map(f => (
                        <tr key={f.fold}>
                          <td>{f.fold}</td>
                          <td style={{ fontFamily: "monospace", fontSize: "10px" }}>{f.test_start} → {f.test_end}</td>
                          <td className={(f.metrics.sharpe ?? 0) > 0 ? "text-green" : "text-red"}>
                            {f.metrics.sharpe?.toFixed(3) ?? "—"}
                          </td>
                          <td>{f.metrics.win_rate != null ? `${(f.metrics.win_rate * 100).toFixed(1)}%` : "—"}</td>
                          <td>{f.metrics.n_trades ?? "—"}</td>
                          <td className={(f.metrics.max_drawdown ?? 0) < -0.2 ? "text-red" : ""}>
                            {f.metrics.max_drawdown != null ? `${(f.metrics.max_drawdown * 100).toFixed(1)}%` : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* 5. Araştırma Döngüsü */}
      <div style={sectionStyle}>
        <div style={sectionHeadStyle}>5. Otomatik Araştırma Döngüsü</div>
        <div style={sectionBodyStyle}>
          <p style={{ fontSize: "11px", color: "#666", marginBottom: "8px" }}>
            Mutasyon önerileri walk-forward + kabul kapısından otomatik geçer. Celery arka planda çalışır.
          </p>
          <table style={{ borderCollapse: "collapse", marginBottom: "8px" }}>
            <tbody>
              <tr>
                <td style={{ padding: "3px 8px 3px 0", fontSize: "11px" }}>İterasyon sayısı:</td>
                <td>
                  <input type="number" min={1} max={50} value={nIterations}
                    onChange={e => setNIterations(+e.target.value)}
                    style={{ width: "60px" }} />
                </td>
              </tr>
            </tbody>
          </table>
          <div style={{ display: "flex", gap: "6px" }}>
            <button onClick={startResearch} disabled={running || selectedTickers.length === 0}>
              {running ? "⏳ Çalışıyor..." : "▶ Araştırma Döngüsünü Başlat"}
            </button>
            <button onClick={loadPromotedStrategies}>
              Aday/Promoted Stratejileri Yükle
            </button>
          </div>
          {researchResult && (
            <div style={{ marginTop: "8px", fontSize: "11px" }}>
              Durum: <b>{researchResult.status}</b>
              {researchResult.task_id && <span> · Task: {researchResult.task_id}</span>}
              <br />
              <span style={{ fontSize: "10px", color: "#666" }}>
                Araştırma Celery ile arka planda çalışır. Sonuçlar için stratejiler sayfasını kontrol edin.
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Promoted/Aday stratejiler */}
      {promotedStrategies && promotedStrategies.length > 0 && (
        <div style={sectionStyle}>
          <div style={{ ...sectionHeadStyle, background: "linear-gradient(to bottom, #4d8a4d, #2d6a2d)" }}>
            ✅ Aday / Promoted Stratejiler ({promotedStrategies.length} adet)
          </div>
          <div style={sectionBodyStyle}>
            {promotedStrategies.map((s, i) => s && (
              <div key={i} style={{ border: "1px solid #c0c0c0", padding: "6px", marginBottom: "8px", background: "#f8fff8" }}>
                <div style={{ marginBottom: "6px" }}>
                  <b>Strateji #{s.strategy_id}</b> &nbsp;
                  <span className={`badge ${s.status === "promoted" ? "badge-success" : "badge-warning"}`}>
                    {s.status === "promoted" ? "PROMOTED" : "PAPER TEST"}
                  </span>
                  {s.outperforms_spy && <> <span className="badge badge-info">SPY&apos;yi Geçiyor</span></>}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                  <StatBox label="Ort. Sharpe" value={s.avg_sharpe?.toFixed(3) ?? "—"} good={(s.avg_sharpe ?? 0) > 0.5} />
                  <StatBox label="Deflated SR" value={s.deflated_sharpe?.toFixed(3) ?? "—"} good={(s.deflated_sharpe ?? 0) > 0} />
                  <StatBox label="Win Rate" value={s.avg_win_rate != null ? `${(s.avg_win_rate * 100).toFixed(1)}%` : "—"} good={(s.avg_win_rate ?? 0) > 0.5} />
                  <StatBox label="Toplam İşlem" value={s.total_trades?.toString() ?? "—"} />
                  <StatBox label="Permütasyon p" value={s.permutation_pvalue?.toFixed(3) ?? "—"} good={(s.permutation_pvalue ?? 1) < 0.1} />
                  <StatBox label="SPY Sharpe" value={s.spy_sharpe?.toFixed(3) ?? "—"} />
                  <StatBox label="SPY&apos;yi Geçiyor" value={s.outperforms_spy ? "Evet" : "Hayır"} good={s.outperforms_spy} />
                  <StatBox label="Benchmark Alpha" value={s.benchmark_alpha != null ? `${(s.benchmark_alpha * 100).toFixed(2)}%` : "—"} good={(s.benchmark_alpha ?? 0) > 0} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Kabul Kapısı */}
      <div className="alert alert-warning">
        <b>⚙ Kabul Kapısı (Tümü Geçmeli)</b><br />
        <table style={{ marginTop: "4px", borderCollapse: "collapse" }}>
          <tbody>
            {[
              ["Ort. Sharpe ≥ 0.5", "Win Rate ≥ %45"],
              ["Toplam İşlem ≥ 30", "Max Drawdown ≥ -%25"],
              ["Ort. Kâr Faktörü ≥ 1.1", "Permütasyon p-değeri &lt; 0.10"],
              ["Deflated Sharpe &gt; 0", "Sadece walk-forward (veri sızıntısı yok)"],
            ].map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j} style={{ padding: "1px 16px 1px 0", fontSize: "10px" }}
                    dangerouslySetInnerHTML={{ __html: cell }} />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <p style={{ marginTop: "4px", fontSize: "10px", color: "#664400" }}>
          %80-95 red oranı beklentisi normaldir — bu hata değil, doğru davranıştır.
        </p>
      </div>

      <div style={{
        textAlign: "center", padding: "6px", background: "#e8f0f8",
        border: "1px solid #c0c0c0", fontSize: "10px",
        fontFamily: "Tahoma,sans-serif", color: "#666", marginTop: "8px"
      }}>
        Bu sistem yalnızca araştırma amaçlıdır, yatırım tavsiyesi değildir
      </div>
    </div>
  );
}
