import { api } from "@/lib/api";
import Link from "next/link";

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

async function getUsers(): Promise<User[]> {
  try { return await api.get<User[]>("/admin/users"); } catch { return []; }
}

async function getJobs(): Promise<JobRun[]> {
  try { return await api.get<JobRun[]>("/admin/jobs?limit=5"); } catch { return []; }
}

async function getStrategies(): Promise<Strategy[]> {
  try { return await api.get<Strategy[]>("/strategies?limit=5"); } catch { return []; }
}

async function getKillSwitch(): Promise<KillSwitchConfig | null> {
  try { return await api.get<KillSwitchConfig>("/admin/kill-switch"); } catch { return null; }
}

export default async function AdminDashboard() {
  const [users, jobs, strategies, killSwitch] = await Promise.all([
    getUsers(),
    getJobs(),
    getStrategies(),
    getKillSwitch(),
  ]);

  const activeJobs = jobs.filter((j) => j.status === "running").length;
  const failedJobs = jobs.filter((j) => j.status === "failed").length;
  const killSwitchEnabled = killSwitch?.enabled === "true";

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white mb-1">Admin Dashboard</h1>
        <p className="text-slate-400 text-sm">System overview and management.</p>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard label="Total Users" value={users.length} icon="users" />
        <StatCard label="Active Jobs" value={activeJobs} icon="jobs" />
        <StatCard label="Strategies" value={strategies.length} icon="strategies" />
        <StatCard
          label="Kill Switch"
          value={killSwitchEnabled ? "Active" : "Inactive"}
          icon="kill"
          highlight={killSwitchEnabled}
          highlightColor={killSwitchEnabled ? "text-red-400" : "text-green-400"}
        />
      </div>

      {failedJobs > 0 && (
        <div className="rounded-lg border border-red-700/40 bg-red-900/10 p-4 text-sm text-red-300">
          ⚠️ {failedJobs} job{failedJobs > 1 ? "s" : ""} failed recently. Check the{" "}
          <Link href="/admin/jobs" className="text-red-400 hover:underline font-medium">Jobs page</Link>.
        </div>
      )}

      {/* Quick Links */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { href: "/admin/jobs", label: "Manage Jobs", desc: "View and monitor pipeline jobs" },
          { href: "/admin/strategies", label: "Strategies", desc: "Review and archive strategies" },
          { href: "/admin/users", label: "Users", desc: "User accounts and roles" },
          { href: "/admin/notifications", label: "Notifications", desc: "Alert and email settings" },
        ].map((card) => (
          <Link key={card.href} href={card.href}>
            <div className="rounded-lg border border-slate-700 bg-slate-800 hover:border-blue-500 transition-colors p-5 cursor-pointer h-full">
              <div className="font-medium text-white">{card.label}</div>
              <div className="text-xs text-slate-400 mt-1">{card.desc}</div>
            </div>
          </Link>
        ))}
      </div>

      {/* Recent Jobs */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold text-white">Recent Jobs</h2>
          <Link href="/admin/jobs" className="text-sm text-blue-400 hover:underline">View all</Link>
        </div>
        {jobs.length === 0 ? (
          <div className="rounded-lg border border-slate-700 bg-slate-800 p-6 text-slate-400 text-sm">
            No jobs recorded yet.
          </div>
        ) : (
          <div className="rounded-lg border border-slate-700 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-800 text-slate-400">
                <tr>
                  <th className="px-4 py-3 text-left">Job</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3 text-left">Started</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id} className="border-t border-slate-700 hover:bg-slate-800/50">
                    <td className="px-4 py-3 text-white">{j.job_name}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={j.status} />
                    </td>
                    <td className="px-4 py-3 text-slate-400 font-mono text-xs">{j.started_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function StatCard({
  label,
  value,
  icon,
  highlight,
  highlightColor,
}: {
  label: string;
  value: string | number;
  icon: string;
  highlight?: boolean;
  highlightColor?: string;
}) {
  const iconMap: Record<string, string> = {
    users: "👥",
    jobs: "⚙️",
    strategies: "📊",
    kill: "🛑",
  };

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-5">
      <div className="flex items-center justify-between">
        <div className="text-sm text-slate-400">{label}</div>
        <div className="text-lg">{iconMap[icon] ?? "📋"}</div>
      </div>
      <div className={`text-2xl font-bold mt-2 ${highlight ? highlightColor : "text-white"}`}>
        {value}
      </div>
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
