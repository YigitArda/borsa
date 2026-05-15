const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`);
  return res.json();
}

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
  startResearch: (n_iterations: number = 150) => 
    post<{ task_id: string; status: string; n_iterations: number }>(`/strategies/research/start?n_iterations=${n_iterations}`),
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
export const api = { get, post };
