"use client";

import { useEffect, useState } from "react";
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
    <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
      <h1>Job Management</h1>
      <p style={{ marginBottom: "10px", color: "#666", fontSize: "11px" }}>
        Monitor pipeline jobs and retry the current queue state.
      </p>

      <div className="box">
        <div className="box-head">Controls</div>
        <div className="box-body" style={{ display: "flex", flexWrap: "wrap", gap: "6px", alignItems: "center" }}>
          <button onClick={loadJobs} disabled={loading}>
            {loading ? "Refreshing..." : "Refresh"}
          </button>
          {STATUS_FILTERS.map((s) => (
            <button
              key={s}
              onClick={() => setFilter(s)}
              className={filter === s ? "selected" : ""}
            >
              {s.charAt(0).toUpperCase() + s.slice(1)} ({counts[s] ?? 0})
            </button>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0, 1fr))", gap: "8px", margin: "12px 0" }}>
        <StatCard label="All" value={jobs.length} />
        <StatCard label="Running" value={counts.running ?? 0} />
        <StatCard label="Completed" value={counts.completed ?? 0} />
        <StatCard label="Failed" value={counts.failed ?? 0} />
        <StatCard label="Pending" value={counts.pending ?? 0} />
      </div>

      <div className="box">
        <div className="box-head">Jobs</div>
        <div className="box-body" style={{ padding: 0 }}>
          {filtered.length === 0 ? (
            <div style={{ padding: "12px", color: "#666" }}>
              {loading ? "Loading jobs..." : "No jobs match the selected filter."}
            </div>
          ) : (
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Job Name</th>
                  <th>Status</th>
                  <th>Started</th>
                  <th>Completed</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((j) => (
                  <tr key={j.id}>
                    <td style={{ fontFamily: "monospace", fontSize: "10px" }}>{j.id}</td>
                    <td><b>{j.job_name}</b></td>
                    <td>
                      <StatusBadge status={j.status} />
                    </td>
                    <td style={{ fontFamily: "monospace", fontSize: "10px" }}>{j.started_at}</td>
                    <td style={{ fontFamily: "monospace", fontSize: "10px" }}>{j.completed_at ?? "—"}</td>
                    <td style={{ color: "#cc0000", fontSize: "10px", maxWidth: "300px" }} title={j.error ?? undefined}>
                      {j.error ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    running: "badge-info",
    completed: "badge-success",
    failed: "badge-danger",
    pending: "badge-warning",
  };
  return <span className={`badge ${colorMap[status] ?? "badge-info"}`}>{status}</span>;
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="box" style={{ marginBottom: 0 }}>
      <div className="box-head">{label}</div>
      <div className="box-body">
        <div style={{ fontSize: "20px", fontWeight: "bold" }}>{value}</div>
      </div>
    </div>
  );
}
