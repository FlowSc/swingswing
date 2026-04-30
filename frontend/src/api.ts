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

export type SignupPayload = {
  email: string;
  password: string;
  invite_code: string;
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
  scan_run_id: number;
  offset: number;
  total: number;
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
  days: number;
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
};

export const api = {
  signup: (payload: SignupPayload) =>
    publicRequest<{ ok: boolean; message: string; user_id?: string; email: string }>("/auth/signup", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getBrokerStatus: (session: Session) => request<BrokerStatus>("/broker/kis/status", session),
  getBrokerAccounts: (session: Session) => request<BrokerAccount[]>("/broker/kis/accounts", session),
  saveBroker: (session: Session, payload: BrokerPayload) =>
    request("/broker/kis", session, { method: "POST", body: JSON.stringify(payload) }),
  activateBrokerAccount: (session: Session, accountId: string) =>
    request<BrokerAccount>(`/broker/kis/accounts/${accountId}/activate`, session, { method: "POST" }),
  getKisAccount: (session: Session) => request<KisAccount>("/broker/kis/account", session),
  setAutoTradingEnabled: (session: Session, enabled: boolean) =>
    request("/bot/control", session, { method: "POST", body: JSON.stringify({ enabled }) }),
  getStrategy: (session: Session) => request<StrategySettings>("/bot/strategy", session),
  saveStrategy: (session: Session, payload: StrategySettings) =>
    request<StrategySettings>("/bot/strategy", session, { method: "PUT", body: JSON.stringify(payload) }),
  scan: (session: Session) => request<ScanStartResult>("/bot/scan", session, { method: "POST" }),
  scanStep: (session: Session, scanRunId: number) => request<ScanRun>(`/bot/scan-runs/${scanRunId}/step`, session, { method: "POST" }),
  latestScanRun: (session: Session) => request<ScanRun | null>("/bot/scan-runs/latest", session),
  sendDailyReport: (session: Session, tradeDate?: string) => {
    const suffix = tradeDate ? `?trade_date=${encodeURIComponent(tradeDate)}` : "";
    return request<{ sent: boolean; trade_date: string; signals: number }>(`/bot/reports/daily${suffix}`, session, { method: "POST" });
  },
  sendSignalReport: (session: Session, payload: { trade_date: string; code: string }) =>
    request<{ sent: boolean; trade_date: string; code: string; name?: string }>("/bot/reports/signal", session, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  watchTick: (session: Session, payload: { test_mode: boolean; dry_run: boolean }) =>
    request("/bot/watch-tick", session, { method: "POST", body: JSON.stringify(payload) }),
  todaySignals: (session: Session) => request<Array<Record<string, unknown>>>("/signals/today", session),
  signalDates: (session: Session) => request<string[]>("/signals/dates", session),
  signalsByDate: (session: Session, tradeDate: string) => request<Array<Record<string, unknown>>>(`/signals?trade_date=${encodeURIComponent(tradeDate)}`, session),
  positions: (session: Session) => request<Array<Record<string, unknown>>>("/positions", session),
  tradeLogs: (session: Session) => request<Array<Record<string, unknown>>>("/trade-logs", session),
  tradeDecisions: (session: Session, tradeDate?: string) => {
    const suffix = tradeDate ? `?trade_date=${encodeURIComponent(tradeDate)}` : "";
    return request<TradeDecisionLog[]>(`/trade-decisions${suffix}`, session);
  },
  dailyDashboard: (session: Session) => request<DailyDashboard>("/dashboard/daily", session),
  backtestSharedSignals: (session: Session, days = 120, maxSignals = 200) =>
    request<BacktestResult>(`/backtest/shared-signals?days=${days}&max_signals=${maxSignals}`, session),
};
