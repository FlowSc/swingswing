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
  telegram_chat_id?: string;
};

export type BrokerStatus = {
  configured: boolean;
  enabled: boolean;
  mode?: "paper" | "live";
  account_no?: string;
  account_product_code?: string;
  telegram_chat_id?: string;
};

export const api = {
  getBrokerStatus: (session: Session) => request<BrokerStatus>("/broker/kis/status", session),
  saveBroker: (session: Session, payload: BrokerPayload) =>
    request("/broker/kis", session, { method: "POST", body: JSON.stringify(payload) }),
  setBotEnabled: (session: Session, enabled: boolean) =>
    request("/bot/control", session, { method: "POST", body: JSON.stringify({ enabled }) }),
  scan: (session: Session) => request<{ trade_date: string; signals: number; saved: number }>("/bot/scan", session, { method: "POST" }),
  watchTick: (session: Session, payload: { test_mode: boolean; dry_run: boolean }) =>
    request("/bot/watch-tick", session, { method: "POST", body: JSON.stringify(payload) }),
  todaySignals: (session: Session) => request<Array<Record<string, unknown>>>("/signals/today", session),
  positions: (session: Session) => request<Array<Record<string, unknown>>>("/positions", session),
  tradeLogs: (session: Session) => request<Array<Record<string, unknown>>>("/trade-logs", session),
};
