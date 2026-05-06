import { useEffect, useState } from "react";
import type {
  AiReport,
  AiReportType,
  AiReportStatus,
  BacktestJob,
  BacktestResult,
  DailyDashboard,
  KisAccount,
  StrategyPreset,
  StrategySettings,
  TradeDecisionLog,
  WatcherRun,
} from "../api";
import type { DashboardPage, DetailSelection, Status } from "../types";
import {
  asRecord,
  buildStopLossExplanation,
  buildTakeProfitExplanation,
  delay,
  enrichPlanPercentRow,
  enrichTradeLogRow,
  exitPlanFromSource,
  formatCell,
  formatDateTime,
  formatMarketCap,
  formatOrderPolicy,
  formatPercentFromEntry,
  formatPlanPct,
  formatRiskPct,
  isCoreUniverseSignal,
  isPassed,
  latestWatcherIssue,
  normalizeAiReportStatusRow,
  normalizeDecisionRow,
  normalizeTradeLogRow,
  normalizeWatcherRunRow,
  numericValue,
  percentFromEntry,
  translateBacktestStatus,
  translateCloudType,
  translateCoreUniverse,
  translateReason,
  translateReasons,
  translateReportStatus,
  translateReportType,
  translateWatcherSkipReason,
} from "../utils/dashboard";

export function dashboardPages({ isScanAdmin, canUseReports }: { isScanAdmin: boolean; canUseReports: boolean }) {
  const pages: Array<{ key: DashboardPage; label: string; description: string }> = [
    { key: "overview", label: "개요", description: "자동매매 상태와 오늘 요약" },
    { key: "signals", label: "시그널", description: "오늘 후보와 종목 상세" },
    { key: "account", label: "계좌", description: "KIS 연결과 알림 설정" },
    { key: "trading", label: "매매", description: "포지션, 로그, 와쳐 기록" },
    { key: "strategy", label: "전략", description: "자동매매 조건 설정" },
  ];
  if (isScanAdmin || canUseReports) {
    pages.push({
      key: "admin",
      label: "관리자",
      description: isScanAdmin ? "스캔, 공지, 리포트, 백테스트" : "리포트",
    });
  }
  return pages;
}

export function DashboardNav({
  pages,
  activePage,
  onChange,
}: {
  pages: Array<{ key: DashboardPage; label: string; description: string }>;
  activePage: DashboardPage;
  onChange: (page: DashboardPage) => void;
}) {
  return (
    <nav className="dashboard-nav" aria-label="대시보드 메뉴">
      {pages.map((page) => (
        <button
          key={page.key}
          type="button"
          className={activePage === page.key ? "nav-card active" : "nav-card"}
          onClick={() => onChange(page.key)}
        >
          <strong>{page.label}</strong>
          <span>{page.description}</span>
        </button>
      ))}
    </nav>
  );
}

