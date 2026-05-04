import type { AiReport, AiReportStatus, AiReportType, StrategyPreset, TradeDecisionLog, WatcherRun } from "../api";

export function formatPct(value: number) {
  const rounded = (value * 100).toFixed(1).replace(/\.0$/, "");
  return `${rounded}%`;
}

export function hasCompletedReport(reports: AiReportStatus[], reportType: AiReportType, code?: string) {
  return reports.some((report) => {
    if (report.report_type !== reportType || report.status !== "completed") return false;
    if (reportType === "daily" || reportType === "daily_blog") return report.code === "ALL";
    return report.code === code;
  });
}

export function formatCell(value: unknown) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") return value.toLocaleString("ko-KR");
  return String(value);
}

export function formatMarketCap(value: unknown) {
  const numeric = numericValue(value);
  if (numeric === null || numeric <= 0) return formatCell(value);
  const trillion = Math.floor(numeric / 1_000_000_000_000);
  const hundredMillion = Math.round((numeric % 1_000_000_000_000) / 100_000_000);
  if (trillion > 0 && hundredMillion > 0) return `${trillion}조 ${hundredMillion.toLocaleString("ko-KR")}억 원`;
  if (trillion > 0) return `${trillion}조 원`;
  return `${Math.round(numeric / 100_000_000).toLocaleString("ko-KR")}억 원`;
}

export function numericValue(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(String(value).replace(/,/g, ""));
  return Number.isFinite(parsed) ? parsed : null;
}

export function percentFromEntry(target: unknown, entry: unknown): number | null {
  const targetValue = numericValue(target);
  const entryValue = numericValue(entry);
  if (targetValue === null || entryValue === null || entryValue <= 0) return null;
  return (targetValue / entryValue - 1) * 100;
}

export function formatPlanPct(value: unknown): string {
  const numeric = numericValue(value);
  if (numeric === null) return "";
  const sign = numeric > 0 ? "+" : "";
  return `${sign}${numeric.toFixed(2)}%`;
}

export function formatPercentFromEntry(target: unknown, entry: unknown): string {
  const percent = percentFromEntry(target, entry);
  return percent === null ? "-" : formatPlanPct(percent);
}

export function buildStopLossExplanation(row: Record<string, unknown>, raw: Record<string, unknown>) {
  const stopPct = formatPercentFromEntry(row.stop_loss, row.entry);
  const atrPct = raw["ATR(%)"] === undefined ? "-" : `${formatCell(raw["ATR(%)"])}%`;
  return `최근 10거래일 저점과 60일선 중 더 낮은 지지선에서 1% 아래로 설정. 현재 손절폭 ${stopPct}, ATR 변동성 ${atrPct}.`;
}

export function buildTakeProfitExplanation(row: Record<string, unknown>) {
  const riskPct = formatRiskPct(row.entry, row.stop_loss);
  const tp1Pct = formatPercentFromEntry(row.take_profit_1, row.entry);
  const tp2Pct = formatPercentFromEntry(row.take_profit_2, row.entry);
  return `진입가와 손절가 사이의 리스크를 1R로 보고, 1차 익절은 +1R(${tp1Pct}), 2차 익절은 +2R(${tp2Pct})로 설정. 기준 리스크는 ${riskPct}.`;
}

export function formatRiskPct(entry: unknown, stopLoss: unknown) {
  const entryValue = numericValue(entry);
  const stopValue = numericValue(stopLoss);
  if (entryValue === null || stopValue === null || entryValue <= 0) return "-";
  return `${Math.max(0, (entryValue - stopValue) / entryValue * 100).toFixed(2)}%`;
}

export function formatOrderPolicy(value: unknown): string {
  const policy = asRecord(value);
  const type = String(policy.type || "");
  if (type === "aggressive_stop_limit") {
    return `손절 공격적 지정가: 기준가보다 ${formatCell(policy.slippage_ticks)}틱 낮게 주문`;
  }
  if (type === "best_bid_limit") {
    return "일반 지정가: 최우선 매수호가 기준";
  }
  return "-";
}

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function normalizeTradeLogRow(row: Record<string, unknown>) {
  return {
    ...row,
    action_ko: row.action === "BUY" ? "매수" : row.action === "SELL" ? "매도" : row.action,
    reason_ko: translateReason(row.reason),
    created_at: formatDateTime(row.created_at),
  };
}

