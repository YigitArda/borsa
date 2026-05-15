"use client";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from "recharts";

export default function EquityChart({ data }: { data: { date: string; equity: number; benchmark?: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} interval={12} />
        <YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} tickFormatter={(v) => `${((v - 1) * 100).toFixed(0)}%`} />
        <Tooltip
          contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: 6 }}
          formatter={(v: number) => [`${((v - 1) * 100).toFixed(2)}%`]}
        />
        <ReferenceLine y={1} stroke="#475569" strokeDasharray="4 4" />
        <Line type="monotone" dataKey="equity" stroke="#60a5fa" dot={false} strokeWidth={2} name="Strategy" />
        {data[0]?.benchmark !== undefined && (
          <Line type="monotone" dataKey="benchmark" stroke="#94a3b8" dot={false} strokeWidth={1.5} strokeDasharray="5 3" name="Benchmark (SPY)" />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}
