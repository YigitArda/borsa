"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";

interface Strategy {
  id: number;
  name: string;
  status: string;
  generation: number;
  config: Record<string, unknown>;
  created_at: string;
  notes: string | null;
}

const STATUS_FILTERS = ["all", "research", "promoted", "archived", "candidate"];

export default function StrategiesAdminPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);

  async function loadStrategies() {
    setLoading(true);
    try {
      const data = await api.get<Strategy[]>("/strategies?limit=200");
      setStrategies(data);
    } catch {
      setStrategies([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadStrategies();
  }, []);

  const filtered = filter === "all" ? strategies : strategies.filter((s) => s.status === filter);

  const counts = STATUS_FILTERS.reduce<Record<string, number>>((acc, s) => {
    acc[s] = s === "all" ? strategies.length : strategies.filter((j) => j.status === s).length;
    return acc;
  }, {});

  async function archiveStrategy(id: number) {
    if (!confirm("Archive this strategy?")) return;
    try {
      await api.post(`/strategies/${id}/archive`, {});
      await loadStrategies();
    } catch {
      alert("Failed to archive strategy");
    }
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white mb-1">Strategy Management</h1>
          <p className="text-slate-400 text-sm">Review, promote, and archive strategies.</p>
        </div>
        <button
          onClick={loadStrategies}
          disabled={loading}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded text-sm font-medium"
        >
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            className={`px-3 py-1.5 rounded text-xs font-medium border transition-colors ${
              filter === s
                ? "bg-blue-600 border-blue-500 text-white"
                : "bg-slate-800 border-slate-700 text-slate-300 hover:border-slate-500"
            }`}
          >
            {s.charAt(0).toUpperCase() + s.slice(1)} ({counts[s] ?? 0})
          </button>
        ))}
      </div>

      {/* Strategies Table */}
      {filtered.length === 0 ? (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-8 text-center text-slate-400 text-sm">
          {loading ? "Loading strategies..." : "No strategies match the selected filter."}
        </div>
      ) : (
        <div className="rounded-lg border border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-800 text-slate-400">
              <tr>
                <th className="px-4 py-3 text-left">ID</th>
                <th className="px-4 py-3 text-left">Name</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Generation</th>
                <th className="px-4 py-3 text-left">Created</th>
                <th className="px-4 py-3 text-left">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((s) => (
                <tr key={s.id} className="border-t border-slate-700 hover:bg-slate-800/50">
                  <td className="px-4 py-3 text-slate-400 font-mono text-xs">{s.id}</td>
                  <td className="px-4 py-3 text-white font-medium">{s.name}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={s.status} />
                  </td>
                  <td className="px-4 py-3 text-slate-300">{s.generation}</td>
                  <td className="px-4 py-3 text-slate-400 font-mono text-xs">{s.created_at}</td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2">
                      {s.status !== "archived" && (
                        <button
                          onClick={() => archiveStrategy(s.id)}
                          className="px-2 py-1 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded text-xs"
                        >
                          Archive
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    research: "text-blue-400 bg-blue-400/10",
    promoted: "text-green-400 bg-green-400/10",
    archived: "text-slate-400 bg-slate-400/10",
    candidate: "text-yellow-400 bg-yellow-400/10",
  };
  const color = colorMap[status] ?? "text-slate-400 bg-slate-400/10";
  return <span className={`text-xs px-2 py-0.5 rounded ${color}`}>{status}</span>;
}
