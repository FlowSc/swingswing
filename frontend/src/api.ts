import type { Session } from "@supabase/supabase-js";
import { supabase } from "./supabase";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function publicRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...options,
    headers: {
      "content-type": "application/json",
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function request<T>(path: string, session: Session, options: RequestInit = {}): Promise<T> {
  const token = await currentAccessToken(session);
  let response = await fetchWithToken(path, token, options);
  if (response.status === 401) {
    const refreshed = await refreshedAccessToken();
    response = await fetchWithToken(path, refreshed, options);
  }

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

async function currentAccessToken(fallbackSession: Session): Promise<string> {
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token || fallbackSession.access_token;
}

async function refreshedAccessToken(): Promise<string> {
  const { data, error } = await supabase.auth.refreshSession();
  if (error || !data.session?.access_token) {
    throw new Error(error?.message || "Supabase session refresh failed.");
  }
  return data.session.access_token;
}

async function fetchWithToken(path: string, accessToken: string, options: RequestInit): Promise<Response> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...options,
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${accessToken}`,
      ...(options.headers || {}),
    },
  });
  return response;
}

export type BrokerPayload = {
  kis_app_key: string;
  kis_app_secret: string;
  kis_account_no: string;
  kis_account_product_code: string;
  mode: "paper" | "live";
  live_order_enabled: boolean;
};

export type TelegramSettingsPayload = {
  telegram_bot_token?: string;
  telegram_chat_id?: string;
};

export type SignupPayload = {
  email: string;
  password: string;
};

export type MembershipRole = "admin" | "free" | "paid";

export type Entitlements = {
  user_id: string;
  email?: string | null;
  role: MembershipRole;
  paid_until?: string | null;
  report_enabled: boolean;
  can_use_paper_trading: boolean;
  can_use_live_trading: boolean;
  can_use_reports: boolean;
  can_run_admin_scan: boolean;
  can_run_backtest: boolean;
};

export type BrokerStatus = {
  configured: boolean;
  id?: string;
  label?: string;
  enabled: boolean;
  mode?: "paper" | "live";
  account_no?: string;
  account_product_code?: string;
  telegram_configured: boolean;
  telegram_chat_id?: string;
  live_order_enabled: boolean;
  server_live_trading_allowed: boolean;
  is_active: boolean;
};

export type BrokerAccount = {
  id: string;
  user_id: string;
  label?: string;
  kis_account_no: string;
  kis_account_product_code: string;
  mode: "paper" | "live";
  telegram_configured: boolean;
  telegram_chat_id?: string;
  enabled: boolean;
  live_order_enabled: boolean;
  server_live_trading_allowed: boolean;
  is_active: boolean;
};

export type KisHolding = {
  code: string;
  name?: string;
  qty: number;
  avg_price?: number;
  current_price?: number;
  evaluation_amount?: number;
  profit_loss?: number;
  profit_loss_rate?: number;
};

export type KisAccount = {
  ok: boolean;
  error?: string;
  account: string;
  mode: string;
  cash?: number;
  orderable_cash?: number;
  total_equity?: number;
  holdings_count: number;
  holdings: KisHolding[];
};

export type ScanRun = {
  id: number;
  status: "queued" | "running" | "completed" | "failed";
  trade_date?: string;
  signals_count?: number;
  shared_saved?: number;
  error?: string;
  created_at: string;
  finished_at?: string;
  result?: {
    offset?: number;
    total?: number;
    candidates?: unknown[];
    done?: boolean;
  };
};

export type ScanStartResult = {
  queued: boolean;
  skipped?: boolean;
  reason?: string;
  trade_date?: string;
  scan_run_id?: number;
  offset?: number;
  total?: number;
  message: string;
};

export type TradeDecisionLog = {
  id: number;
  decision_date: string;
  decision: "BUY" | "SKIP" | string;
  code: string;
  name?: string;
  price?: number;
  score?: number;
  reason_code: string;
  reason: string;
  raw?: Record<string, unknown>;
  created_at: string;
};

export type WatcherRun = {
  id: number;
  user_id: string;
  broker_account_id?: string | null;
  mode?: string | null;
  orders_allowed: boolean;
  entry_window_open: boolean;
  manage_window_open: boolean;
  cash?: number | null;
  total_equity?: number | null;
  signals_count: number;
  open_positions_count: number;
  kis_holdings_count: number;
  pending_orders_count: number;
  today_entry_count?: number;
  orderable_cash?: number | null;
  today_pending_buy_count?: number;
  remaining_daily_slots?: number | null;
  available_slots?: number | null;
  affordable_slots?: number | null;
  daily_slots?: number | null;
  action_count: number;
  buy_order_count: number;
  sell_order_count: number;
  cooldown_skip_count?: number;
  skip_reason?: string | null;
  raw?: Record<string, unknown>;
  created_at: string;
};

export type WatchJob = {
  id: number;
  job_type: "intraday" | "realtime_position" | string;
  user_id: string;
  broker_account_id: string;
  account_label?: string | null;
  account_mode?: "paper" | "live" | string;
  account_no?: string | null;
  account_product_code?: string | null;
  account_display?: string | null;
  account_enabled?: boolean;
  account_is_active?: boolean;
  account_live_order_enabled?: boolean;
  status: "pending" | "running" | "completed" | "failed" | "skipped" | string;
  scheduled_for: string;
  run_after: string;
  attempts: number;
  locked_by?: string | null;
  locked_until?: string | null;
  error?: string | null;
  result?: Record<string, unknown>;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
};

export type WatchJobOverview = {
  status_counts: Record<string, number>;
  type_counts: Record<string, number>;
  oldest_pending_seconds?: number | null;
  running_overdue: number;
  failures: Array<{ reason: string; count: number }>;
  jobs: WatchJob[];
};

export type DailyDashboard = {
  date: string;
  signals_count: number;
  open_positions: number;
  buy_count: number;
  sell_count: number;
  skip_count: number;
  latest_scan?: ScanRun | null;
  top_skip_reasons: Array<{
    reason_code: string;
    reason: string;
    count: number;
  }>;
};

export type DailyDiagnostics = {
  trade_date: string;
  signals_count: number;
  forward_count: number;
  scan?: ScanRun | null;
  reject_counts: Array<{
    reason_code: string;
    reason: string;
    count: number;
  }>;
  top_market_cap_analysis: Array<Record<string, unknown>>;
  score_buckets: Array<Record<string, unknown>>;
  forward_returns: Array<Record<string, unknown>>;
};

export type BacktestTrade = {
  trade_date: string;
  entry_date: string;
  code: string;
  name?: string;
  score?: number;
  entry: number;
  exit_price: number;
  return_pct: number;
  hold_days: number;
  exit_reason: string;
};

export type BacktestResult = {
  source?: string;
  days: number;
  generated_signals?: number;
  skipped_symbols?: number;
  error?: string;
  signals_tested: number;
  win_count: number;
  loss_count: number;
  win_rate: number;
  avg_return_pct: number;
  avg_win_pct: number;
  avg_loss_pct: number;
  best_return_pct: number;
  worst_return_pct: number;
  avg_hold_days: number;
  trades: BacktestTrade[];
};

export type BacktestJob = {
  job_id: string;
  run_id?: number;
  status: "running" | "completed" | "failed" | "not_found";
  days?: number;
  max_signals?: number;
  source?: string;
  strategy_key?: string;
  strategy_version?: string;
  start_date?: string;
  end_date?: string;
  universe_scope?: string;
  progress?: {
    processed?: number;
    total?: number;
    signals?: number;
    skipped?: number;
    tested?: number;
  };
  result?: BacktestResult | null;
  error?: string | null;
  created_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
  completed_at?: string | null;
};

export type AiReportType = "daily" | "signal" | "daily_blog" | "signal_blog";

export type AiReport = {
  id: number;
  trade_date: string;
  report_type: AiReportType;
  code: string;
  name?: string | null;
  title: string;
  status: "queued" | "running" | "completed" | "failed";
  markdown?: string;
  html?: string;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
};

export type AiReportStatus = Omit<AiReport, "markdown" | "html">;

export type StrategyPreset = "conservative" | "balanced" | "aggressive";

export type StrategySettings = {
  user_id?: string;
  preset: StrategyPreset;
  min_score: number;
  max_open_positions: number;
  max_new_positions_per_day: number;
  position_capital_pct: number;
  risk_per_trade_pct: number;
  min_order_amount: number;
  min_entry_discount: number;
  max_entry_premium: number;
  max_pullback_from_day_high: number;
  use_kijun_filter: boolean;
  use_bb_upper_filter: boolean;
  use_day_candle_filter: boolean;
  use_breakeven_after_tp1: boolean;
  use_kijun_exit: boolean;
  use_kijun_reentry_block: boolean;
  use_daily_loss_limit: boolean;
  daily_loss_limit_pct: number;
  use_unrealized_loss_limit: boolean;
  unrealized_loss_limit_pct: number;
  use_market_crash_filter: boolean;
  market_crash_limit_pct: number;
  commission_tax_pct: number;
  use_realtime_liquidity_filter: boolean;
  min_realtime_strength: number;
  min_bid_ask_ratio: number;
  max_realtime_spread_pct: number;
  use_stoploss_reentry_block: boolean;
  use_vi_filter: boolean;
};

export const api = {
  signup: (payload: SignupPayload) =>
    publicRequest<{ ok: boolean; message: string; user_id?: string; email: string }>("/auth/signup", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getEntitlements: (session: Session) => request<Entitlements>("/auth/me/entitlements", session),
  getBrokerStatus: (session: Session) => request<BrokerStatus>("/broker/kis/status", session),
  getBrokerAccounts: (session: Session) => request<BrokerAccount[]>("/broker/kis/accounts", session),
  saveBroker: (session: Session, payload: BrokerPayload) =>
    request("/broker/kis", session, { method: "POST", body: JSON.stringify(payload) }),
  saveTelegramSettings: (session: Session, payload: TelegramSettingsPayload) =>
    request<BrokerAccount>("/broker/telegram", session, { method: "PUT", body: JSON.stringify(payload) }),
  activateBrokerAccount: (session: Session, accountId: string) =>
    request<BrokerAccount>(`/broker/kis/accounts/${accountId}/activate`, session, { method: "POST" }),
  getKisAccount: (session: Session) => request<KisAccount>("/broker/kis/account", session),
  setAutoTradingEnabled: (session: Session, enabled: boolean) =>
    request("/bot/control", session, { method: "POST", body: JSON.stringify({ enabled }) }),
  getStrategy: (session: Session) => request<StrategySettings>("/bot/strategy", session),
  saveStrategy: (session: Session, payload: StrategySettings) =>
    request<StrategySettings>("/bot/strategy", session, { method: "PUT", body: JSON.stringify(payload) }),
  scan: (session: Session, universeScope: "limited" | "all" = "all") =>
    request<ScanStartResult>(`/bot/scan?universe_scope=${encodeURIComponent(universeScope)}`, session, { method: "POST" }),
  scanStep: (session: Session, scanRunId: number) => request<ScanRun>(`/bot/scan-runs/${scanRunId}/step`, session, { method: "POST" }),
  latestScanRun: (session: Session) => request<ScanRun | null>("/bot/scan-runs/latest", session),
  sendSharedTelegramNotice: (session: Session, message: string) =>
    request<{ sent: boolean; message: string }>("/bot/telegram/shared-notice", session, { method: "POST", body: JSON.stringify({ message }) }),
  watchJobOverview: (session: Session) => request<WatchJobOverview>("/bot/watch-jobs", session),
  retryFailedWatchJobs: (session: Session, jobType?: "intraday" | "realtime_position") =>
    request<{ retried: number; job_type: string }>("/bot/watch-jobs/retry-failed", session, {
      method: "POST",
      body: JSON.stringify({ job_type: jobType || null }),
    }),
  sendDailyReport: (session: Session, tradeDate?: string, reportStyle: "report" | "blog" = "report") => {
    const params = new URLSearchParams({ report_style: reportStyle });
    if (tradeDate) params.set("trade_date", tradeDate);
    const suffix = `?${params.toString()}`;
    return request<{ queued: boolean; trade_date: string; signals: number; stage?: string; error?: string | null; report_id?: number; title?: string }>(`/bot/reports/daily${suffix}`, session, { method: "POST" });
  },
  sendSignalReport: (session: Session, payload: { trade_date: string; code: string; report_style?: "report" | "blog" }) =>
    request<{ queued: boolean; trade_date: string; code: string; name?: string; stage?: string; error?: string | null; report_id?: number; title?: string }>(`/bot/reports/signal?report_style=${encodeURIComponent(payload.report_style || "report")}`, session, {
      method: "POST",
      body: JSON.stringify({ trade_date: payload.trade_date, code: payload.code }),
    }),
  getAiReport: (session: Session, payload: { trade_date: string; report_type: AiReportType; code?: string }) => {
    const params = new URLSearchParams({ trade_date: payload.trade_date, report_type: payload.report_type });
    if (payload.code) params.set("code", payload.code);
    return request<AiReport>(`/bot/reports?${params.toString()}`, session);
  },
  getAiReportStatuses: (session: Session, tradeDate: string) =>
    request<AiReportStatus[]>(`/bot/reports/status?trade_date=${encodeURIComponent(tradeDate)}`, session),
  getAiReportDates: (session: Session) => request<string[]>("/bot/reports/dates", session),
  watchTick: (session: Session, payload: { test_mode: boolean; dry_run: boolean }) =>
    request("/bot/watch-tick", session, { method: "POST", body: JSON.stringify(payload) }),
  forceLiquidatePosition: (session: Session, code: string, dryRun = false) =>
    request(`/bot/positions/${encodeURIComponent(code)}/force-liquidate`, session, { method: "POST", body: JSON.stringify({ dry_run: dryRun }) }),
  todaySignals: (session: Session) => request<Array<Record<string, unknown>>>("/signals/today", session),
  signalDates: (session: Session) => request<string[]>("/signals/dates", session),
  signalsByDate: (session: Session, tradeDate: string) => request<Array<Record<string, unknown>>>(`/signals?trade_date=${encodeURIComponent(tradeDate)}`, session),
  blockSignalAutoBuy: (session: Session, payload: { trade_date: string; code: string; reason?: string }) =>
    request<{ blocked: boolean; signal?: Record<string, unknown>; block?: Record<string, unknown> }>(
      `/signals/${encodeURIComponent(payload.trade_date)}/${encodeURIComponent(payload.code)}/auto-buy-block`,
      session,
      { method: "POST", body: JSON.stringify({ reason: payload.reason || "관리자 매수 금지" }) },
    ),
  unblockSignalAutoBuy: (session: Session, payload: { trade_date: string; code: string }) =>
    request<{ blocked: boolean; trade_date: string; code: string }>(
      `/signals/${encodeURIComponent(payload.trade_date)}/${encodeURIComponent(payload.code)}/auto-buy-block`,
      session,
      { method: "DELETE" },
    ),
  positions: (session: Session) => request<Array<Record<string, unknown>>>("/positions", session),
  tradeLogs: (session: Session) => request<Array<Record<string, unknown>>>("/trade-logs", session),
  tradeDecisions: (session: Session, tradeDate?: string) => {
    const suffix = tradeDate ? `?trade_date=${encodeURIComponent(tradeDate)}` : "";
    return request<TradeDecisionLog[]>(`/trade-decisions${suffix}`, session);
  },
  watcherRuns: (session: Session) => request<WatcherRun[]>("/watcher-runs", session),
  dailyDashboard: (session: Session) => request<DailyDashboard>("/dashboard/daily", session),
  dailyDiagnostics: (session: Session, tradeDate: string) =>
    request<DailyDiagnostics>(`/diagnostics/daily?trade_date=${encodeURIComponent(tradeDate)}`, session),
  backtestSharedSignals: (session: Session, days = 120, maxSignals = 200) =>
    request<BacktestResult>(`/backtest/shared-signals?days=${days}&max_signals=${maxSignals}`, session),
  startHistoricalBacktest: (session: Session, days = 120, maxSignals = 200) =>
    request<BacktestJob>(`/backtest/historical/start?days=${days}&max_signals=${maxSignals}`, session, { method: "POST" }),
  stepHistoricalBacktest: (session: Session, runId: number | string) =>
    request<BacktestJob>(`/backtest/historical/runs/${encodeURIComponent(String(runId))}/step`, session, { method: "POST" }),
  getHistoricalBacktestJob: (session: Session, jobId: string) =>
    request<BacktestJob>(`/backtest/historical/jobs/${encodeURIComponent(jobId)}`, session),
  historicalBacktestRuns: (session: Session) => request<BacktestJob[]>("/backtest/historical/runs", session),
  historicalBacktestTrades: (session: Session, runId: number | string) =>
    request<Array<Record<string, unknown>>>(`/backtest/historical/runs/${encodeURIComponent(String(runId))}/trades`, session),
};
