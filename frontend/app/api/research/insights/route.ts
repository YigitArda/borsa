import { NextRequest, NextResponse } from "next/server";
import { fetchBackend } from "@/lib/server-backend";

const EMPTY: unknown[] = [];

async function proxyGet(path: string) {
  try {
    const response = await fetchBackend(path);
    if (response.ok) {
      const text = await response.text();
      const data = text ? JSON.parse(text) : EMPTY;
      return NextResponse.json(data, { status: response.status });
    }
  } catch {
    // Fallback below.
  }
  return NextResponse.json(EMPTY);
}

export async function GET(request: NextRequest) {
  const search = request.nextUrl.search ?? "";
  return proxyGet(`/research/insights${search}`);
}
