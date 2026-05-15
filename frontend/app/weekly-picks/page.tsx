import { api } from "@/lib/api";
import Link from "next/link";

interface Pick {
  rank: number;
  ticker: string;
  name: string;
  sector: string;
  week_starting: string;
  prob_2pct: number | null;
  prob_loss_2pct: number | null;
  expected_return: number | null;
  confidence: string | null;
  signal_summary: string | null;
}

interface PaperTrade {
  id: number;
  ticker: string;
  week_starting: string;
  rank: number | null;
  prob_2pct: number | null;
  expected_return: number | null;
  realized_return: number | null;
  status: string;
  hit_2pct: boolean | null;
}

interface PaperResponse {
  summary: {
    total: number;
    open: number;
    pending_data: number;
    closed: number;
    hit_rate_2pct: number | null;
    avg_prob_2pct: number | null;
    avg_realized_return: number | null;
    calibration_error_2pct: number | null;
  };
  trades: PaperTrade[];
}

async function getPicks(): Promise<Pick[]> {
  try { return await api.get<Pick[]>("/weekly-picks"); } catch { return []; }
}

async function getPaper(): Promise<PaperResponse | null> {
  try { return await api.get<PaperResponse>("/weekly-picks/paper?limit=25"); } catch { return null; }
}

function pct(v: number | null) {
  return v != null ? `${(v * 100).toFixed(1)}%` : "—";
}

function Badge({ c }: { c: string | null }) {
  const color = c === "high" ? "text-green-400 bg-green-400/10" : c === "medium" ? "text-yellow-400 bg-yellow-400/10" : "text-slate-400 bg-slate-400/10";
  return <span className={`text-xs px-2 py-0.5 rounded ${color}`}>{c ?? "low"}</span>;
}

export default async function WeeklyPicks() {
  const picks = await getPicks();
  const paper = await getPaper();

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Weekly Picks</h1>
        <p className="text-slate-400 text-sm mt-1">
          Model-generated candidates. Not financial advice. Research only.
        </p>
      </div>

      {picks.length === 0 ? (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-8 text-center text-slate-400">
          No picks available yet. Run the pipeline first from the{" "}
          <Link href="/strategy-lab" className="text-blue-400 hover:underline">Strategy Lab</Link>.
        </div>
      ) : (
        <div className="rounded-lg border border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-800 text-slate-400">
              <tr>
                <th className="px-4 py-3 text-left">#</th>
                <th className="px-4 py-3 text-left">Ticker</th>
                <th className="px-4 py-3 text-left">Sector</th>
                <th className="px-4 py-3 text-right">P(≥2%)</th>
                <th className="px-4 py-3 text-right">P(≤-2%)</th>
                <th className="px-4 py-3 text-right">E[Return]</th>
                <th className="px-4 py-3 text-center">Confidence</th>
                <th className="px-4 py-3 text-left">Signal</th>
              </tr>
            </thead>
            <tbody>
              {picks.map((p) => (
                <tr key={p.ticker} className="border-t border-slate-700 hover:bg-slate-800/50">
                  <td className="px-4 py-3 text-slate-400">{p.rank}</td>
                  <td className="px-4 py-3">
                    <Link href={`/stocks/${p.ticker}`} className="font-bold text-blue-400 hover:underline">
                      {p.ticker}
                    </Link>
                    <div className="text-xs text-slate-400">{p.name}</div>
                  </td>
                  <td className="px-4 py-3 text-slate-400">{p.sector}</td>
                  <td className="px-4 py-3 text-right text-green-400">{pct(p.prob_2pct)}</td>
                  <td className="px-4 py-3 text-right text-red-400">{pct(p.prob_loss_2pct)}</td>
                  <td className={`px-4 py-3 text-right font-medium ${(p.expected_return ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {pct(p.expected_return)}
                  </td>
                  <td className="px-4 py-3 text-center"><Badge c={p.confidence} /></td>
                  <td className="px-4 py-3 text-xs text-slate-400 max-w-xs truncate">{p.signal_summary ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="rounded-lg border border-slate-700 bg-slate-800 p-5 space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-white">Paper Forward Test</h2>
            <p className="text-xs text-slate-400">Predictions compared with realized weekly returns. Paper only.</p>
          </div>
          {paper?.summary && (
            <div className="grid grid-cols-4 gap-2 text-xs">
              <div className="bg-slate-700/60 rounded p-2">
                <div className="text-slate-400">Closed</div>
                <div className="text-white font-mono">{paper.summary.closed}</div>
              </div>
              <div className="bg-slate-700/60 rounded p-2">
                <div className="text-slate-400">Hit &gt;=2%</div>
                <div className="text-white font-mono">{pct(paper.summary.hit_rate_2pct)}</div>
              </div>
              <div className="bg-slate-700/60 rounded p-2">
                <div className="text-slate-400">Avg Realized</div>
                <div className="text-white font-mono">{pct(paper.summary.avg_realized_return)}</div>
              </div>
              <div className="bg-slate-700/60 rounded p-2">
                <div className="text-slate-400">Calibration</div>
                <div className="text-white font-mono">{pct(paper.summary.calibration_error_2pct)}</div>
              </div>
            </div>
          )}
        </div>

        {!paper || paper.trades.length === 0 ? (
          <p className="text-sm text-slate-400">No paper trades opened yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-slate-400">
                <tr className="border-b border-slate-700">
                  <th className="py-2 text-left">Week</th>
                  <th className="py-2 text-left">Ticker</th>
                  <th className="py-2 text-right">P(&gt;=2%)</th>
                  <th className="py-2 text-right">E[Return]</th>
                  <th className="py-2 text-right">Realized</th>
                  <th className="py-2 text-center">Status</th>
                </tr>
              </thead>
              <tbody>
                {paper.trades.slice(0, 10).map((t) => (
                  <tr key={t.id} className="border-b border-slate-700/60">
                    <td className="py-2 text-slate-400 font-mono">{t.week_starting}</td>
                    <td className="py-2">
                      <Link href={`/stocks/${t.ticker}`} className="text-blue-400 hover:underline font-mono">
                        {t.ticker}
                      </Link>
                    </td>
                    <td className="py-2 text-right text-green-400">{pct(t.prob_2pct)}</td>
                    <td className="py-2 text-right text-slate-300">{pct(t.expected_return)}</td>
                    <td className={`py-2 text-right ${((t.realized_return ?? 0) >= 0) ? "text-green-400" : "text-red-400"}`}>
                      {pct(t.realized_return)}
                    </td>
                    <td className="py-2 text-center">
                      <span className={`px-2 py-0.5 rounded ${t.status === "closed" ? "bg-green-400/10 text-green-400" : "bg-slate-400/10 text-slate-400"}`}>
                        {t.status}
                      </span>
                    </td>
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
