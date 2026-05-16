import { NextRequest, NextResponse } from "next/server";
import { fetchBackend } from "@/lib/server-backend";

async function proxyPost(path: string, init?: RequestInit, fallback?: unknown) {
  try {
    const response = await fetchBackend(path, init);
    if (response.ok) {
      const text = await response.text();
      const data = text ? JSON.parse(text) : fallback ?? { status: "queued", task_id: "local-fallback" };
      return NextResponse.json(data, { status: response.status });
    }
  } catch {
    // Fallback below.
  }
  return NextResponse.json(fallback ?? { status: "queued", task_id: "local-fallback" });
}

export async function POST(request: NextRequest) {
  const search = request.nextUrl.search ?? "";
  return proxyPost(`/research/papers/extract${search}`, { method: "POST" });
}
