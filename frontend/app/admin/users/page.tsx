"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface User {
  id: number;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

export default function UsersAdminPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);

  async function loadUsers() {
    setLoading(true);
    try {
      const data = await api.get<User[]>("/admin/users");
      setUsers(data);
    } catch {
      setUsers([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadUsers();
  }, []);

  return (
    <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
      <h1>User Management</h1>
      <p style={{ marginBottom: "10px", color: "#666", fontSize: "11px" }}>
        Inspect account status and user roles.
      </p>

      <div className="box">
        <div className="box-head">Controls</div>
        <div className="box-body">
          <button onClick={loadUsers} disabled={loading}>
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: "8px", margin: "12px 0" }}>
        <StatCard label="Users" value={users.length} />
        <StatCard label="Active" value={users.filter((u) => u.is_active).length} />
        <StatCard label="Inactive" value={users.filter((u) => !u.is_active).length} />
        <StatCard label="Roles" value={new Set(users.map((u) => u.role)).size} />
      </div>

      <div className="box">
        <div className="box-head">Users</div>
        <div className="box-body" style={{ padding: 0 }}>
          {users.length === 0 ? (
            <div style={{ padding: "12px", color: "#666" }}>
              {loading ? "Loading users..." : "No users found."}
            </div>
          ) : (
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td style={{ fontFamily: "monospace", fontSize: "10px" }}>{u.id}</td>
                    <td><b>{u.email}</b></td>
                    <td>
                      <span className="badge badge-info">{u.role}</span>
                    </td>
                    <td>
                      <span className={`badge ${u.is_active ? "badge-success" : "badge-danger"}`}>
                        {u.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td style={{ fontFamily: "monospace", fontSize: "10px" }}>{u.created_at}</td>
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
