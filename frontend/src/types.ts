export type Status = { type: "idle" | "info" | "error"; message: string };

export type DashboardPage = "overview" | "signals" | "account" | "trading" | "strategy" | "admin";

export type DetailKind = "signal" | "log" | "position" | "account" | "decision" | "watcher" | "report" | "backtest";

export type DetailSelection = { title: string; kind: DetailKind; row: Record<string, unknown> };
