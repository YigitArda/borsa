"use client";

import { useEffect, useState } from "react";
import { arxiv } from "@/lib/api";

type ArxivPaper = {
  id: number;
  arxiv_id: string;
  url: string;
  title: string;
  authors: string | null;
  abstract: string | null;
  published_date: string | null;
  categories: string | null;
  is_read: boolean;
  fetched_at: string | null;
};

type ResearchInsight = {
  id: number;
  arxiv_id: string | null;
  feature_name: string | null;
  description: string | null;
  pseudocode: string | null;
  applicable: boolean;
  status: string;
  created_at: string | null;
};

export default function ArxivPage() {
  const [papers, setPapers] = useState<ArxivPaper[]>([]);
  const [insights, setInsights] = useState<ResearchInsight[]>([]);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [insightStatus, setInsightStatus] = useState<string>("all");
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function load() {
      setLoading(true);
      try {
        const [paperData, insightData] = await Promise.all([
          arxiv.papers(40, unreadOnly),
          arxiv.insights(insightStatus === "all" ? undefined : insightStatus, 40),
        ]);
        if (!active) return;
        setPapers(paperData);
        setInsights(insightData);
        setError(null);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "ArXiv data could not be loaded.");
      } finally {
        if (active) setLoading(false);
      }
    }

    load();
    return () => {
      active = false;
    };
  }, [unreadOnly, insightStatus]);

  async function refresh() {
    setMessage(null);
    setError(null);
    setLoading(true);
    try {
      const [paperData, insightData] = await Promise.all([
        arxiv.papers(40, unreadOnly),
        arxiv.insights(insightStatus === "all" ? undefined : insightStatus, 40),
      ]);
      setPapers(paperData);
      setInsights(insightData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ArXiv data could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  async function runScan() {
    setMessage("ArXiv scan queued.");
    try {
      await arxiv.scan();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "ArXiv scan could not be queued.");
    }
  }

  async function runExtract() {
    setMessage("Insight extraction queued.");
    try {
      await arxiv.extract();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Insight extraction could not be queued.");
    }
  }

  async function markRead(paperId: number) {
    try {
      await arxiv.markRead(paperId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Paper could not be marked as read.");
    }
  }

  return (
    <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
      <h1>ArXiv Papers</h1>
      <p style={{ marginBottom: "10px", color: "#666", fontSize: "11px" }}>
        Quant finance papers, extracted feature ideas and human-in-the-loop review.
      </p>

      <div className="alert alert-info">
        <b>Akis:</b> Yeni paper taramasi arka planda kuyruğa alınır. Öneri özetleri ve feature fikirleri burada listelenir.
      </div>

      {message && <div className="alert alert-success">{message}</div>}
      {error && <div className="alert alert-danger">{error}</div>}

      <div className="box">
        <div className="box-head">Kontroller</div>
        <div className="box-body" style={{ display: "flex", flexWrap: "wrap", gap: "8px", alignItems: "center" }}>
          <label style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
            <input
              type="checkbox"
              checked={unreadOnly}
              onChange={(e) => setUnreadOnly(e.target.checked)}
            />
            Unread only
          </label>

          <label style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
            <span className="section-label" style={{ marginBottom: 0 }}>Insight filter</span>
            <select value={insightStatus} onChange={(e) => setInsightStatus(e.target.value)}>
              <option value="all">all</option>
              <option value="new">new</option>
              <option value="approved">approved</option>
              <option value="implemented">implemented</option>
              <option value="rejected">rejected</option>
            </select>
          </label>

          <button onClick={refresh} disabled={loading}>
            {loading ? "Refreshing..." : "Refresh"}
          </button>
          <button onClick={runScan} disabled={loading}>
            Scan Papers
          </button>
          <button onClick={runExtract} disabled={loading}>
            Extract Insights
          </button>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "8px", marginBottom: "12px" }}>
        <StatCard label="Papers" value={papers.length} />
        <StatCard label="Unread" value={papers.filter((p) => !p.is_read).length} />
        <StatCard label="Insights" value={insights.length} />
      </div>

      <div className="box">
        <div className="box-head">Recent Papers</div>
        <div className="box-body" style={{ padding: 0 }}>
          <table className="data-table" style={{ marginBottom: 0 }}>
            <thead>
              <tr>
                <th>Title</th>
                <th>Authors</th>
                <th>Categories</th>
                <th>Published</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {papers.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ color: "#666" }}>
                    {loading ? "Loading papers..." : "No papers found."}
                  </td>
                </tr>
              ) : (
                papers.map((paper) => (
                  <tr key={paper.id}>
                    <td style={{ maxWidth: "420px" }}>
                      <a href={paper.url} target="_blank" rel="noreferrer">
                        <b>{paper.title}</b>
                      </a>
                      <div style={{ fontSize: "10px", color: "#666", marginTop: "3px" }}>
                        {paper.arxiv_id}
                      </div>
                    </td>
                    <td style={{ maxWidth: "220px" }}>{paper.authors ?? "—"}</td>
                    <td style={{ color: "#336699" }}>{paper.categories ?? "—"}</td>
                    <td style={{ fontFamily: "monospace", fontSize: "10px" }}>
                      {paper.published_date ? paper.published_date.slice(0, 10) : "—"}
                    </td>
                    <td>
                      <span className={`badge ${paper.is_read ? "badge-info" : "badge-warning"}`}>
                        {paper.is_read ? "READ" : "NEW"}
                      </span>
                    </td>
                    <td>
                      {!paper.is_read ? (
                        <button onClick={() => markRead(paper.id)}>Mark Read</button>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="box" style={{ marginTop: "12px" }}>
        <div className="box-head">Research Insights</div>
        <div className="box-body" style={{ padding: 0 }}>
          <table className="data-table" style={{ marginBottom: 0 }}>
            <thead>
              <tr>
                <th>Feature</th>
                <th>Status</th>
                <th>Applicable</th>
                <th>Description</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {insights.length === 0 ? (
                <tr>
                  <td colSpan={5} style={{ color: "#666" }}>
                    {loading ? "Loading insights..." : "No insights found."}
                  </td>
                </tr>
              ) : (
                insights.map((insight) => (
                  <tr key={insight.id}>
                    <td>
                      <b>{insight.feature_name ?? "—"}</b>
                      <div style={{ fontSize: "10px", color: "#666" }}>{insight.arxiv_id ?? "—"}</div>
                    </td>
                    <td>
                      <span className="badge badge-info">{insight.status.toUpperCase()}</span>
                    </td>
                    <td>
                      <span className={`badge ${insight.applicable ? "badge-success" : "badge-danger"}`}>
                        {insight.applicable ? "YES" : "NO"}
                      </span>
                    </td>
                    <td style={{ maxWidth: "420px" }}>
                      {insight.description ?? "—"}
                      {insight.pseudocode && (
                        <pre style={{ marginTop: "6px", whiteSpace: "pre-wrap", fontSize: "10px", background: "#f8f8f8", border: "1px solid #c0c0c0", padding: "4px" }}>
                          {insight.pseudocode}
                        </pre>
                      )}
                    </td>
                    <td style={{ fontFamily: "monospace", fontSize: "10px" }}>
                      {insight.created_at ? insight.created_at.slice(0, 19).replace("T", " ") : "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="box" style={{ marginBottom: 0 }}>
      <div className="box-head">{label}</div>
      <div className="box-body">
        <div style={{ fontSize: "20px", fontWeight: "bold" }}>{value}</div>
      </div>
    </div>
  );
}
