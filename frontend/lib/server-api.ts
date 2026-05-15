import { api } from "@/lib/api";

export type LoadResult<T> = {
  data: T | null;
  error: string | null;
};

export function formatApiError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "API request failed";
}

export async function loadApi<T>(path: string): Promise<LoadResult<T>> {
  try {
    return { data: await api.get<T>(path), error: null };
  } catch (error) {
    return { data: null, error: formatApiError(error) };
  }
}
