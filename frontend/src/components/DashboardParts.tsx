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

export function dashboardPages({ isScanAdmin, canUseReports }: { isScanAdmin: boolean; canUseReports: boolean }) {
  const pages: Array<{ key: DashboardPage; label: string; description: string }> = [
    { key: "overview", label: "개요", description: "자동매매 상태와 오늘 요약" },
    { key: "signals", label: "시그널", description: "오늘 후보와 종목 상세" },
    { key: "account", label: "계좌", description: "KIS 연결과 알림 설정" },
    { key: "trading", label: "매매", description: "포지션, 로그, 와쳐 기록" },
    { key: "strategy", label: "전략", description: "자동매매 조건 설정" },
  ];
  if (isScanAdmin || canUseReports) {
    pages.push({ key: "admin", label: "관리자", description: "스캔, 리포트, 백테스트" });
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

export function BacktestPanel({
  result,
  job,
  runs,
  days,
  pending,
  onDaysChange,
  onRun,
  onResume,
  onRunDetail,
}: {
  result: BacktestResult | null;
  job: BacktestJob | null;
  runs: BacktestJob[];
  days: number;
  pending: boolean;
  onDaysChange: (days: number) => void;
  onRun: () => void;
  onResume: (runId: number | string) => void;
  onRunDetail: (run: BacktestJob) => void;
}) {
  const progress = job?.progress || {};
  const progressTotal = progress.total || 0;
  const progressProcessed = progress.processed || 0;
  const progressPct = progressTotal > 0 ? Math.min(100, Math.round((progressProcessed / progressTotal) * 100)) : 0;
  const summary = result
    ? [
        ["생성 후보", result.generated_signals || 0],
        ["검증 건수", result.signals_tested],
        ["승률", `${result.win_rate}%`],
        ["평균 수익률", `${result.avg_return_pct}%`],
        ["평균 보유", `${result.avg_hold_days}일`],
        ["최고/최악", `${result.best_return_pct}% / ${result.worst_return_pct}%`],
      ]
    : [];

  return (
    <section className="panel data-panel backtest-panel">
      <div className="data-panel-head">
        <h2>백테스트</h2>
        <div className="backtest-controls">
          <select value={days} onChange={(event) => onDaysChange(Number(event.target.value))}>
            <option value={120}>120일</option>
            <option value={240}>240일</option>
            <option value={365}>365일</option>
            <option value={730}>730일</option>
          </select>
          <button className="primary small" type="button" disabled={pending} onClick={onRun}>
            {pending ? "실행 중..." : "백테스트 실행"}
          </button>
          {runs.some((run) => run.status === "running" || run.status === "failed") && (
            <button
              className="ghost small"
              type="button"
              disabled={pending}
              onClick={() => {
                const target = runs.find((run) => run.status === "running" || run.status === "failed");
                if (target) onResume(target.run_id || target.job_id);
              }}
            >
              최근 백테스트 이어가기
            </button>
          )}
        </div>
      </div>
      {pending && (
        <div className="backtest-progress">
          <div className="backtest-progress-bar">
            <span style={{ width: `${progressPct}%` }} />
          </div>
          <p>
            {progressTotal > 0
              ? `${progressProcessed}/${progressTotal}개 처리, 누적 후보 ${progress.signals || 0}개`
              : "백테스트 잡을 준비 중입니다."}
          </p>
        </div>
      )}
      {!result ? (
        <p className="empty">저장된 시그널이 없어도 과거 가격 데이터를 다시 스캔해 당시 조건으로 후보를 재생성한 뒤, 진입가·손절가·익절가·최대 보유일을 검증합니다.</p>
      ) : (
        <>
          {result.error && <p className="empty">{result.error}</p>}
          <p className="hint">과거 재스캔 기반입니다. 저장된 공용 시그널이 아니라 각 날짜의 가격 데이터로 전략 조건을 다시 계산합니다.</p>
          <div className="metric-grid compact">
            {summary.map(([label, value]) => (
              <div className="metric-card" key={label}>
                <span>{label}</span>
                <strong>{formatCell(value)}</strong>
              </div>
            ))}
          </div>
          <MiniTable
            rows={result.trades.map((trade) => ({
              date: trade.trade_date,
              code: trade.code,
              name: trade.name,
              score: trade.score,
              return_pct: `${trade.return_pct}%`,
              hold_days: trade.hold_days,
              exit_reason: translateReason(trade.exit_reason),
            }))}
            columns={["date", "code", "name", "score", "return_pct", "hold_days", "exit_reason"]}
          />
        </>
      )}
      {runs.length > 0 && (
        <div className="backtest-history">
          <h3>백테스트 기록</h3>
          <MiniTable
            rows={runs.slice(0, 5).map((run) => ({
              id: run.run_id || run.job_id,
              status: translateBacktestStatus(run.status),
              range: `${run.days || "-"}일`,
              strategy: `${run.strategy_key || "-"} / ${run.strategy_version || "-"}`,
              progress: `${run.progress?.processed || 0}/${run.progress?.total || 0}`,
              win_rate: run.result ? `${run.result.win_rate}%` : "-",
              avg_return: run.result ? `${run.result.avg_return_pct}%` : "-",
              raw_run: run,
            }))}
            columns={["id", "status", "range", "strategy", "progress", "win_rate", "avg_return"]}
            onRowClick={(row) => onRunDetail(row.raw_run as BacktestJob)}
          />
        </div>
      )}
    </section>
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
    report: "AI 리포트 생성 큐 등록",
    signalReport: "개별 기업 AI 리포트 생성 큐 등록",
    reportDownload: "종합 리포트 다운로드",
    signalReportDownload: "개별 리포트 다운로드",
    watcherRunsRefresh: "와쳐 상태 확인",
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
        cash: account.cash,
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
            <strong>예수금 {formatCell(account.cash)}원</strong>
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

export function ReportCalendarPanel({
  selectedDate,
  dates,
  rows,
  refreshing,
  reportPending,
  downloadPending,
  onDateChange,
  onRefresh,
  onDailyReportAction,
  onDailyBlogReportAction,
  onRowClick,
}: {
  selectedDate: string;
  dates: string[];
  rows: AiReportStatus[];
  refreshing: boolean;
  reportPending: boolean;
  downloadPending: boolean;
  onDateChange: (tradeDate: string) => void;
  onRefresh: () => void;
  onDailyReportAction: () => void;
  onDailyBlogReportAction: () => void;
  onRowClick: (row: Record<string, unknown>) => void;
}) {
  const normalizedRows = rows
    .filter((row) => !selectedDate || row.trade_date === selectedDate)
    .map(normalizeAiReportStatusRow);
  const dailyReports = normalizedRows.filter((row) => row.report_type === "daily" || row.report_type === "daily_blog");
  const signalReports = normalizedRows.filter((row) => row.report_type === "signal" || row.report_type === "signal_blog");
  const recentDates = dates.slice(0, 12);
  const dailyReportCompleted = dailyReports.some((row) => row.report_type === "daily" && row.status === "completed");
  const dailyBlogReportCompleted = dailyReports.some((row) => row.report_type === "daily_blog" && row.status === "completed");
  const actionPending = reportPending || downloadPending;

  return (
    <section className="panel data-panel report-calendar-panel">
      <div className="data-panel-head">
        <div>
          <h2>리포트 캘린더</h2>
          <p className="panel-subtitle">날짜를 선택하면 해당일의 종합/개별 리포트와 블로그 글을 확인합니다.</p>
        </div>
        <button className="ghost small" type="button" disabled={refreshing || !selectedDate} onClick={onRefresh}>
          {refreshing ? "갱신 중" : "새로고침"}
        </button>
      </div>
      <div className="report-calendar-controls">
        <input
          type="date"
          value={selectedDate}
          onChange={(event) => onDateChange(event.target.value)}
        />
        <div className="report-generate-actions">
          <button className="primary small" type="button" disabled={actionPending || !selectedDate} onClick={onDailyReportAction}>
            {downloadPending && dailyReportCompleted ? "다운로드 중..."
              : reportPending && !dailyReportCompleted ? "생성 요청 중..."
                : dailyReportCompleted ? "선택 날짜 종합 리포트 다운로드" : "선택 날짜 종합 리포트 생성"}
          </button>
          <button className="small" type="button" disabled={actionPending || !selectedDate} onClick={onDailyBlogReportAction}>
            {downloadPending && dailyBlogReportCompleted ? "다운로드 중..."
              : reportPending && !dailyBlogReportCompleted ? "생성 요청 중..."
                : dailyBlogReportCompleted ? "선택 날짜 블로그 글 다운로드" : "선택 날짜 블로그 글 생성"}
          </button>
        </div>
        <div className="report-date-list">
          {recentDates.length === 0 ? (
            <span className="empty">생성된 리포트 날짜 없음</span>
          ) : recentDates.map((tradeDate) => (
            <button
              className={tradeDate === selectedDate ? "active" : ""}
              type="button"
              key={tradeDate}
              onClick={() => onDateChange(tradeDate)}
            >
              {tradeDate}
            </button>
          ))}
        </div>
      </div>
      <div className="report-status-groups">
        <section>
          <h3>{selectedDate || "날짜 미선택"} 종합 리포트/블로그 글</h3>
          <MiniTable
            rows={dailyReports}
            columns={["report_kind_ko", "name", "code", "status_ko", "created_at", "started_at", "finished_at", "error"]}
            onRowClick={onRowClick}
            emptyLabel="해당 날짜의 종합 리포트 없음"
          />
        </section>
        <section>
          <h3>개별 기업 리포트/블로그 글</h3>
          <MiniTable
            rows={signalReports}
            columns={["report_kind_ko", "name", "code", "status_ko", "created_at", "started_at", "finished_at", "error"]}
            onRowClick={onRowClick}
            emptyLabel="해당 날짜의 개별 리포트 없음"
          />
        </section>
      </div>
    </section>
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

export function DetailOverlay({
  detail,
  isScanAdmin,
  pending,
  onSendSignalReport,
  onSendSignalBlogReport,
  onDownloadSignalReport,
  onDownloadSignalBlogReport,
  onDownloadReportStatus,
  onForceLiquidatePosition,
  aiReports,
  onClose,
}: {
  detail: DetailSelection;
  isScanAdmin: boolean;
  pending: string | null;
  onSendSignalReport: (row: Record<string, unknown>) => void;
  onSendSignalBlogReport: (row: Record<string, unknown>) => void;
  onDownloadSignalReport: (row: Record<string, unknown>) => void;
  onDownloadSignalBlogReport: (row: Record<string, unknown>) => void;
  onDownloadReportStatus: (row: Record<string, unknown>) => void;
  onForceLiquidatePosition: (row: Record<string, unknown>) => void;
  aiReports: AiReportStatus[];
  onClose: () => void;
}) {
  const detailLabel =
    detail.kind === "signal" ? "시그널 상세"
      : detail.kind === "log" ? "매매 로그 상세"
        : detail.kind === "decision" ? "매수 제외 상세"
          : detail.kind === "watcher" ? "와쳐 실행 상세"
            : detail.kind === "account" ? "계좌 상세"
              : detail.kind === "report" ? "AI 리포트 상세"
                : detail.kind === "backtest" ? "백테스트 상세"
            : "포지션 상세";
  return (
    <div className="overlay-backdrop" onClick={onClose}>
      <aside className="detail-popover" onClick={(event) => event.stopPropagation()}>
        <div className="detail-head">
          <div>
            <span>{detailLabel}</span>
            <h2>{detail.title}</h2>
          </div>
          <button className="ghost small" onClick={onClose}>닫기</button>
        </div>
        {detail.kind === "signal" && (
          <SignalDetail
            row={detail.row}
            isScanAdmin={isScanAdmin}
            pending={pending === "signalReport"}
            downloadPending={pending === "signalReportDownload"}
            reportCompleted={hasCompletedReport(aiReports, "signal", String(detail.row.code || "").padStart(6, "0"))}
            blogReportCompleted={hasCompletedReport(aiReports, "signal_blog", String(detail.row.code || "").padStart(6, "0"))}
            onSendReport={() => onSendSignalReport(detail.row)}
            onSendBlogReport={() => onSendSignalBlogReport(detail.row)}
            onDownloadReport={() => onDownloadSignalReport(detail.row)}
            onDownloadBlogReport={() => onDownloadSignalBlogReport(detail.row)}
          />
        )}
        {detail.kind === "log" && <TradeLogDetail row={detail.row} />}
        {detail.kind === "position" && (
          <PositionDetail
            row={detail.row}
            pending={pending === "forceLiquidate"}
            onForceLiquidate={() => onForceLiquidatePosition(detail.row)}
          />
        )}
        {detail.kind === "account" && <AccountDetail row={detail.row} />}
        {detail.kind === "decision" && <DecisionDetail row={detail.row} />}
        {detail.kind === "watcher" && <WatcherRunDetail row={detail.row} />}
        {detail.kind === "backtest" && <BacktestRunDetail row={detail.row} />}
        {detail.kind === "report" && (
          <ReportStatusDetail
            row={detail.row}
            pending={pending === "reportDownload" || pending === "signalReportDownload"}
            onDownload={() => onDownloadReportStatus(detail.row)}
          />
        )}
      </aside>
    </div>
  );
}

export function SignalDetail({
  row,
  isScanAdmin,
  pending,
  downloadPending,
  reportCompleted,
  blogReportCompleted,
  onSendReport,
  onSendBlogReport,
  onDownloadReport,
  onDownloadBlogReport,
}: {
  row: Record<string, unknown>;
  isScanAdmin: boolean;
  pending: boolean;
  downloadPending: boolean;
  reportCompleted: boolean;
  blogReportCompleted: boolean;
  onSendReport: () => void;
  onSendBlogReport: () => void;
  onDownloadReport: () => void;
  onDownloadBlogReport: () => void;
}) {
  const raw = asRecord(row.raw);
  const companyProfile = asRecord(raw.CompanyProfile);
  const code = String(row.code || "").padStart(6, "0");
  const naverUrl = `https://stock.naver.com/domestic/stock/${code}/price`;
  return (
    <div className="detail-grid">
      <a className="naver-link" href={naverUrl} target="_blank" rel="noreferrer">
        네이버 증권으로 가기
      </a>
      {isScanAdmin && (
        <>
          <button className="primary detail-action" type="button" disabled={pending} onClick={onSendReport}>
            {pending ? "개별 리포트 생성 요청 중..." : "이 기업 AI 리포트 생성 요청"}
          </button>
          <button className="detail-action" type="button" disabled={pending} onClick={onSendBlogReport}>
            {pending ? "블로그 글 생성 요청 중..." : "이 기업 블로그 글 생성 요청"}
          </button>
          {reportCompleted && (
            <button className="detail-action" type="button" disabled={downloadPending} onClick={onDownloadReport}>
              {downloadPending ? "리포트 확인 중..." : "개별 리포트 다운로드"}
            </button>
          )}
          {blogReportCompleted && (
            <button className="detail-action" type="button" disabled={downloadPending} onClick={onDownloadBlogReport}>
              {downloadPending ? "블로그 글 확인 중..." : "개별 블로그 글 다운로드"}
            </button>
          )}
        </>
      )}
      <DetailSection title="기업 개요" items={[
        ["시장", companyProfile.market || raw.Universe],
        ["섹터", companyProfile.sector],
        ["업종", companyProfile.industry],
        ["사업 요약", companyProfile.business_summary],
        ["시가총액", formatMarketCap(companyProfile.market_cap)],
      ]} />
      <DetailSection title="매매 계획" items={[
        ["매수가", row.entry],
        ["손절가", row.stop_loss],
        ["손절률", formatPercentFromEntry(row.stop_loss, row.entry)],
        ["1차 익절가", row.take_profit_1],
        ["1차 익절률", formatPercentFromEntry(row.take_profit_1, row.entry)],
        ["2차 익절가", row.take_profit_2],
        ["2차 익절률", formatPercentFromEntry(row.take_profit_2, row.entry)],
        ["추적 손절가", row.trailing_stop],
        ["추적 손절률", formatPercentFromEntry(row.trailing_stop, row.entry)],
        ["손절 산출 근거", buildStopLossExplanation(row, raw)],
        ["익절 산출 근거", buildTakeProfitExplanation(row)],
        ["권장 보유", `${formatCell(raw.HoldMinDays)}-${formatCell(raw.HoldPreferredDays)}일`],
        ["최대 보유", `${formatCell(raw.HoldMaxDays)}일`],
        ["매입 허용 시간", "14:30-15:20"],
      ]} />
      <DetailSection title="진입 근거" items={[
        ["점수", row.score],
        ["사유", translateReasons(raw.Reasons)],
        ["RSI14", raw.RSI14],
        ["일목 전환선", raw.Tenkan],
        ["일목 기준선", raw.Kijun],
        ["구름 상단", raw.CloudUpper],
        ["구름 하단", raw.CloudLower],
        ["구름 상태", translateCloudType(raw.CloudType)],
        ["구름 상단 이격", `${formatCell(raw["DistanceToCloudUpper(%)"])}%`],
        ["패턴", raw.SignalPatterns],
        ["일목 돌파 후 경과일", raw.DaysAfterIchimokuCross],
        ["BB 폭", raw["BBWidth(%)"]],
        ["BB 확장", raw["BBExpansion(%)"]],
        ["거래량 배율", raw.VolumeSpikeRatio],
        ["거래대금 배율", raw.TradingValueSpikeRatio],
        ["상대강도 20D", `${formatCell(raw["RelativeStrength_20D(%)"])}%`],
      ]} />
      <DetailSection title="리스크/시장" items={[
        ["손절폭", `${formatCell(raw["StopPct"] ?? raw.StopPct)}%`],
        ["리스크", `${formatCell(raw.RiskPct)}%`],
        ["ATR", raw.ATR14],
        ["ATR 비율", `${formatCell(raw["ATR(%)"])}%`],
        ["갭", `${formatCell(raw["Gap(%)"])}%`],
        ["윗꼬리 비율", raw.UpperShadowRatio],
        ["20일 거래대금", raw.TradingValue20D],
        ["시장 필터", `${formatCell(raw.MarketFilter)} / ${isPassed(raw.MarketFilterPassed) ? "통과" : "미통과"}`],
        ["유니버스", raw.Universe],
        ["핵심군", isCoreUniverseSignal(raw) ? translateCoreUniverse(raw.CoreUniverseType) : "해당 없음"],
        ["5일 수익률", `${formatCell(raw["Ret_5D(%)"])}%`],
        ["20일 수익률", `${formatCell(raw["Ret_20D(%)"])}%`],
        ["시장 20일 수익률", `${formatCell(raw["MarketRet_20D(%)"])}%`],
      ]} />
    </div>
  );
}

export function TradeLogDetail({ row }: { row: Record<string, unknown> }) {
  const raw = asRecord(row.raw);
  const exitPlan = asRecord(raw.exit_plan);
  const quote = asRecord(raw.quote);
  const realtime = asRecord(raw.realtime);
  return (
    <div className="detail-grid">
      <DetailSection title="체결 정보" items={[
        ["구분", row.action_ko],
        ["종목", `${formatCell(row.name)} (${formatCell(row.code)})`],
        ["수량", row.qty],
        ["가격", row.price],
        ["시간", formatDateTime(row.created_at)],
        ["사유", row.reason_ko],
        ["원본 코드", raw.reason_code],
      ]} />
      <DetailSection title="언제 팔 건지" items={[
        ["매수가", exitPlan.entry_price],
        ["손절", exitPlan.stop_loss],
        ["손절률", formatPlanPct(exitPlan.stop_loss_pct) || formatPercentFromEntry(exitPlan.stop_loss, exitPlan.entry_price)],
        ["1차 익절", exitPlan.take_profit_1],
        ["1차 익절률", formatPlanPct(exitPlan.take_profit_1_pct) || formatPercentFromEntry(exitPlan.take_profit_1, exitPlan.entry_price)],
        ["2차 익절", exitPlan.take_profit_2],
        ["2차 익절률", formatPlanPct(exitPlan.take_profit_2_pct) || formatPercentFromEntry(exitPlan.take_profit_2, exitPlan.entry_price)],
        ["추적 손절", exitPlan.trailing_stop],
        ["추적 손절률", formatPlanPct(exitPlan.trailing_stop_pct) || formatPercentFromEntry(exitPlan.trailing_stop, exitPlan.entry_price)],
        ["권장 보유", `${formatCell(exitPlan.hold_min_days)}-${formatCell(exitPlan.hold_preferred_days)}일`],
        ["최대 보유", `${formatCell(exitPlan.hold_max_days)}일`],
        ["매입 시간", exitPlan.planned_entry_window || "14:30-15:20"],
        ["관리 시간", exitPlan.planned_manage_window || "09:00-15:20"],
      ]} />
      <DetailSection title="장중 확인값" items={[
        ["현재가", quote.current_price],
        ["당일 고가", quote.day_high],
        ["당일 저가", quote.day_low],
        ["누적 거래량", quote.accumulated_volume],
        ["VI 발동", Number(quote.vi_active || 0) > 0 ? "예" : "아니오"],
        ["주문 정책", formatOrderPolicy(raw.order_policy)],
        ["주문 응답", raw.order ? "저장됨" : "-"],
      ]} />
      <DetailSection title="실시간 호가/체결" items={[
        ["체결강도", realtime.strength],
        ["매수/매도 잔량비", realtime.bid_ask_ratio],
        ["호가 스프레드", realtime.spread_pct],
        ["샘플 수", realtime.samples],
        ["판단", realtime.reason],
      ]} />
    </div>
  );
}

export function AccountDetail({ row }: { row: Record<string, unknown> }) {
  const rowType = String(row.row_type || "");
  const holdings = Array.isArray(row.holdings) ? row.holdings : [];
  if (rowType === "summary") {
    return (
      <div className="detail-grid">
        <DetailSection title="계좌 요약" items={[
          ["계좌", row.account],
          ["예수금", `${formatCell(row.cash)}원`],
          ["총평가", `${formatCell(row.total_equity)}원`],
          ["보유 종목 수", `${formatCell(row.holdings_count)}종목`],
        ]} />
        <DetailSection title="보유 종목 요약" items={[
          ["보유 종목", holdings.length > 0 ? holdings.map((item) => {
            const holding = asRecord(item);
            return `${formatCell(holding.name || holding.code)} ${formatCell(holding.qty)}주`;
          }).join(" / ") : "보유 종목 없음"],
        ]} />
      </div>
    );
  }

  const avgPrice = Number(row.avg_price || 0);
  const currentPrice = Number(row.current_price || 0);
  const qty = Number(row.qty || 0);
  const evaluationAmount = Number(row.evaluation_amount || currentPrice * qty || 0);
  const investedAmount = avgPrice * qty;
  return (
    <div className="detail-grid">
      <DetailSection title="보유 종목" items={[
        ["계좌", row.account],
        ["종목", `${formatCell(row.name)} (${formatCell(row.code)})`],
        ["보유 수량", `${formatCell(row.qty)}주`],
        ["평균 매입가", `${formatCell(row.avg_price)}원`],
        ["현재가", `${formatCell(row.current_price)}원`],
        ["평가금액", `${formatCell(evaluationAmount)}원`],
        ["매입금액", `${formatCell(investedAmount)}원`],
      ]} />
      <DetailSection title="손익" items={[
        ["평가손익", `${formatCell(row.profit_loss)}원`],
        ["손익률", `${formatCell(row.profit_loss_rate)}%`],
        ["주당 손익", `${formatCell(currentPrice - avgPrice)}원`],
      ]} />
      <DetailSection title="확인 포인트" items={[
        ["자동매매 DB 포지션", "KIS 계좌 잔고 기준 정보입니다. 자동매매 포지션 상세는 포지션 메뉴에서 확인합니다."],
        ["가격 기준", "KIS 계좌 조회 시점의 현재가/평가금액 기준입니다."],
      ]} />
    </div>
  );
}

export function ReportStatusDetail({
  row,
  pending,
  onDownload,
}: {
  row: Record<string, unknown>;
  pending: boolean;
  onDownload: () => void;
}) {
  const completed = row.status === "completed";
  return (
    <div className="detail-grid">
      {completed && (
        <button className="primary detail-action" type="button" disabled={pending} onClick={onDownload}>
          {pending ? "다운로드 확인 중..." : "완료된 리포트 다운로드"}
        </button>
      )}
      <DetailSection title="리포트 상태" items={[
        ["종류", row.report_kind_ko],
        ["상태", row.status_ko],
        ["날짜", row.trade_date],
        ["종목", row.code === "ALL" ? "종합 리포트" : `${formatCell(row.name)} (${formatCell(row.code)})`],
        ["제목", row.title],
        ["생성 요청", formatDateTime(row.created_at)],
        ["시작", formatDateTime(row.started_at)],
        ["완료", formatDateTime(row.finished_at)],
        ["오류", row.error],
      ]} />
      {!completed && (
        <DetailSection title="다운로드 안내" items={[
          ["상태", "완료된 리포트만 다운로드할 수 있습니다."],
        ]} />
      )}
    </div>
  );
}

export function PositionDetail({
  row,
  pending,
  onForceLiquidate,
}: {
  row: Record<string, unknown>;
  pending: boolean;
  onForceLiquidate: () => void;
}) {
  const raw = asRecord(row.raw);
  const isOpen = String(row.status || "").toUpperCase() === "OPEN" && Number(row.remaining_qty || 0) > 0;
  return (
    <div className="detail-grid">
      {isOpen && (
        <button className="danger detail-action" type="button" disabled={pending} onClick={onForceLiquidate}>
          {pending ? "강제 청산 주문 중..." : "이 종목 시장가 강제 청산"}
        </button>
      )}
      <DetailSection title="보유 정보" items={[
        ["종목", `${formatCell(row.name)} (${formatCell(row.code)})`],
        ["매수일", row.entry_date],
        ["매수가", row.entry_price],
        ["총수량", row.qty],
        ["잔여수량", row.remaining_qty],
        ["상태", row.status],
      ]} />
      <DetailSection title="청산 계획" items={[
        ["손절", row.stop_loss],
        ["손절률", formatPercentFromEntry(row.stop_loss, row.entry_price)],
        ["1차 익절", row.take_profit_1],
        ["1차 익절률", formatPercentFromEntry(row.take_profit_1, row.entry_price)],
        ["2차 익절", row.take_profit_2],
        ["2차 익절률", formatPercentFromEntry(row.take_profit_2, row.entry_price)],
        ["추적 손절", row.trailing_stop],
        ["추적 손절률", formatPercentFromEntry(row.trailing_stop, row.entry_price)],
        ["최대 보유", `${formatCell(raw.HoldMaxDays)}일`],
        ["1차 익절 완료", row.take_profit_1_done ? "예" : "아니오"],
        ["2차 익절 완료", row.take_profit_2_done ? "예" : "아니오"],
      ]} />
    </div>
  );
}

export function DecisionDetail({ row }: { row: Record<string, unknown> }) {
  const raw = asRecord(row.raw);
  const quote = asRecord(raw.quote);
  const realtime = asRecord(raw.realtime);
  const sizing = asRecord(raw.sizing);
  const strategy = asRecord(raw.strategy);
  return (
    <div className="detail-grid">
      <DetailSection title="제외 판단" items={[
        ["종목", `${formatCell(row.name)} (${formatCell(row.code)})`],
        ["판단일", row.decision_date],
        ["점수", row.score],
        ["현재가", row.price],
        ["제외 사유", row.reason],
        ["사유 코드", row.reason_code],
        ["기록 시간", formatDateTime(row.created_at)],
      ]} />
      <DetailSection title="장중 값" items={[
        ["현재가", quote.current_price],
        ["당일 고가", quote.day_high],
        ["당일 저가", quote.day_low],
        ["누적 거래량", quote.accumulated_volume],
        ["VI 발동", Number(quote.vi_active || 0) > 0 ? "예" : "아니오"],
        ["호가 기준", quote.price_source],
      ]} />
      <DetailSection title="실시간 호가/체결" items={[
        ["체결강도", realtime.strength],
        ["매수/매도 잔량비", realtime.bid_ask_ratio],
        ["호가 스프레드", realtime.spread_pct],
        ["샘플 수", realtime.samples],
        ["판단", realtime.reason],
      ]} />
      <DetailSection title="전략/수량 조건" items={[
        ["최소 점수", strategy.min_score],
        ["진입가 하단 배율", strategy.min_entry_discount],
        ["진입가 상단 배율", strategy.max_entry_premium],
        ["고점 이탈 허용", strategy.max_pullback_from_day_high],
        ["계산 수량", sizing.qty],
        ["주문 가능금액", sizing.available_cash],
        ["리스크 기준 수량", sizing.risk_qty],
      ]} />
    </div>
  );
}

export function WatcherRunDetail({ row }: { row: Record<string, unknown> }) {
  const raw = asRecord(row.raw);
  const strategy = asRecord(raw.strategy);
  const actions = Array.isArray(raw.actions) ? raw.actions : [];
  return (
    <div className="detail-grid">
      <DetailSection title="실행 요약" items={[
        ["실행 시간", row.created_at],
        ["계좌 구분", row.mode],
        ["주문 허용", row.orders_allowed_ko],
        ["매수 시간대", row.entry_window_open ? "열림" : "아님"],
        ["관리 시간대", row.manage_window_open ? "열림" : "아님"],
        ["스킵 사유", row.skip_reason_ko],
        ["실행 단계", raw.stage],
        ["오류", raw.error],
      ]} />
      <DetailSection title="매수 가능 상태" items={[
        ["예수금", row.cash],
        ["총평가금", row.total_equity],
        ["시그널 수", row.signals_count],
        ["DB 포지션", row.open_positions_count],
        ["KIS 보유종목", row.kis_holdings_count],
        ["미체결 주문", row.pending_orders_count],
        ["오늘 진입 종목", row.today_entry_count],
        ["오늘 미체결 매수", row.today_pending_buy_count],
        ["오늘 손절 차단 종목", raw.today_stopped_out_count],
        ["오늘 기준선 이탈 차단 종목", raw.today_kijun_exit_count],
        ["오늘 남은 신규 슬롯", row.remaining_daily_slots],
        ["하루 실현손실", raw.daily_realized_loss],
        ["하루 손실 한도금액", raw.daily_loss_limit_amount],
        ["미실현 손익", raw.unrealized_pnl],
        ["미실현 손실", raw.unrealized_loss],
        ["미실현 손실 한도금액", raw.unrealized_loss_limit_amount],
        ["코스피 당일 수익률", raw.market_intraday_return_pct === undefined || raw.market_intraday_return_pct === null ? "-" : formatPct(Number(raw.market_intraday_return_pct))],
        ["보유 가능 슬롯", row.available_slots],
        ["금액 기준 슬롯", row.affordable_slots],
        ["오늘 신규 가능 슬롯", row.daily_slots],
      ]} />
      <DetailSection title="실행 결과" items={[
        ["전체 액션", row.action_count],
        ["매수 주문", row.buy_order_count],
        ["매도 주문", row.sell_order_count],
        ["쿨다운 스킵", row.cooldown_skip_count],
        ["액션 상세", actions.map((item) => {
          const action = asRecord(item);
          return `${formatCell(action.action)} ${formatCell(action.name || action.code)} ${formatCell(action.qty)}주 @ ${formatCell(action.price)}`;
        }).join(" / ")],
      ]} />
      <DetailSection title="전략 설정" items={[
        ["최소 점수", strategy.min_score],
        ["최대 보유 종목", strategy.max_open_positions],
        ["하루 신규 매수", strategy.max_new_positions_per_day],
        ["종목당 비중", strategy.position_capital_pct],
        ["최소 주문금액", strategy.min_order_amount],
        ["하루 손실 제한", strategy.use_daily_loss_limit ? formatPct(Number(strategy.daily_loss_limit_pct || 0)) : "미사용"],
        ["미실현손실 제한", strategy.use_unrealized_loss_limit ? formatPct(Number(strategy.unrealized_loss_limit_pct || 0)) : "미사용"],
        ["시장 급락 차단", strategy.use_market_crash_filter ? formatPct(Number(strategy.market_crash_limit_pct || 0)) : "미사용"],
        ["세금/수수료율", formatPct(Number(strategy.commission_tax_pct || 0))],
        ["실시간 필터", strategy.use_realtime_liquidity_filter ? "사용" : "미사용"],
        ["당일 손절 재매수 금지", strategy.use_stoploss_reentry_block ? "사용" : "미사용"],
        ["기준선 이탈 재매수 금지", strategy.use_kijun_reentry_block ? "사용" : "미사용"],
        ["VI 매수 차단", strategy.use_vi_filter ? "사용" : "미사용"],
        ["최소 체결강도", strategy.min_realtime_strength],
        ["최소 매수/매도 잔량비", strategy.min_bid_ask_ratio],
        ["최대 호가 스프레드", strategy.max_realtime_spread_pct],
      ]} />
    </div>
  );
}

export function BacktestRunDetail({ row }: { row: Record<string, unknown> }) {
  const progress = asRecord(row.progress);
  const result = asRecord(row.result);
  const trades = Array.isArray(result.trades) ? result.trades.map((item) => asRecord(item)) : [];
  const tradesByReturn = [...trades].sort((left, right) => Number(right.return_pct || 0) - Number(left.return_pct || 0));
  const topProfitTrades = tradesByReturn.slice(0, 5);
  const topLossTrades = [...tradesByReturn].reverse().slice(0, 5);
  const tested = result.signals_tested ?? progress.tested;
  const generated = result.generated_signals ?? progress.signals;
  const tradeRows = (items: Record<string, unknown>[]) => items.map((trade) => ({
    date: trade.trade_date,
    code: trade.code,
    name: trade.name,
    score: trade.score,
    entry: trade.entry,
    exit: trade.exit_price,
    return_pct: trade.return_pct === undefined ? "-" : `${formatCell(trade.return_pct)}%`,
    hold_days: trade.hold_days,
    reason: translateReason(trade.exit_reason),
  }));
  const tradeColumns = ["date", "code", "name", "score", "entry", "exit", "return_pct", "hold_days", "reason"];
  return (
    <div className="detail-grid">
      <DetailSection title="실행 정보" items={[
        ["실행 ID", row.run_id || row.job_id],
        ["상태", translateBacktestStatus(row.status)],
        ["기간", `${formatCell(row.start_date)} - ${formatCell(row.end_date)}`],
        ["검증 범위", `${formatCell(row.days)}일`],
        ["최대 검증 시그널", row.max_signals],
        ["전략", `${formatCell(row.strategy_key)} / ${formatCell(row.strategy_version)}`],
        ["유니버스", row.universe_scope],
        ["생성 시간", formatDateTime(row.created_at)],
        ["완료 시간", formatDateTime(row.finished_at || row.completed_at)],
        ["오류", row.error],
      ]} />
      <DetailSection title="진행 상태" items={[
        ["처리 종목", `${formatCell(progress.processed)}/${formatCell(progress.total)}`],
        ["누적 후보", generated],
        ["검증 거래", tested],
        ["스킵", progress.skipped],
      ]} />
      <DetailSection title="성과 요약" items={[
        ["승률", result.win_rate === undefined ? "-" : `${formatCell(result.win_rate)}%`],
        ["평균 수익률", result.avg_return_pct === undefined ? "-" : `${formatCell(result.avg_return_pct)}%`],
        ["평균 수익", result.avg_win_pct === undefined ? "-" : `${formatCell(result.avg_win_pct)}%`],
        ["평균 손실", result.avg_loss_pct === undefined ? "-" : `${formatCell(result.avg_loss_pct)}%`],
        ["최고 수익", result.best_return_pct === undefined ? "-" : `${formatCell(result.best_return_pct)}%`],
        ["최악 손실", result.worst_return_pct === undefined ? "-" : `${formatCell(result.worst_return_pct)}%`],
        ["평균 보유일", result.avg_hold_days === undefined ? "-" : `${formatCell(result.avg_hold_days)}일`],
        ["승/패", `${formatCell(result.win_count)} / ${formatCell(result.loss_count)}`],
      ]} />
      <section className="detail-section">
        <h3>수익률 TOP 5</h3>
        <MiniTable
          rows={tradeRows(topProfitTrades)}
          columns={tradeColumns}
          emptyLabel="수익 거래 없음"
        />
      </section>
      <section className="detail-section">
        <h3>최악 수익률 TOP 5</h3>
        <MiniTable
          rows={tradeRows(topLossTrades)}
          columns={tradeColumns}
          emptyLabel="손실 거래 없음"
        />
      </section>
      <section className="detail-section">
        <h3>거래 샘플</h3>
        <MiniTable
          rows={tradeRows(trades.slice(0, 20))}
          columns={tradeColumns}
          emptyLabel="완료된 거래 샘플 없음"
        />
      </section>
    </div>
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
    StopLossRepriced: "손절 미체결 재주문",
    StopLossMarketExit: "손절 최종 시장가 탈출",
    TrailingStop: "추적 손절가 도달",
    TimeExit: "최대 보유기간 도달",
    MaxHold: "최대 보유 후 청산",
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

export function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