export function enrichPlanPercentRow(row: Record<string, unknown>) {
  const raw = asRecord(row.raw);
  const exitPlan = asRecord(raw.exit_plan);
  const entry = row.entry_price ?? row.entry ?? exitPlan.entry_price;
  const stopLoss = row.stop_loss ?? exitPlan.stop_loss ?? raw.StopLoss;
  const takeProfit1 = row.take_profit_1 ?? exitPlan.take_profit_1 ?? raw.TakeProfit1;
  const takeProfit2 = row.take_profit_2 ?? exitPlan.take_profit_2 ?? raw.TakeProfit2;
  const trailingStop = row.trailing_stop ?? exitPlan.trailing_stop ?? raw.TrailingStop;
  return {
    ...row,
    핵심군: isCoreUniverseSignal(raw) ? translateCoreUniverse(raw.CoreUniverseType) : "전종목",
    stop_loss_pct: formatPlanPct(exitPlan.stop_loss_pct) || formatPercentFromEntry(stopLoss, entry),
    take_profit_1_pct: formatPlanPct(exitPlan.take_profit_1_pct) || formatPercentFromEntry(takeProfit1, entry),
    take_profit_2_pct: formatPlanPct(exitPlan.take_profit_2_pct) || formatPercentFromEntry(takeProfit2, entry),
    trailing_stop_pct: formatPlanPct(exitPlan.trailing_stop_pct) || formatPercentFromEntry(trailingStop, entry),
  };
}

export function normalizeDecisionRow(row: TradeDecisionLog): Record<string, unknown> {
  return {
    ...row,
    reason: row.reason || translateReason(row.reason_code),
    created_at: formatDateTime(row.created_at),
  };
}

export function normalizeWatcherRunRow(row: WatcherRun): Record<string, unknown> {
  return {
    ...row,
    orders_allowed_ko: row.orders_allowed ? "허용" : "차단",
    skip_reason_ko: translateWatcherSkipReason(row.skip_reason),
    created_at: formatDateTime(row.created_at),
  };
}

export function latestWatcherIssue(rows: WatcherRun[]): Record<string, unknown> | null {
  for (const row of rows) {
    const raw = asRecord(row.raw);
    const hasError = row.skip_reason === "watcher_error" || Boolean(raw.error);
    if (!hasError) continue;
    const normalized = normalizeWatcherRunRow(row);
    return {
      ...normalized,
      reason: normalized.skip_reason_ko || "와쳐 실행 오류",
      error: raw.error || normalized.skip_reason_ko,
    };
  }
  return null;
}

export function normalizeAiReportStatusRow(row: AiReportStatus): Record<string, unknown> {
  return {
    ...row,
    report_kind_ko: translateReportType(row.report_type),
    status_ko: translateReportStatus(row.status),
    created_at: formatDateTime(row.created_at),
    started_at: formatDateTime(row.started_at),
    finished_at: formatDateTime(row.finished_at),
    error: row.error || "",
  };
}

export function enrichTradeLogRow(
  row: Record<string, unknown>,
  positions: Array<Record<string, unknown>>,
  signals: Array<Record<string, unknown>>,
) {
  const raw = asRecord(row.raw);
  if (raw.exit_plan) return row;

  const code = String(row.code || "");
  const matchingPosition = positions.find((position) => String(position.code || "") === code);
  const matchingSignal = signals.find((signal) => String(signal.code || "") === code);
  const fallbackPlan = exitPlanFromSource(matchingPosition || matchingSignal || row);

  return {
    ...row,
    raw: {
      ...raw,
      exit_plan: fallbackPlan,
    },
  };
}

export function exitPlanFromSource(source?: Record<string, unknown>) {
  const row = source || {};
  const raw = asRecord(row.raw);
  return {
    entry_price: row.entry_price ?? row.entry,
    stop_loss: row.stop_loss ?? raw.StopLoss,
    stop_loss_pct: percentFromEntry(row.stop_loss ?? raw.StopLoss, row.entry_price ?? row.entry),
    take_profit_1: row.take_profit_1 ?? raw.TakeProfit1,
    take_profit_1_pct: percentFromEntry(row.take_profit_1 ?? raw.TakeProfit1, row.entry_price ?? row.entry),
    take_profit_2: row.take_profit_2 ?? raw.TakeProfit2,
    take_profit_2_pct: percentFromEntry(row.take_profit_2 ?? raw.TakeProfit2, row.entry_price ?? row.entry),
    trailing_stop: row.trailing_stop ?? raw.TrailingStop,
    trailing_stop_pct: percentFromEntry(row.trailing_stop ?? raw.TrailingStop, row.entry_price ?? row.entry),
    hold_min_days: raw.HoldMinDays,
    hold_preferred_days: raw.HoldPreferredDays,
    hold_max_days: raw.HoldMaxDays || 15,
    planned_entry_window: "14:30-15:20",
    planned_manage_window: "09:00-15:20",
  };
}

