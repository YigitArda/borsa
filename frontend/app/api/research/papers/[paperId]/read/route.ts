import { NextRequest, NextResponse } from "next/server";
import { fetchBackend } from "@/lib/server-backend";

async function proxyPost(path: string, init?: RequestInit, fallback?: unknown) {
  try {
    const response = await fetchBackend(path, init);
    if (response.ok) {
      const text = await response.text();
      const data = text ? JSON.parse(text) : fallback ?? { status: "ok" };
      return NextResponse.json(data, { status: response.status });
    }
  } catch {
    // Fallback below.
  }
  return NextResponse.json(fallback ?? { status: "ok" });
}

export async function POST(_: NextRequest, context: { params: Promise<{ paperId: string }> }) {
  const { paperId } = await context.params;
  return proxyPost(`/research/papers/${paperId}/read`, { method: "POST" }, { status: "ok", paper_id: Number(paperId) });
}
