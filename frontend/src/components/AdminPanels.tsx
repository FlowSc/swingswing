import type { AiReportStatus, BacktestJob, BacktestResult, WatchJobOverview } from "../api";
import { formatCell, normalizeAiReportStatusRow, translateBacktestStatus, translateReason } from "../utils/dashboard";
import { MiniTable } from "./DashboardParts";

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

export function WatchJobPanel({
  overview,
  pending,
  onRefresh,
  onRetryFailed,
}: {
  overview: WatchJobOverview | null;
  pending: boolean;
  onRefresh: () => void;
  onRetryFailed: () => void;
}) {
  const statusCounts = overview?.status_counts || {};
  const typeCounts = overview?.type_counts || {};
  const rows = (overview?.jobs || []).slice(0, 20).map((job) => ({
    id: job.id,
    type: translateJobType(job.job_type),
    status: translateJobStatus(job.status),
    attempts: job.attempts,
    scheduled_for: job.scheduled_for,
    run_after: job.run_after,
    locked_by: job.locked_by || "-",
    error: job.error || "-",
  }));

  return (
    <section className="panel data-panel watch-job-panel">
      <div className="data-panel-head">
        <div>
          <h2>와쳐 작업 큐</h2>
          <p className="panel-subtitle">계좌별 자동매매 작업 상태와 적체/실패 여부를 확인합니다.</p>
        </div>
        <div className="backtest-controls">
          <button className="ghost small" type="button" disabled={pending} onClick={onRefresh}>
            {pending ? "갱신 중" : "새로고침"}
          </button>
          <button className="small" type="button" disabled={pending || !statusCounts.failed} onClick={onRetryFailed}>
            실패 작업 재시도
          </button>
        </div>
      </div>
      <div className="metric-grid compact">
        <div className="metric-card"><span>대기</span><strong>{statusCounts.pending || 0}</strong></div>
        <div className="metric-card"><span>실행</span><strong>{statusCounts.running || 0}</strong></div>
        <div className="metric-card"><span>실패</span><strong>{statusCounts.failed || 0}</strong></div>
        <div className="metric-card"><span>스킵</span><strong>{statusCounts.skipped || 0}</strong></div>
        <div className="metric-card"><span>5분 와쳐</span><strong>{typeCounts.intraday || 0}</strong></div>
        <div className="metric-card"><span>1분 감시</span><strong>{typeCounts.realtime_position || 0}</strong></div>
        <div className="metric-card"><span>최대 대기</span><strong>{formatAge(overview?.oldest_pending_seconds)}</strong></div>
        <div className="metric-card"><span>락 초과</span><strong>{overview?.running_overdue || 0}</strong></div>
      </div>
      {(overview?.failures || []).length > 0 && (
        <div className="watch-failure-list">
          <h3>실패/스킵 사유 TOP</h3>
          {(overview?.failures || []).map((item) => (
            <span key={item.reason}>{item.reason} · {item.count}</span>
          ))}
        </div>
      )}
      <MiniTable
        rows={rows}
        columns={["id", "type", "status", "attempts", "scheduled_for", "run_after", "locked_by", "error"]}
        emptyLabel="최근 와쳐 작업 없음"
      />
    </section>
  );
}

function translateJobType(value: string) {
  if (value === "intraday") return "5분 와쳐";
  if (value === "realtime_position") return "1분 포지션 감시";
  return value;
}

function translateJobStatus(value: string) {
  const labels: Record<string, string> = {
    pending: "대기",
    running: "실행 중",
    completed: "완료",
    failed: "실패",
    skipped: "스킵",
  };
  return labels[value] || value;
}

function formatAge(seconds?: number | null) {
  if (seconds === null || seconds === undefined) return "-";
  if (seconds < 60) return `${seconds}초`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}분`;
  return `${Math.round(seconds / 3600)}시간`;
}
