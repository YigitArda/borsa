const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function readError(res: Response, path: string): Promise<string> {
  const text = await res.text();
  if (!text) {
    return `API error ${res.status}: ${path}`;
  }

  try {
    const data = JSON.parse(text) as { detail?: unknown; message?: unknown };
    if (typeof data.detail === "string" && data.detail.trim()) {
      return data.detail;
    }
    if (typeof data.message === "string" && data.message.trim()) {
      return data.message;
    }
  } catch {
    // Fall back to raw text below.
  }

  return text || `API error ${res.status}: ${path}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    cache: "no-store",
    headers: init?.headers,
  });
  if (!res.ok) throw new Error(await readError(res, path));
  return res.json();
}

async function requestLocal<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    cache: "no-store",
    headers: init?.headers,
  });
  if (!res.ok) throw new Error(await readError(res, path));
  return res.json();
}

async function get<T>(path: string): Promise<T> {
  return request<T>(path);
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

async function put<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

type ResearchStartRequest = {
  model_type?: string;
  target?: string;
  threshold?: number;
  top_n?: number;
  holding_weeks?: number;
  features?: string[];
  tickers?: string[];
  apply_liquidity_filter?: boolean;
};

// Pipeline endpoints
export const pipeline = {
  runAll: (tickers?: string[]) => post<{ task_id: string; status: string }>("/pipeline/run-all", tickers ? { tickers } : undefined),
  social: (tickers?: string[]) => post<{ task_id: string; status: string }>("/pipeline/social", tickers ? { tickers } : undefined),
  ingest: (tickers?: string[]) => post<{ task_id: string; status: string }>("/pipeline/ingest", tickers ? { tickers } : undefined),
  features: (tickers?: string[]) => post<{ task_id: string; status: string }>("/pipeline/features", tickers ? { tickers } : undefined),
};

// Strategy endpoints
export const strategies = {
  list: () => get<any[]>("/strategies"),
  startResearch: (n_iterations: number = 150, config: ResearchStartRequest = {}) =>
    post<{ task_id: string; status: string; n_iterations: number; features: number; tickers: number }>(
      `/strategies/research/start?n_iterations=${n_iterations}`,
      config,
    ),
  get: (id: number) => get<any>(`/strategies/${id}`),
  promote: (id: number) => post<any>(`/strategies/${id}/promote`),
};

// Backtest endpoints
export const backtest = {
  direct: (config: any) => post<any>("/backtest/direct", config),
  run: (config: any) => post<any>("/backtest/run", config),
  cpcv: (config: any) => post<any>("/backtest/cpcv", config),
  portfolio: (config: any) => post<any>("/backtest/portfolio", config),
};

// Research endpoints
export const research = {
  status: () => get<any>("/research/status"),
  featureImportance: (strategy_id: number) => get<any>(`/research/feature-importance/${strategy_id}`),
  walkForward: (strategy_id: number) => get<any>(`/research/walk-forward/${strategy_id}`),
  compare: (strategy_ids: string) => get<any>(`/research/compare?strategy_ids=${strategy_ids}`),
  riskWarnings: () => get<any>("/research/risk-warnings"),
  promotions: () => get<any>("/research/promotions"),
  rollingSharpe: (strategy_id: number) => get<any>(`/research/rolling-sharpe/${strategy_id}`),
  regimeAnalysis: (strategy_id: number) => get<any>(`/research/regime-analysis/${strategy_id}`),
  calibration: (strategy_id: number) => get<any>(`/research/calibration/${strategy_id}`),
  computeCalibration: (strategy_id: number) => post<any>(`/research/calibration/${strategy_id}/compute`),
  ablation: (strategy_id: number) => post<any>(`/research/ablation/${strategy_id}`),
  killSwitchStatus: () => get<any>("/research/kill-switch/status"),
};

// Weekly picks
export const weeklyPicks = {
  list: () => get<any>("/weekly-picks"),
  paper: () => get<any>("/weekly-picks/paper"),
  generate: () => post<any>("/weekly-picks/generate"),
};

// Data quality
export const dataQuality = {
  report: () => get<any>("/data-quality"),
  scores: () => get<any>("/data-quality/scores"),
  summary: () => get<any>("/data-quality/summary"),
};

export type NotificationSettings = {
  emailAlerts: boolean;
  slackWebhook: string;
  jobFailures: boolean;
  killSwitchTriggers: boolean;
  strategyPromotions: boolean;
  dailyDigest: boolean;
};

export const notifications = {
  getSettings: () => requestLocal<NotificationSettings>("/api/notifications/settings"),
  saveSettings: (settings: NotificationSettings) => requestLocal<NotificationSettings>("/api/notifications/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  }),
};

// ArXiv papers and research insights
export const arxiv = {
  papers: (limit: number = 30, unreadOnly: boolean = false) =>
    requestLocal<any[]>(`/api/research/papers?limit=${limit}&unread_only=${unreadOnly ? "true" : "false"}`),
  insights: (status?: string, limit: number = 50) =>
    requestLocal<any[]>(`/api/research/insights?limit=${limit}${status ? `&status=${encodeURIComponent(status)}` : ""}`),
  scan: (days: number = 7, maxResults: number = 50) =>
    requestLocal<any>(`/api/research/papers/scan?days=${days}&max_results=${maxResults}`, { method: "POST" }),
  extract: (limit: number = 10) =>
    requestLocal<any>(`/api/research/papers/extract?limit=${limit}`, { method: "POST" }),
  markRead: (paperId: number) =>
    requestLocal<any>(`/api/research/papers/${paperId}/read`, { method: "POST" }),
};

// Portfolio simulation
export const portfolioSimulation = {
  run: (config: any) => post<any>("/backtest/portfolio", config),
  get: (simulationId: number) => get<any>(`/backtest/portfolio/${simulationId}`),
  snapshots: (simulationId: number) => get<any>(`/backtest/portfolio/${simulationId}/snapshots`),
};

// Ablation analysis
export const ablation = {
  run: (strategyId: number) => post<any>(`/research/ablation/${strategyId}`),
  results: (strategyId: number) => get<any[]>(`/research/ablation/${strategyId}/results`),
  recommendations: (strategyId: number) => get<any>(`/research/ablation/${strategyId}/recommendations`),
};

// Jobs
export const jobs = {
  list: () => get<any>("/jobs"),
  running: () => get<any>("/jobs/running"),
  failed: () => get<any>("/jobs/failed"),
};

// Verification
export const verification = {
  status: () => get<any>("/verification/status"),
  full: () => get<any>("/verification"),
};

// Legacy generic API
export const api = { get, post, put };
