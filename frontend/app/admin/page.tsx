import Link from "next/link";
import { loadApi } from "@/lib/server-api";

interface User {
  id: number;
  email: string;
  role: string;
  is_active: boolean;
}

interface JobRun {
  id: number;
  job_name: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  error: string | null;
}

interface Strategy {
  id: number;
  name: string;
  status: string;
  generation: number;
  created_at: string;
}

interface KillSwitchConfig {
  enabled: string;
  max_paper_drawdown_pct: number;
  max_vix_level: number;
}

export default async function AdminDashboard() {
  const [usersResult, jobsResult, strategiesResult, killSwitchResult] = await Promise.all([
    loadApi<User[]>("/admin/users"),
    loadApi<JobRun[]>("/admin/jobs?limit=5"),
    loadApi<Strategy[]>("/strategies?limit=5"),
    loadApi<KillSwitchConfig>("/admin/kill-switch"),
  ]);

  const users = usersResult.data ?? [];
  const jobs = jobsResult.data ?? [];
  const strategies = strategiesResult.data ?? [];
  const killSwitch = killSwitchResult.data;
  const errors = [usersResult.error, jobsResult.error, strategiesResult.error, killSwitchResult.error].filter(Boolean) as string[];

  const activeJobs = jobs.filter((j) => j.status === "running").length;
  const failedJobs = jobs.filter((j) => j.status === "failed").length;
  const killSwitchEnabled = killSwitch?.enabled === "true";

  return (
    <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
      <h1>Admin Dashboard</h1>
      <p style={{ marginBottom: "10px", color: "#666", fontSize: "11px" }}>
        System overview, recent jobs and control panel shortcuts.
      </p>

      {errors.length > 0 && (
        <div className="alert alert-warning">
          Some admin data could not be loaded: {errors.join(" · ")}
        </div>
      )}

      {killSwitchEnabled && (
        <div className="alert alert-danger">
          Kill switch is active. Paper trading or signal generation may be blocked.
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: "8px", marginBottom: "12px" }}>
        <StatCard label="Users" value={users.length} />
        <StatCard label="Active Jobs" value={activeJobs} />
        <StatCard label="Strategies" value={strategies.length} />
        <StatCard label="Kill Switch" value={killSwitchEnabled ? "Active" : "Inactive"} highlight={killSwitchEnabled} />
      </div>

      {failedJobs > 0 && (
        <div className="alert alert-danger">
          {failedJobs} job{failedJobs > 1 ? "s" : ""} failed recently. Check the{" "}
          <Link href="/admin/jobs" prefetch={false}>Jobs page</Link>.
        </div>
      )}

      <div className="box">
        <div className="box-head">Shortcuts</div>
        <div className="box-body">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: "8px" }}>
            {[
              { href: "/admin/jobs", label: "Manage Jobs", desc: "View and monitor pipeline jobs" },
              { href: "/admin/strategies", label: "Strategies", desc: "Review and archive strategies" },
              { href: "/admin/users", label: "Users", desc: "User accounts and roles" },
              { href: "/admin/notifications", label: "Notifications", desc: "Alert and email settings" },
            ].map((card) => (
              <Link
                key={card.href}
                href={card.href}
                prefetch={false}
                className="box"
                style={{ textDecoration: "none", marginBottom: 0, display: "block" }}
              >
                <div className="box-head">{card.label}</div>
                <div className="box-body" style={{ minHeight: "72px" }}>
                  <div style={{ color: "#000" }}>{card.desc}</div>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </div>

      <div className="box" style={{ marginTop: "12px" }}>
        <div className="box-head">Recent Jobs</div>
        <div className="box-body" style={{ padding: 0 }}>
          {jobs.length === 0 ? (
            <div style={{ padding: "12px", color: "#666" }}>No jobs recorded yet.</div>
          ) : (
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th>Job</th>
                  <th>Status</th>
                  <th>Started</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id}>
                    <td>{j.job_name}</td>
                    <td>
                      <StatusBadge status={j.status} />
                    </td>
                    <td style={{ fontFamily: "monospace", fontSize: "10px" }}>{j.started_at}</td>
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

function StatCard({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string | number;
  highlight?: boolean;
}) {
  return (
    <div className="box" style={{ marginBottom: 0 }}>
      <div className="box-head">{label}</div>
      <div className="box-body">
        <div style={{ fontSize: "20px", fontWeight: "bold", color: highlight ? "#cc0000" : "#000" }}>
          {value}
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
  const badgeClass = colorMap[status] ?? "badge-info";
  return <span className={`badge ${badgeClass}`}>{status}</span>;
}