export function WatcherIssuePanel({
  issue,
  refreshing,
  onRefresh,
}: {
  issue: Record<string, unknown>;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  return (
    <section className="panel watcher-issue-panel">
      <div className="data-panel-head">
        <div>
          <h2>와쳐 오류</h2>
          <p className="command-copy">자동매매 감시 중 확인이 필요한 오류만 표시합니다.</p>
        </div>
        <button className="ghost small" type="button" disabled={refreshing} onClick={onRefresh}>
          {refreshing ? "확인 중" : "상태 확인"}
        </button>
      </div>
      <div className="watcher-issue-card">
        <strong>{formatCell(issue.reason)}</strong>
        <span>{formatCell(issue.created_at)}</span>
        {issue.error ? <p>{formatCell(issue.error)}</p> : null}
      </div>
    </section>
  );
}

export function DailyDashboardPanel({ dashboard, onRefresh, refreshing }: { dashboard: DailyDashboard | null; onRefresh: () => void; refreshing: boolean }) {
  const scan = dashboard?.latest_scan;
  const cards = [
    ["오늘 시그널", dashboard?.signals_count],
    ["오픈 포지션", dashboard?.open_positions],
    ["오늘 매수", dashboard?.buy_count],
    ["오늘 매도", dashboard?.sell_count],
    ["매수 제외", dashboard?.skip_count],
  ];

  return (
    <section className="panel daily-panel">
      <div className="section-title">
        <div>
          <h2>데일리 대시보드</h2>
          <p className="command-copy">{dashboard?.date || "오늘"} 기준 자동매매 상태 요약</p>
        </div>
        <div className="panel-actions">
          <span className={`scan-badge ${scan?.status || "idle"}`}>
            스캔 {scan?.status || "대기"}
          </span>
          <button className="ghost small" type="button" disabled={refreshing} onClick={onRefresh}>
            {refreshing ? "갱신 중" : "새로고침"}
          </button>
        </div>
      </div>
      <div className="metric-grid">
        {cards.map(([label, value]) => (
          <div className="metric-card" key={label}>
            <span>{label}</span>
            <strong>{formatCell(value)}</strong>
          </div>
        ))}
      </div>
      <div className="skip-summary">
        <strong>상위 제외 사유</strong>
        {dashboard?.top_skip_reasons?.length ? (
          dashboard.top_skip_reasons.map((item) => (
            <span key={item.reason_code}>{item.reason} {item.count}건</span>
          ))
        ) : (
          <span>아직 기록 없음</span>
        )}
      </div>
    </section>
  );
}

export function StrategyPanel({
  strategy,
  editing,
  pending,
  onToggleEdit,
  onPresetChange,
  onChange,
  onSave,
}: {
  strategy: StrategySettings;
  editing: boolean;
  pending: boolean;
  onToggleEdit: () => void;
  onPresetChange: (preset: StrategyPreset) => void;
  onChange: (strategy: StrategySettings) => void;
  onSave: () => void;
}) {
  const updateNumber = (key: keyof StrategySettings, value: string) => {
    onChange({ ...strategy, [key]: Number(value) });
  };
  return (
    <div className="panel strategy-panel">
      <div className="section-title">
        <div>
          <h2>전략 설정</h2>
          <p className="command-copy">공용 시그널은 그대로 쓰고, 내 계좌의 자동매매 실행 조건만 조정합니다.</p>
        </div>
        <button className="ghost small" type="button" onClick={onToggleEdit}>
          {editing ? "변경 취소" : "변경하기"}
        </button>
      </div>

      {!editing && (
        <div className="strategy-summary">
          <strong>{presetLabel(strategy.preset)} 전략을 사용 중입니다.</strong>
          <span>최소 점수 {strategy.min_score}점</span>
          <span>최대 보유 {strategy.max_open_positions}종목 · 하루 신규 {strategy.max_new_positions_per_day}종목</span>
          <span>종목당 {formatPct(strategy.position_capital_pct)} 이하 · 리스크 {formatPct(strategy.risk_per_trade_pct)} 이하</span>
          <span>최소 주문금액 {Number(strategy.min_order_amount).toLocaleString()}원</span>
          <span>킬스위치: 일손실 {strategy.use_daily_loss_limit ? formatPct(strategy.daily_loss_limit_pct) : "OFF"} · 미실현손실 {strategy.use_unrealized_loss_limit ? formatPct(strategy.unrealized_loss_limit_pct) : "OFF"} · 시장급락 {strategy.use_market_crash_filter ? formatPct(strategy.market_crash_limit_pct) : "OFF"}</span>
          <span>추가 필터: 손절 재매수 차단 {strategy.use_stoploss_reentry_block ? "ON" : "OFF"} · 기준선 이탈 재매수 차단 {strategy.use_kijun_reentry_block ? "ON" : "OFF"} · VI 차단 {strategy.use_vi_filter ? "ON" : "OFF"} · 실시간 호가/체결 {strategy.use_realtime_liquidity_filter ? "ON" : "OFF"} · 당일 캔들 {strategy.use_day_candle_filter ? "ON" : "OFF"} · 본전 손절 {strategy.use_breakeven_after_tp1 ? "ON" : "OFF"} · 기준선 이탈 매도 {strategy.use_kijun_exit ? "ON" : "OFF"}</span>
        </div>
      )}

      {editing && (
        <>
      <div className="preset-row">
        {(["conservative", "balanced", "aggressive"] as StrategyPreset[]).map((preset) => (
          <button
            key={preset}
            type="button"
            className={strategy.preset === preset ? "preset-chip active" : "preset-chip"}
            onClick={() => onPresetChange(preset)}
          >
            {presetLabel(preset)}
          </button>
        ))}
      </div>

      <div className="strategy-grid">
        <label>
          최소 점수
          <input type="number" step="0.5" value={strategy.min_score} onChange={(event) => updateNumber("min_score", event.target.value)} />
        </label>
        <label>
          최대 보유 종목
          <input type="number" min="1" value={strategy.max_open_positions} onChange={(event) => updateNumber("max_open_positions", event.target.value)} />
        </label>
        <label>
          하루 신규 매수
          <input type="number" min="1" value={strategy.max_new_positions_per_day} onChange={(event) => updateNumber("max_new_positions_per_day", event.target.value)} />
        </label>
        <label>
          종목당 최대 비중
          <input type="number" step="0.01" value={strategy.position_capital_pct} onChange={(event) => updateNumber("position_capital_pct", event.target.value)} />
        </label>
        <label>
          1회 리스크 비중
          <input type="number" step="0.001" value={strategy.risk_per_trade_pct} onChange={(event) => updateNumber("risk_per_trade_pct", event.target.value)} />
        </label>
        <label>
          최소 주문금액
          <input type="number" step="10000" value={strategy.min_order_amount} onChange={(event) => updateNumber("min_order_amount", event.target.value)} />
        </label>
        <label>
          진입가 하단 배율
          <input type="number" step="0.001" value={strategy.min_entry_discount} onChange={(event) => updateNumber("min_entry_discount", event.target.value)} />
        </label>
        <label>
          진입가 상단 배율
          <input type="number" step="0.001" value={strategy.max_entry_premium} onChange={(event) => updateNumber("max_entry_premium", event.target.value)} />
        </label>
        <label>
          고점 이탈 허용
          <input type="number" step="0.005" value={strategy.max_pullback_from_day_high} onChange={(event) => updateNumber("max_pullback_from_day_high", event.target.value)} />
        </label>
        <label>
          하루 손실 제한
          <input type="number" step="0.005" value={strategy.daily_loss_limit_pct} onChange={(event) => updateNumber("daily_loss_limit_pct", event.target.value)} />
        </label>
        <label>
          미실현손실 제한
          <input type="number" step="0.005" value={strategy.unrealized_loss_limit_pct} onChange={(event) => updateNumber("unrealized_loss_limit_pct", event.target.value)} />
        </label>
        <label>
          시장 급락 차단 기준
          <input type="number" step="0.005" value={strategy.market_crash_limit_pct} onChange={(event) => updateNumber("market_crash_limit_pct", event.target.value)} />
        </label>
        <label>
          세금/수수료율
          <input type="number" step="0.0001" value={strategy.commission_tax_pct} onChange={(event) => updateNumber("commission_tax_pct", event.target.value)} />
        </label>
        <label>
          최소 체결강도
          <input type="number" step="1" value={strategy.min_realtime_strength} onChange={(event) => updateNumber("min_realtime_strength", event.target.value)} />
        </label>
        <label>
          최소 매수/매도 잔량비
          <input type="number" step="0.05" value={strategy.min_bid_ask_ratio} onChange={(event) => updateNumber("min_bid_ask_ratio", event.target.value)} />
        </label>
        <label>
          최대 호가 스프레드
          <input type="number" step="0.001" value={strategy.max_realtime_spread_pct} onChange={(event) => updateNumber("max_realtime_spread_pct", event.target.value)} />
        </label>
      </div>

      <div className="strategy-checks">
        <label className="check-row">
          <input type="checkbox" checked={strategy.use_kijun_filter} onChange={(event) => onChange({ ...strategy, use_kijun_filter: event.target.checked })} />
          일목 기준선 필터 사용
        </label>
        <label className="check-row">
          <input type="checkbox" checked={strategy.use_bb_upper_filter} onChange={(event) => onChange({ ...strategy, use_bb_upper_filter: event.target.checked })} />
          볼린저 상단 필터 사용
        </label>
        <label className="check-row">
          <input type="checkbox" checked={strategy.use_day_candle_filter} onChange={(event) => onChange({ ...strategy, use_day_candle_filter: event.target.checked })} />
          당일 캔들 위치 필터 사용
        </label>
        <label className="check-row">
          <input type="checkbox" checked={strategy.use_breakeven_after_tp1} onChange={(event) => onChange({ ...strategy, use_breakeven_after_tp1: event.target.checked })} />
          1차 익절 후 본전 손절 사용
        </label>
        <label className="check-row">
          <input type="checkbox" checked={strategy.use_kijun_exit} onChange={(event) => onChange({ ...strategy, use_kijun_exit: event.target.checked })} />
          일목 기준선 이탈 매도 사용
        </label>
        <label className="check-row">
          <input type="checkbox" checked={strategy.use_kijun_reentry_block} onChange={(event) => onChange({ ...strategy, use_kijun_reentry_block: event.target.checked })} />
          당일 기준선 이탈 매도 종목 재매수 금지
        </label>
        <label className="check-row">
          <input type="checkbox" checked={strategy.use_daily_loss_limit} onChange={(event) => onChange({ ...strategy, use_daily_loss_limit: event.target.checked })} />
          하루 손실 제한 사용
        </label>
        <label className="check-row">
          <input type="checkbox" checked={strategy.use_unrealized_loss_limit} onChange={(event) => onChange({ ...strategy, use_unrealized_loss_limit: event.target.checked })} />
          미실현손실 제한 사용
        </label>
        <label className="check-row">
          <input type="checkbox" checked={strategy.use_market_crash_filter} onChange={(event) => onChange({ ...strategy, use_market_crash_filter: event.target.checked })} />
          시장 급락 시 신규 매수 차단
        </label>
        <label className="check-row">
          <input type="checkbox" checked={strategy.use_realtime_liquidity_filter} onChange={(event) => onChange({ ...strategy, use_realtime_liquidity_filter: event.target.checked })} />
          시그널 종목 실시간 체결강도/호가잔량 필터
        </label>
        <label className="check-row">
          <input type="checkbox" checked={strategy.use_stoploss_reentry_block} onChange={(event) => onChange({ ...strategy, use_stoploss_reentry_block: event.target.checked })} />
          당일 손절 종목 재매수 금지
        </label>
        <label className="check-row">
          <input type="checkbox" checked={strategy.use_vi_filter} onChange={(event) => onChange({ ...strategy, use_vi_filter: event.target.checked })} />
          VI 발동 종목 매수 차단
        </label>
      </div>
      <button className="primary strategy-save" type="button" disabled={pending} onClick={onSave}>
        {pending ? "저장 중..." : "전략 저장"}
      </button>
        </>
      )}
    </div>
  );
}
export function presetLabel(preset: StrategyPreset) {
  if (preset === "conservative") return "보수적";
  if (preset === "aggressive") return "공격적";
  return "기본";
}

export function formatPct(value: number) {
  const rounded = (value * 100).toFixed(1).replace(/\.0$/, "");
  return `${rounded}%`;
}

export function AutoTradingRules({
  strategy,
  mode,
  liveOrderEnabled,
  serverLiveTradingAllowed,
}: {
  strategy: StrategySettings;
  mode?: "paper" | "live";
  liveOrderEnabled: boolean;
  serverLiveTradingAllowed: boolean;
}) {
  const liveBlocked = mode === "live" && (!liveOrderEnabled || !serverLiveTradingAllowed);
  return (
    <div className="rule-box">
      <div>
        <strong>매수 조건</strong>
        <ul>
          <li>오늘 공용 시그널 점수 {strategy.min_score}점 이상</li>
          <li>14:30~15:20 사이에만 신규 매수</li>
          <li>하루 신규 매수 {strategy.max_new_positions_per_day}종목 제한은 오늘 체결 포지션과 미체결 매수 주문을 합산해서 적용</li>
          <li>하루 손실 제한 {strategy.use_daily_loss_limit ? `사용: 실현손실 ${formatPct(strategy.daily_loss_limit_pct)} 도달 시 신규 매수 중단` : "미사용"}</li>
          <li>미실현손실 제한 {strategy.use_unrealized_loss_limit ? `사용: 보유종목 평가손실 ${formatPct(strategy.unrealized_loss_limit_pct)} 도달 시 신규 매수 중단` : "미사용"}</li>
          <li>시장 급락 차단 {strategy.use_market_crash_filter ? `사용: 코스피 당일 수익률 ${formatPct(strategy.market_crash_limit_pct)} 이하이면 신규 매수 중단` : "미사용"}</li>
          <li>실시간 필터 {strategy.use_realtime_liquidity_filter ? `사용: 체결강도 ${strategy.min_realtime_strength} 이상, 매수/매도 잔량비 ${strategy.min_bid_ask_ratio} 이상, 스프레드 ${formatPct(strategy.max_realtime_spread_pct)} 이하` : "미사용"}</li>
          <li>당일 손절 종목 재매수 금지 {strategy.use_stoploss_reentry_block ? "사용" : "미사용"}</li>
          <li>당일 기준선 이탈 매도 종목 재매수 금지 {strategy.use_kijun_reentry_block ? "사용" : "미사용"}</li>
          <li>VI 발동 종목 매수 차단 {strategy.use_vi_filter ? "사용" : "미사용"}</li>
          <li>점수 높은 순서로 확인하되 장중 가격 필터 통과 필요</li>
          <li>현재가가 진입가 {formatPct(strategy.min_entry_discount - 1)}~+{formatPct(strategy.max_entry_premium - 1)} 범위 안</li>
          <li>일목 기준선 필터 {strategy.use_kijun_filter ? "사용" : "미사용"}, 볼린저 상단 필터 {strategy.use_bb_upper_filter ? "사용" : "미사용"}</li>
          <li>당일 캔들 위치 필터 {strategy.use_day_candle_filter ? `사용: 고점 대비 ${formatPct(strategy.max_pullback_from_day_high)} 이상 밀리면 제외` : "미사용"}</li>
          <li>매수 주문가는 최우선 매도호가 기준, 호가가 없으면 현재가보다 1틱 위로 주문</li>
        </ul>
      </div>
      <div>
        <strong>자금/리스크</strong>
        <ul>
          <li>전체 보유 최대 {strategy.max_open_positions}종목</li>
          <li>하루 신규 매수 최대 {strategy.max_new_positions_per_day}종목</li>
          <li>종목당 총자산 {formatPct(strategy.position_capital_pct)} 이하</li>
          <li>1회 손실 리스크 총자산 {formatPct(strategy.risk_per_trade_pct)} 이하</li>
          <li>주문금액 {Number(strategy.min_order_amount).toLocaleString()}원 미만이면 매수 안 함</li>
          <li>수익/손실 계산에 세금·수수료 추정치 {formatPct(strategy.commission_tax_pct)} 반영</li>
        </ul>
      </div>
      <div>
        <strong>매도 조건</strong>
        <ul>
          <li>09:00~15:20 동안 5분 단위 감시</li>
          <li>보유 포지션은 1분 단위 웹소켓 감시로 손절/익절 트리거를 빠르게 확인</li>
          <li>손절가 도달 시 전량 매도</li>
          <li>매수 후 30분 동안은 손절을 제외한 전략성 매도 제한</li>
          <li>1차/2차 익절가 도달 시 일부 매도</li>
          <li>익절 후 추적 손절 도달 시 잔량 매도</li>
          <li>1차 익절 후 본전 손절 {strategy.use_breakeven_after_tp1 ? "사용" : "미사용"}</li>
          <li>일목 기준선 이탈 매도 {strategy.use_kijun_exit ? "사용" : "미사용"}</li>
          <li>최대 보유일 도달 시 전량 매도</li>
          <li>일반 매도 주문가는 최우선 매수호가 기준, 호가가 없으면 현재가보다 1틱 아래로 주문</li>
          <li>손절 매도는 체결 우선으로 최우선 매수호가보다 3틱 낮은 공격적 지정가로 주문</li>
          <li>손절 주문이 미체결이면 다음 와쳐 주기에서 최대 3회까지 5틱, 7틱, 9틱 낮춰 재주문</li>
          <li>3회 재주문 후에도 미체결이면 기존 주문 취소 후 시장가 매도로 최종 탈출</li>
          <li>부분체결/전체체결은 KIS 주문조회와 계좌 잔고를 같이 확인해서 반영</li>
        </ul>
      </div>
      {liveBlocked && (
        <p className="rule-warning">실전 계좌는 사용자 실전 주문 허용과 서버 ALLOW_LIVE_TRADING 둘 다 켜져야 주문됩니다.</p>
      )}
    </div>
  );
}

export function labelForPending(key: string) {
  const labels: Record<string, string> = {
    broker: "KIS 정보 저장",
    enable: "자동매매 ON",
    disable: "자동매매 OFF",
    account: "KIS 계좌 조회",
    accountSwitch: "활성 계좌 변경",
    strategy: "전략 설정 저장",
    scan: "오늘 시그널 스캔",
    telegramNotice: "공용 텔레그램 공지 발송",
    signals: "시그널 조회",
    backtest: "백테스트",
    backtestExport: "백테스트 전체 거래 다운로드",
    report: "AI 리포트 생성 큐 등록",
    signalReport: "개별 기업 AI 리포트 생성 큐 등록",
    reportDownload: "종합 리포트 다운로드",
    signalReportDownload: "개별 리포트 다운로드",
    watcherRunsRefresh: "와쳐 상태 확인",
    watchJobsRefresh: "와쳐 작업 큐 확인",
    watchJobsRetry: "실패 와쳐 작업 재시도",
    forceLiquidate: "종목 강제 청산",
  };
  return labels[key] || "요청";
}

export function membershipLabel(role?: string | null) {
  if (!role) return "권한 확인 중";
  if (role === "admin") return "관리자";
  if (role === "paid") return "유료회원";
  return "무료회원";
}

export function AccountPanel({
  account,
  onRefresh,
  refreshing,
  onDetail,
}: {
  account: KisAccount | null;
  onRefresh: () => void;
  refreshing: boolean;
  onDetail: (title: string, row: Record<string, unknown>) => void;
}) {
  const rows = account?.holdings.map((holding) => ({
    row_type: "holding",
    account: account.account,
    code: holding.code,
    name: holding.name,
    qty: holding.qty,
    avg_price: holding.avg_price,
    current_price: holding.current_price,
    evaluation_amount: holding.evaluation_amount,
    profit_loss: holding.profit_loss,
    profit_loss_rate: holding.profit_loss_rate,
  })) || [];
  const accountSummary = account
    ? {
        row_type: "summary",
        account: account.account,
        orderable_cash: account.orderable_cash ?? account.cash,
        total_equity: account.total_equity,
        holdings_count: account.holdings_count,
        holdings: account.holdings,
      }
    : null;

  return (
    <section className="panel data-panel account-panel">
      <div className="data-panel-head">
        <h2>KIS 계좌</h2>
        <button className="ghost small" type="button" disabled={refreshing} onClick={onRefresh}>
          {refreshing ? "갱신 중" : "새로고침"}
        </button>
      </div>
      {!account ? (
        <p className="empty">계좌 조회 전</p>
      ) : (
        <>
          <div
            className="account-summary clickable-summary"
            role="button"
            tabIndex={0}
            onClick={() => accountSummary && onDetail(`${account.account} 계좌`, accountSummary)}
            onKeyDown={(event) => {
              if ((event.key === "Enter" || event.key === " ") && accountSummary) onDetail(`${account.account} 계좌`, accountSummary);
            }}
          >
            <span>계좌 {account.account}</span>
            <strong>주문가능 {formatCell(account.orderable_cash ?? account.cash)}원</strong>
            <strong>총평가 {formatCell(account.total_equity)}원</strong>
            <span>보유 {account.holdings_count}종목</span>
          </div>
          <MiniTable
            rows={rows}
            columns={["code", "name", "qty", "avg_price", "current_price", "evaluation_amount", "profit_loss", "profit_loss_rate"]}
            onRowClick={(row) => onDetail(`${formatCell(row.name)} (${formatCell(row.code)})`, row)}
          />
        </>
      )}
    </section>
  );
}

export function MiniTable({
  rows,
  columns,
  onRowClick,
  emptyLabel = "보유 종목 없음",
}: {
  rows: Array<Record<string, unknown>>;
  columns: string[];
  onRowClick?: (row: Record<string, unknown>) => void;
  emptyLabel?: string;
}) {
  if (rows.length === 0) {
    return <p className="empty">{emptyLabel}</p>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={String(row.code || row.id || index)}
              className={onRowClick ? "clickable-row" : undefined}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
            >
              {columns.map((column) => <td key={column}>{formatCell(row[column])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function StatusLine({ status }: { status: Status }) {
  if (!status.message) return null;
  return <p className={`status ${status.type}`}>{status.message}</p>;
}

export function cleanErrorMessage(message: string) {
  try {
    const parsed = JSON.parse(message);
    return parsed.detail || parsed.message || message;
  } catch {
    return message;
  }
}

export function downloadHtmlReport(report: AiReport) {
  const html = report.html || "";
  const documentHtml = `<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <title>${escapeHtml(report.title)}</title>
</head>
<body>
${html}
</body>
</html>`;
  const blob = new Blob([documentHtml], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${sanitizeFilename(`${report.trade_date}_${report.code}_${report.name || report.report_type}_ai_report`)}.html`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function sanitizeFilename(value: string) {
  return value.replace(/[\\/:*?"<>|]+/g, "_").replace(/\s+/g, "_");
}

export function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function hasCompletedReport(reports: AiReportStatus[], reportType: AiReportType, code?: string) {
  return reports.some((report) => {
    if (report.report_type !== reportType || report.status !== "completed") return false;
    if (reportType === "daily" || reportType === "daily_blog") return report.code === "ALL";
    return report.code === code;
  });
}

export function DataPanel({
  title,
  rows,
  columns,
  onRowClick,
  headerAction,
  initialRows = 10,
  maxRows = 10,
  pageSize = 10,
  pagination = false,
  className = "",
}: {
  title: string;
  rows: Array<Record<string, unknown>>;
  columns: string[];
  onRowClick?: (row: Record<string, unknown>) => void;
  headerAction?: React.ReactNode;
  initialRows?: number;
  maxRows?: number;
  pageSize?: number;
  pagination?: boolean;
  className?: string;
}) {
  const [visibleRows, setVisibleRows] = useState(initialRows);
  const [page, setPage] = useState(1);
  const cappedMaxRows = Math.min(maxRows, rows.length);
  const totalPages = pagination ? Math.max(1, Math.ceil(rows.length / pageSize)) : 1;
  const normalizedPage = Math.min(page, totalPages);
  const displayRows = pagination
    ? rows.slice((normalizedPage - 1) * pageSize, normalizedPage * pageSize)
    : rows.slice(0, Math.min(visibleRows, cappedMaxRows));

  useEffect(() => {
    setVisibleRows(initialRows);
    setPage(1);
  }, [initialRows, rows.length, title]);

  return (
    <section className={`panel data-panel ${className}`.trim()}>
      <div className="data-panel-head">
        <h2>{title}</h2>
        {headerAction}
      </div>
      {rows.length === 0 ? (
        <p className="empty">데이터 없음</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
            </thead>
            <tbody>
              {displayRows.map((row, index) => (
                <tr
                  key={String(row.id || index)}
                  className={onRowClick ? "clickable-row" : undefined}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                >
                  {columns.map((column) => <td key={column}>{formatCell(row[column])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
          {!pagination && visibleRows < cappedMaxRows && (
            <button className="ghost table-more" type="button" onClick={() => setVisibleRows(cappedMaxRows)}>
              더보기 {cappedMaxRows - visibleRows}개
            </button>
          )}
          {pagination && totalPages > 1 && (
            <div className="table-pagination">
              {Array.from({ length: totalPages }, (_, index) => index + 1).map((pageNumber) => (
                <button
                  key={pageNumber}
                  className={pageNumber === normalizedPage ? "active" : ""}
                  type="button"
                  onClick={() => setPage(pageNumber)}
                >
                  {pageNumber}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
export function DetailSection({ title, items }: { title: string; items: Array<[string, unknown]> }) {
  return (
    <section className="detail-section">
      <h3>{title}</h3>
      <dl>
        {items.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{formatCell(value)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
