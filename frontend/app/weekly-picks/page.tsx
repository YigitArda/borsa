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

async function getPicks(): Promise<Pick[]> {
  try { return await api.get<Pick[]>("/weekly-picks"); } catch { return []; }
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
    </div>
  );
}
