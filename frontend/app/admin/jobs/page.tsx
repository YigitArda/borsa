"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";

interface JobRun {
  id: number;
  job_name: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  error: string | null;
  metadata_: string | null;
}

const STATUS_FILTERS = ["all", "running", "completed", "failed", "pending"];

export default function JobsPage() {
  const [jobs, setJobs] = useState<JobRun[]>([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);

  async function loadJobs() {
    setLoading(true);
    try {
      const data = await api.get<JobRun[]>("/admin/jobs?limit=100");
      setJobs(data);
    } catch {
      setJobs([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadJobs();
  }, []);

  const filtered = filter === "all" ? jobs : jobs.filter((j) => j.status === filter);

  const counts = STATUS_FILTERS.reduce<Record<string, number>>((acc, s) => {
    acc[s] = s === "all" ? jobs.length : jobs.filter((j) => j.status === s).length;
    return acc;
  }, {});

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white mb-1">Job Management</h1>
          <p className="text-slate-400 text-sm">Monitor and manage pipeline jobs.</p>
        </div>
        <button
          onClick={loadJobs}
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

      {/* Jobs Table */}
      {filtered.length === 0 ? (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-8 text-center text-slate-400 text-sm">
          {loading ? "Loading jobs..." : "No jobs match the selected filter."}
        </div>
      ) : (
        <div className="rounded-lg border border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-800 text-slate-400">
              <tr>
                <th className="px-4 py-3 text-left">ID</th>
                <th className="px-4 py-3 text-left">Job Name</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Started</th>
                <th className="px-4 py-3 text-left">Completed</th>
                <th className="px-4 py-3 text-left">Error</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((j) => (
                <tr key={j.id} className="border-t border-slate-700 hover:bg-slate-800/50">
                  <td className="px-4 py-3 text-slate-400 font-mono text-xs">{j.id}</td>
                  <td className="px-4 py-3 text-white font-medium">{j.job_name}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={j.status} />
                  </td>
                  <td className="px-4 py-3 text-slate-400 font-mono text-xs">{j.started_at}</td>
                  <td className="px-4 py-3 text-slate-400 font-mono text-xs">{j.completed_at ?? "—"}</td>
                  <td className="px-4 py-3 text-red-400 text-xs max-w-xs truncate" title={j.error ?? undefined}>
                    {j.error ?? "—"}
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
    running: "text-blue-400 bg-blue-400/10",
    completed: "text-green-400 bg-green-400/10",
    failed: "text-red-400 bg-red-400/10",
    pending: "text-yellow-400 bg-yellow-400/10",
  };
  const color = colorMap[status] ?? "text-slate-400 bg-slate-400/10";
  return <span className={`text-xs px-2 py-0.5 rounded ${color}`}>{status}</span>;
}
