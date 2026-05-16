import { NextResponse } from "next/server";
import { fetchBackend } from "@/lib/server-backend";

const DEFAULT_SETTINGS = {
  emailAlerts: true,
  slackWebhook: "",
  jobFailures: true,
  killSwitchTriggers: true,
  strategyPromotions: false,
  dailyDigest: false,
};

async function proxyJson(path: string, init?: RequestInit, fallback?: unknown) {
  try {
    const response = await fetchBackend(path, init);
    if (response.ok) {
      const text = await response.text();
      const data = text ? JSON.parse(text) : fallback ?? DEFAULT_SETTINGS;
      return NextResponse.json(data, { status: response.status });
    }
  } catch {
    // Fall through to fallback payload.
  }
  return NextResponse.json(fallback ?? DEFAULT_SETTINGS);
}

export async function GET() {
  return proxyJson("/notifications/settings", undefined, DEFAULT_SETTINGS);
}

export async function PUT(request: Request) {
  const body = await request.json().catch(() => DEFAULT_SETTINGS);
  return proxyJson(
    "/notifications/settings",
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    body,
  );
}
