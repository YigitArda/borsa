"use client";

import { useEffect, useState } from "react";
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
    <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
      <h1>Strategy Management</h1>
      <p style={{ marginBottom: "10px", color: "#666", fontSize: "11px" }}>
        Review, promote and archive research strategies.
      </p>

      <div className="box">
        <div className="box-head">Controls</div>
        <div className="box-body" style={{ display: "flex", flexWrap: "wrap", gap: "6px", alignItems: "center" }}>
          <button onClick={loadStrategies} disabled={loading}>
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
        <StatCard label="All" value={strategies.length} />
        <StatCard label="Research" value={counts.research ?? 0} />
        <StatCard label="Promoted" value={counts.promoted ?? 0} />
        <StatCard label="Archived" value={counts.archived ?? 0} />
        <StatCard label="Candidate" value={counts.candidate ?? 0} />
      </div>

      <div className="box">
        <div className="box-head">Strategies</div>
        <div className="box-body" style={{ padding: 0 }}>
          {filtered.length === 0 ? (
            <div style={{ padding: "12px", color: "#666" }}>
              {loading ? "Loading strategies..." : "No strategies match the selected filter."}
            </div>
          ) : (
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Name</th>
                  <th>Status</th>
                  <th>Generation</th>
                  <th>Created</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((s) => (
                  <tr key={s.id}>
                    <td style={{ fontFamily: "monospace", fontSize: "10px" }}>{s.id}</td>
                    <td><b>{s.name}</b></td>
                    <td>
                      <StatusBadge status={s.status} />
                    </td>
                    <td>{s.generation}</td>
                    <td style={{ fontFamily: "monospace", fontSize: "10px" }}>{s.created_at}</td>
                    <td>
                      {s.status !== "archived" && (
                        <button onClick={() => archiveStrategy(s.id)}>Archive</button>
                      )}
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
    research: "badge-info",
    promoted: "badge-success",
    archived: "badge-info",
    candidate: "badge-warning",
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
