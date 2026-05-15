import { api } from "@/lib/api";
import Link from "next/link";

interface Stock {
  id: number;
  ticker: string;
  name: string;
  sector: string;
}

interface Strategy {
  id: number;
  name: string;
  status: string;
  generation: number;
  notes: string;
}

async function getStocks(): Promise<Stock[]> {
  try { return await api.get<Stock[]>("/stocks"); } catch { return []; }
}

async function getStrategies(): Promise<Strategy[]> {
  try { return await api.get<Strategy[]>("/strategies?status=promoted"); } catch { return []; }
}

export default async function Dashboard() {
  const [stocks, strategies] = await Promise.all([getStocks(), getStrategies()]);

  return (
    <div className="space-y-8 max-w-6xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold text-white mb-1">Dashboard</h1>
        <p className="text-slate-400 text-sm">Research-only system. Results are backtested, not live trading.</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="Stocks Tracked" value={stocks.length} />
        <StatCard label="Promoted Strategies" value={strategies.length} />
        <StatCard label="Status" value="Research Mode" highlight />
      </div>

      {/* Promoted Strategies */}
      <section>
        <h2 className="text-lg font-semibold text-white mb-3">Promoted Strategies</h2>
        {strategies.length === 0 ? (
          <div className="rounded-lg border border-slate-700 bg-slate-800 p-6 text-slate-400 text-sm">
            No promoted strategies yet. Start the research loop from{" "}
            <Link href="/strategy-lab" className="text-blue-400 hover:underline">Strategy Lab</Link>.
          </div>
        ) : (
          <div className="space-y-3">
            {strategies.map((s) => (
              <div key={s.id} className="rounded-lg border border-slate-700 bg-slate-800 p-4">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-white">{s.name}</span>
                  <span className="text-xs bg-green-500/20 text-green-400 px-2 py-1 rounded">
                    Generation {s.generation}
                  </span>
                </div>
                <p className="text-xs text-slate-400 mt-1">{s.notes}</p>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Stock Grid */}
      <section>
        <h2 className="text-lg font-semibold text-white mb-3">Universe ({stocks.length} stocks)</h2>
        <div className="grid grid-cols-4 gap-3">
          {stocks.map((s) => (
            <Link key={s.id} href={`/stocks/${s.ticker}`}>
              <div className="rounded-lg border border-slate-700 bg-slate-800 hover:border-blue-500 transition-colors p-3 cursor-pointer">
                <div className="font-bold text-blue-400">{s.ticker}</div>
                <div className="text-xs text-slate-400 truncate">{s.name}</div>
                <div className="text-xs text-slate-500">{s.sector}</div>
              </div>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}

function StatCard({ label, value, highlight }: { label: string; value: string | number; highlight?: boolean }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-5">
      <div className="text-sm text-slate-400">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${highlight ? "text-yellow-400" : "text-white"}`}>{value}</div>
    </div>
  );
}