export function translateReason(reason: unknown) {
  const value = String(reason || "");
  const map: Record<string, string> = {
    IntradayEntry: "장중 진입 조건 충족",
    StopLoss: "손절가 도달",
    StopLossAfterTakeProfit: "익절 후 잔량 손절",
    StopLossRepriced: "손절 미체결 재주문",
    StopLossMarketExit: "손절 최종 시장가 탈출",
    TrailingStop: "추적 손절가 도달",
    TimeExit: "최대 보유기간 도달",
    MaxHold: "최대 보유 후 청산",
    MaxHoldAfterTakeProfit: "익절 후 최대 보유 청산",
    DataEnd: "백테스트 데이터 종료 청산",
    TakeProfit1: "1차 익절가 도달",
    TakeProfit2: "2차 익절가 도달",
    AlreadyHeld: "이미 보유 중인 종목",
    ScoreBelowMinimum: "전략 최소 점수 미달",
    BelowEntryBand: "현재가가 진입 허용 하단보다 낮음",
    AboveEntryBand: "현재가가 진입 허용 상단보다 높음",
    BelowKijun: "현재가가 일목 기준선 아래",
    KijunExit: "일목 기준선 이탈",
    KijunExitedToday: "당일 기준선 이탈 매도 종목 재진입 금지",
    AboveBBUpper: "현재가가 볼린저 상단 위",
    PulledBackFromDayHigh: "당일 고점 대비 과도하게 밀림",
    StoppedOutToday: "당일 손절 종목 재매수 금지",
    VolatilityInterruption: "VI 발동 종목 매수 차단",
    RealtimeStrengthWeak: "실시간 체결강도 약함",
    RealtimeBidDepthWeak: "실시간 매수 호가잔량 약함",
    RealtimeSpreadWide: "실시간 호가 스프레드 과다",
    RealtimeCheckFailed: "실시간 체결/호가 확인 실패",
    OrderFilled: "주문/계좌 기준 체결 확인",
    OrderPending: "주문 접수 후 체결 대기",
    QuoteFailed: "현재가 조회 실패",
    InvalidQuote: "현재가 값 비정상",
    SizingRejected: "수량/리스크/최소주문금액 조건 미충족",
    SizingRiskBudgetTooSmall: "리스크 허용손실이 너무 작음",
    SizingCapitalTooSmall: "현금/종목당 배정금액 부족",
    SizingBelowMinOrder: "계산 주문금액이 최소 주문금액 미만",
    SizingInvalidPrice: "진입가 또는 손절가 비정상",
    OrderableCashExceeded: "주문가능금액 초과",
    StrategySellCooldown: "매수 직후 전략 매도 쿨다운",
    UnrealizedLossLimit: "미실현손실 한도 도달",
  };
  return map[value] || value || "-";
}

export function translateWatcherSkipReason(reason: unknown) {
  const value = String(reason || "");
  const map: Record<string, string> = {
    outside_entry_window: "매수 시간대 아님",
    no_shared_signals: "오늘 시그널 없음",
    no_buy_slots: "매수 가능 슬롯 없음",
    no_buy_order_created: "조건 충족 종목 없음",
    watcher_error: "와쳐 실행 오류",
    daily_loss_limit: "하루 손실 한도 도달",
    unrealized_loss_limit: "미실현손실 한도 도달",
    market_crash_filter: "시장 급락 신규 매수 차단",
    completed: "실행 완료",
  };
  return map[value] || value || "-";
}

export function translateReportType(type: unknown) {
  const value = String(type || "");
  const map: Record<string, string> = {
    daily: "종합 리포트",
    signal: "개별 리포트",
    daily_blog: "종합 블로그",
    signal_blog: "개별 블로그",
  };
  return map[value] || value || "-";
}

export function translateReportStatus(status: unknown) {
  const value = String(status || "");
  const map: Record<string, string> = {
    queued: "대기 중",
    running: "작성 중",
    completed: "완료",
    failed: "실패",
  };
  return map[value] || value || "-";
}

