const BACKEND_BASE =
  process.env.BACKEND_API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000";

export async function fetchBackend(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${BACKEND_BASE}${path}`, {
    ...init,
    cache: "no-store",
    headers: init?.headers,
  });
}
