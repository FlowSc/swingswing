import type { Session } from "@supabase/supabase-js";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function request<T>(path: string, session: Session, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...options,
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${session.access_token}`,
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export type BrokerPayload = {
  kis_app_key: string;
  kis_app_secret: string;
  kis_account_no: string;
  kis_account_product_code: string;
  mode: "paper" | "live";
  live_order_enabled: boolean;
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

export type BrokerTestResult = {
  ok: boolean;
  error?: string;
  token_ok: boolean;
  quote_ok: boolean;
  balance_ok: boolean;
  telegram_ok: boolean;
  account: string;
  mode: string;
  quote_code: string;
  quote_price?: number;
  holdings_count?: number;
  cash?: number;
  total_equity?: number;
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
  status: "running" | "completed" | "failed";
  trade_date?: string;
  signals_count: number;
  shared_saved: number;
  error?: string;
  created_at: string;
  finished_at?: string;
};

export const api = {
  getBrokerStatus: (session: Session) => request<BrokerStatus>("/broker/kis/status", session),
  getBrokerAccounts: (session: Session) => request<BrokerAccount[]>("/broker/kis/accounts", session),
  saveBroker: (session: Session, payload: BrokerPayload) =>
    request("/broker/kis", session, { method: "POST", body: JSON.stringify(payload) }),
  activateBrokerAccount: (session: Session, accountId: string) =>
    request<BrokerAccount>(`/broker/kis/accounts/${accountId}/activate`, session, { method: "POST" }),
  testBroker: (session: Session) => request<BrokerTestResult>("/broker/kis/test", session, { method: "POST" }),
  getKisAccount: (session: Session) => request<KisAccount>("/broker/kis/account", session),
  setAutoTradingEnabled: (session: Session, enabled: boolean) =>
    request("/bot/control", session, { method: "POST", body: JSON.stringify({ enabled }) }),
  scan: (session: Session) => request<{ queued: boolean; scan_run_id: number; message: string }>("/bot/scan", session, { method: "POST" }),
  latestScanRun: (session: Session) => request<ScanRun | null>("/bot/scan-runs/latest", session),
  watchTick: (session: Session, payload: { test_mode: boolean; dry_run: boolean }) =>
    request("/bot/watch-tick", session, { method: "POST", body: JSON.stringify(payload) }),
  todaySignals: (session: Session) => request<Array<Record<string, unknown>>>("/signals/today", session),
  signalDates: (session: Session) => request<string[]>("/signals/dates", session),
  signalsByDate: (session: Session, tradeDate: string) => request<Array<Record<string, unknown>>>(`/signals?trade_date=${encodeURIComponent(tradeDate)}`, session),
  positions: (session: Session) => request<Array<Record<string, unknown>>>("/positions", session),
  tradeLogs: (session: Session) => request<Array<Record<string, unknown>>>("/trade-logs", session),
};