export function translateReasons(reasons: unknown) {
  const value = String(reasons || "");
  const map: Record<string, string> = {
    "MA20 > MA60": "20일선이 60일선 위",
    "MA20 rising": "20일선 상승 중",
    "Tenkan > Kijun": "일목 전환선이 기준선 위",
    "Ichimoku cross": "일목 전환선 기준선 돌파",
    "Bullish close": "전일 대비 상승 마감",
    "Near Kijun": "기준선 근처",
    "RSI rebound zone": "RSI 반등 구간",
    "5D momentum ok": "5일 모멘텀 양호",
    "20D momentum ok": "20일 모멘텀 양호",
    "BB expanding": "볼린저 밴드폭 확대",
    "Enough trading value": "거래대금 충분",
    "Volume spike": "거래량 증가",
    "Strong volume spike": "거래량 강한 증가",
    "Bull cloud pullback support": "양운 위 눌림목 지지",
    "Bear cloud breakout pressure": "음운 돌파 직전 수급",
    "KOSPI above MA5": "코스피 5일선 위",
    "KOSPI_TOP1000": "KOSPI1000",
    KOSPI_TOP500: "KOSPI1000",
    KOSDAQ150: "KOSDAQ150 구성",
    "Core universe": "기존 제한 유니버스 해당",
  };
  return value.split(",").map((item) => map[item.trim()] || item.trim()).filter(Boolean).join(", ");
}

export function isCoreUniverseSignal(raw: Record<string, unknown>) {
  return raw.CoreUniverse === true || raw.CoreUniverse === "true" || raw.CoreUniverse === 1;
}

export function isPassed(value: unknown) {
  return value === true || value === "true" || value === 1;
}

export function translateCoreUniverse(value: unknown) {
  const type = String(value || "");
  const map: Record<string, string> = {
    KOSPI_TOP1000: "KOSPI1000",
    KOSPI_TOP500: "KOSPI1000",
    KOSDAQ150: "KOSDAQ150",
  };
  return map[type] || type || "해당 없음";
}

export function translateCloudType(value: unknown) {
  const type = String(value || "");
  if (type === "bullish") return "양운";
  if (type === "bearish") return "음운";
  if (type === "neutral") return "중립";
  return type || "-";
}

export function translateBacktestStatus(value: unknown) {
  const status = String(value || "");
  if (status === "running") return "진행 중";
  if (status === "completed") return "완료";
  if (status === "failed") return "실패";
  if (status === "not_found") return "없음";
  return status || "-";
}

export function formatDateTime(value: unknown) {
  if (!value) return "-";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function exportBacktestTradesCsv(rows: Array<Record<string, unknown>>, filename: string) {
  const columns: Array<[string, string]> = [
    ["trade_date", "시그널일"],
    ["entry_date", "진입일"],
    ["code", "종목코드"],
    ["name", "종목명"],
    ["score", "점수"],
    ["entry", "진입가"],
    ["exit_price", "청산가"],
    ["return_pct", "수익률"],
    ["hold_days", "보유일"],
    ["exit_reason_ko", "청산사유"],
    ["exit_reason", "청산사유코드"],
    ["tp1_done_ko", "1차익절"],
    ["tp2_done_ko", "2차익절"],
    ["remaining_qty_ratio", "잔량비율"],
    ["events_ko", "청산이벤트"],
  ];
  const csvRows = [
    columns.map(([, label]) => label),
    ...rows.map((row) => {
      const raw = asRecord(row.raw);
      const events = Array.isArray(raw.events) ? raw.events : [];
      const source: Record<string, unknown> = {
        ...raw,
        ...row,
        exit_reason_ko: translateReason(row.exit_reason),
        tp1_done_ko: row.tp1_done || raw.tp1_done ? "Y" : "N",
        tp2_done_ko: row.tp2_done || raw.tp2_done ? "Y" : "N",
        events_ko: events.map((event) => {
          const item = asRecord(event);
          return `${formatCell(item.day)}일차 ${translateReason(item.event)} @ ${formatCell(item.price)}`;
        }).join(" / "),
      };
      return columns.map(([key]) => source[key]);
    }),
  ];
  const csv = `\uFEFF${csvRows.map((row) => row.map(csvCell).join(",")).join("\n")}`;
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename.replace(/[\\/:*?"<>|]+/g, "_").replace(/\s+/g, "_");
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function csvCell(value: unknown) {
  const text = value === null || value === undefined ? "" : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

export function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
