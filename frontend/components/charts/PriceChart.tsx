"use client";

import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

interface PriceRow {
  week_ending: string;
  close: number;
  weekly_return: number | null;
}

export default function PriceChart({ data }: { data: PriceRow[] }) {
  const formatted = data.map((d) => ({
    date: d.week_ending.slice(0, 10),
    close: d.close ? +d.close.toFixed(2) : null,
    return_pct: d.weekly_return != null ? +(d.weekly_return * 100).toFixed(2) : null,
  }));

  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={formatted} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} interval={12} />
        <YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} tickLine={false} axisLine={false} />
        <Tooltip
          contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: 6 }}
          labelStyle={{ color: "#94a3b8" }}
          itemStyle={{ color: "#60a5fa" }}
        />
        <Line type="monotone" dataKey="close" stroke="#60a5fa" dot={false} strokeWidth={2} />
      </LineChart>
    </ResponsiveContainer>
  );
}
