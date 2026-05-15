"use client";

import { BarChart, Bar, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer, Cell } from "recharts";

interface Bucket {
  bucket: number;
  count: number;
}

export default function ReturnDistributionChart({ data }: { data: Bucket[] }) {
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
        <XAxis
          dataKey="bucket"
          tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
          tick={{ fill: "#94a3b8", fontSize: 10 }}
        />
        <YAxis tick={{ fill: "#94a3b8", fontSize: 10 }} />
        <Tooltip
          formatter={(value: number) => [value, "Count"]}
          labelFormatter={(v: number) => `Return ≈ ${(v * 100).toFixed(1)}%`}
          contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 6 }}
          labelStyle={{ color: "#94a3b8" }}
        />
        <ReferenceLine x={0} stroke="#64748b" strokeDasharray="3 3" />
        <Bar dataKey="count" radius={[2, 2, 0, 0]}>
          {data.map((entry, index) => (
            <Cell key={index} fill={entry.bucket >= 0 ? "#22c55e" : "#ef4444"} fillOpacity={0.7} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
