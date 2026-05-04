import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import {
  api,
  type AiReportType,
  type AiReportStatus,
  type BacktestJob,
  type BacktestResult,
  type BrokerAccount,
  type BrokerPayload,
  type BrokerStatus,
  type DailyDashboard,
  type Entitlements,
  type KisAccount,
  type StrategyPreset,
  type StrategySettings,
  type TelegramSettingsPayload,
  type TradeDecisionLog,
  type WatchJobOverview,
  type WatcherRun,
} from "./api";
import { AuthCard } from "./components/AuthCard";
import { BacktestPanel, ReportCalendarPanel, WatchJobPanel } from "./components/AdminPanels";
import {
  AccountPanel,
  AutoTradingRules,
  cleanErrorMessage,
  DailyDashboardPanel,
  dashboardPages,
  DashboardNav,
  DataPanel,
  downloadHtmlReport,
  hasCompletedReport,
  labelForPending,
  membershipLabel,
  StatusLine,
  StrategyPanel,
  WatcherIssuePanel,
} from "./components/DashboardParts";
import { DetailOverlay } from "./components/DetailViews";
import { Shell } from "./components/Shell";
import { defaultStrategy, strategyPresets } from "./strategyPresets";
import { supabase } from "./supabase";
import type { DashboardPage, DetailSelection, Status } from "./types";
import {
  delay,
  enrichPlanPercentRow,
  enrichTradeLogRow,
  exportBacktestTradesCsv,
  formatCell,
  formatDateTime,
  latestWatcherIssue,
  normalizeDecisionRow,
  normalizeTradeLogRow,
  normalizeWatcherRunRow,
} from "./utils/dashboard";

const emptyBroker: BrokerPayload = {
  kis_app_key: "",
  kis_app_secret: "",
  kis_account_no: "",
  kis_account_product_code: "01",
  mode: "paper",
  live_order_enabled: false,
};

const emptyTelegramSettings: TelegramSettingsPayload = {
  telegram_bot_token: "",
  telegram_chat_id: "",
};

export function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [loadingSession, setLoadingSession] = useState(true);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoadingSession(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      setLoadingSession(false);
    });

    return () => subscription.unsubscribe();
  }, []);

  if (loadingSession) {
    return <Shell><div className="panel">세션 확인 중...</div></Shell>;
  }

  return <Shell>{session ? <Dashboard session={session} /> : <AuthCard />}</Shell>;
}

function Dashboard({ session }: { session: Session }) {
  const [broker, setBroker] = useState<BrokerPayload>(emptyBroker);
  const [telegramSettings, setTelegramSettings] = useState<TelegramSettingsPayload>(emptyTelegramSettings);
  const [editingBroker, setEditingBroker] = useState(false);
  const [editingTelegram, setEditingTelegram] = useState(false);
  const [status, setStatus] = useState<Status>({ type: "idle", message: "" });
  const [brokerStatus, setBrokerStatus] = useState<BrokerStatus | null>(null);
  const [brokerAccounts, setBrokerAccounts] = useState<BrokerAccount[]>([]);
  const [signals, setSignals] = useState<Array<Record<string, unknown>>>([]);
  const [signalDates, setSignalDates] = useState<string[]>([]);
  const [selectedSignalDate, setSelectedSignalDate] = useState("");
  const [positions, setPositions] = useState<Array<Record<string, unknown>>>([]);
  const [logs, setLogs] = useState<Array<Record<string, unknown>>>([]);
  const [decisions, setDecisions] = useState<TradeDecisionLog[]>([]);
  const [watcherRuns, setWatcherRuns] = useState<WatcherRun[]>([]);
  const [watchJobOverview, setWatchJobOverview] = useState<WatchJobOverview | null>(null);
  const [dailyDashboard, setDailyDashboard] = useState<DailyDashboard | null>(null);
  const [entitlements, setEntitlements] = useState<Entitlements | null>(null);
  const [aiReports, setAiReports] = useState<AiReportStatus[]>([]);
  const [reportDates, setReportDates] = useState<string[]>([]);
  const [selectedReportDate, setSelectedReportDate] = useState("");
  const [reportStatuses, setReportStatuses] = useState<AiReportStatus[]>([]);
  const [backtest, setBacktest] = useState<BacktestResult | null>(null);
  const [backtestJob, setBacktestJob] = useState<BacktestJob | null>(null);
  const [backtestRuns, setBacktestRuns] = useState<BacktestJob[]>([]);
  const [backtestDays, setBacktestDays] = useState(120);
  const [kisAccount, setKisAccount] = useState<KisAccount | null>(null);
  const [strategy, setStrategy] = useState<StrategySettings>(defaultStrategy);
  const [editingStrategy, setEditingStrategy] = useState(false);
  const [autoLoadedAccountKey, setAutoLoadedAccountKey] = useState("");
  const [detail, setDetail] = useState<DetailSelection | null>(null);
  const [sharedNotice, setSharedNotice] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [activePage, setActivePage] = useState<DashboardPage>("overview");
  const isScanAdmin = Boolean(entitlements?.can_run_admin_scan);
  const canUseLiveTrading = Boolean(entitlements?.can_use_live_trading);
  const canUseReports = Boolean(entitlements?.can_use_reports);
  const hasRunningScan = dailyDashboard?.latest_scan?.status === "running";

  useEffect(() => {
    refresh();
  }, []);

  const activeAccountKey = brokerStatus?.configured
    ? brokerStatus.id || `${brokerStatus.mode}:${brokerStatus.account_no}:${brokerStatus.account_product_code || "01"}`
    : "";

  useEffect(() => {
    if (!brokerStatus?.configured || !activeAccountKey || autoLoadedAccountKey === activeAccountKey) return;

    let cancelled = false;
    api.getKisAccount(session)
      .then((result) => {
        if (!cancelled && result.ok) setKisAccount(result);
      })
      .finally(() => {
        if (!cancelled) setAutoLoadedAccountKey(activeAccountKey);
      });

    return () => {
      cancelled = true;
    };
  }, [session, brokerStatus?.configured, activeAccountKey, autoLoadedAccountKey]);

  async function run<T>(key: string, action: () => Promise<T>, doneMessage: string) {
    setPending(key);
    setStatus({ type: "info", message: `${labelForPending(key)} 실행 중...` });
    try {
      const result = await action();
      setStatus({ type: "info", message: `${doneMessage} ${JSON.stringify(result)}` });
      await refresh();
    } catch (error) {
      setStatus({ type: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setPending(null);
    }
  }

  async function loadKisAccount() {
    await run("account", async () => {
      const result = await api.getKisAccount(session);
      if (!result.ok) {
        throw new Error(result.error || "KIS 계좌 조회 실패");
      }
      setKisAccount(result);
      setAutoLoadedAccountKey(activeAccountKey);
      return {
        account: result.account,
        cash: result.cash,
        total_equity: result.total_equity,
        holdings_count: result.holdings_count,
      };
    }, "KIS 계좌 조회 완료:");
  }

  async function refreshDashboardOnly() {
    setPending("dashboardRefresh");
    try {
      const result = await api.dailyDashboard(session).catch(() => null);
      setDailyDashboard(result);
      setStatus({ type: "info", message: "대시보드 새로고침 완료" });
    } catch (error) {
      setStatus({ type: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setPending(null);
    }
  }

  async function refreshSignalsOnly() {
    if (!selectedSignalDate) return;
    setPending("signalsRefresh");
    try {
      const [signalResult, decisionResult, reportResult] = await Promise.all([
        api.signalsByDate(session, selectedSignalDate),
        api.tradeDecisions(session, selectedSignalDate).catch(() => []),
        canUseReports ? api.getAiReportStatuses(session, selectedSignalDate).catch(() => []) : Promise.resolve([]),
      ]);
      setSignals(signalResult);
      setDecisions(decisionResult);
      setAiReports(reportResult);
      setStatus({ type: "info", message: `시그널 새로고침 완료: ${signalResult.length}개` });
    } catch (error) {
      setStatus({ type: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setPending(null);
    }
  }

  async function refreshReportsOnly(tradeDate = selectedReportDate) {
    if (!tradeDate || !canUseReports) return;
    setSelectedReportDate(tradeDate);
    setReportStatuses([]);
    setPending("reportsRefresh");
    try {
      const [dateResult, statusResult] = await Promise.all([
        api.getAiReportDates(session).catch(() => reportDates),
        api.getAiReportStatuses(session, tradeDate).catch(() => []),
      ]);
      const filteredStatusResult = statusResult.filter((report) => report.trade_date === tradeDate);
      setReportDates(dateResult);
      setReportStatuses(filteredStatusResult);
      setStatus({ type: "info", message: `리포트 조회 완료: ${tradeDate} / ${filteredStatusResult.length}개` });
    } catch (error) {
      setStatus({ type: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setPending(null);
    }
  }

  async function refreshWatchJobsOnly() {
    if (!isScanAdmin) return;
    setPending("watchJobsRefresh");
    try {
      const result = await api.watchJobOverview(session);
      setWatchJobOverview(result);
      setStatus({ type: "info", message: "와쳐 작업 큐 새로고침 완료" });
    } catch (error) {
      setStatus({ type: "error", message: error instanceof Error ? cleanErrorMessage(error.message) : String(error) });
    } finally {
      setPending(null);
    }
  }

  async function retryFailedWatchJobs() {
    if (!isScanAdmin) return;
    await run(
      "watchJobsRetry",
      () => api.retryFailedWatchJobs(session),
      "실패 와쳐 작업 재시도 완료:",
    );
    await refreshWatchJobsOnly();
  }

  async function changeReportDate(tradeDate: string) {
    if (!tradeDate) return;
    await refreshReportsOnly(tradeDate);
  }

  async function refreshPositionsOnly() {
    setPending("positionsRefresh");
    try {
      const result = await api.positions(session);
      setPositions(result);
      setStatus({ type: "info", message: `포지션 새로고침 완료: ${result.length}개` });
    } catch (error) {
      setStatus({ type: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setPending(null);
    }
  }

  async function refreshTradeLogsOnly() {
    setPending("logsRefresh");
    try {
      const result = await api.tradeLogs(session);
      setLogs(result);
      setStatus({ type: "info", message: `매매 로그 새로고침 완료: ${result.length}개` });
    } catch (error) {
      setStatus({ type: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setPending(null);
    }
  }

  async function refreshDecisionsOnly() {
    if (!selectedSignalDate) return;
    setPending("decisionsRefresh");
    try {
      const result = await api.tradeDecisions(session, selectedSignalDate).catch(() => []);
      setDecisions(result);
      setStatus({ type: "info", message: `매수 제외 로그 새로고침 완료: ${result.length}개` });
    } catch (error) {
      setStatus({ type: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setPending(null);
    }
  }

  async function refreshWatcherRunsOnly() {
    setPending("watcherRunsRefresh");
    try {
      const result = await api.watcherRuns(session);
      setWatcherRuns(result);
      const issue = latestWatcherIssue(result);
      setStatus({ type: issue ? "error" : "info", message: issue ? `와쳐 오류 확인: ${formatCell(issue.reason)}` : "최근 와쳐 오류 없음" });
    } catch (error) {
      setStatus({ type: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setPending(null);
    }
  }

  async function startScan(universeScope: "limited" | "all" = "all") {
    setPending("scan");
    setStatus({ type: "info", message: universeScope === "all" ? "전 종목 스캔 요청 중..." : "스캔 요청 중..." });
    try {
      const started = await api.scan(session, universeScope);
      if (started.skipped || !started.queued || !started.scan_run_id) {
        setStatus({ type: "info", message: started.message || "오늘은 장이 열리지 않아 스캔을 실행하지 않았습니다." });
        await refresh();
        return;
      }
      setStatus({ type: "info", message: `${universeScope === "all" ? "전 종목" : "제한 유니버스"} 스캔 시작: 0/${started.total}개 처리` });
      await runScanSteps(started.scan_run_id);
    } catch (error) {
      setStatus({ type: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setPending(null);
    }
  }

  async function continueLatestScan() {
    setPending("scan");
    setStatus({ type: "info", message: "진행 중인 최신 스캔 확인 중..." });
    try {
      const latest = await api.latestScanRun(session);
      if (!latest || latest.status !== "running") {
        setStatus({ type: "info", message: "이어갈 running 상태의 스캔이 없습니다." });
        return;
      }
      const offset = latest.result?.offset || 0;
      const total = latest.result?.total || 0;
      setStatus({ type: "info", message: `스캔 이어서 처리: ${offset}/${total}개 처리됨` });
      await runScanSteps(latest.id);
    } catch (error) {
      setStatus({ type: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setPending(null);
    }
  }

  async function sendSharedTelegramNotice() {
    const message = sharedNotice.trim();
    if (!message) {
      setStatus({ type: "error", message: "공지 메시지를 입력하세요." });
      return;
    }
    await run(
      "telegramNotice",
      () => api.sendSharedTelegramNotice(session, message),
      "공용 텔레그램 공지 발송 완료:",
    );
    setSharedNotice("");
  }

  async function runScanSteps(scanRunId: number) {
    const maxSteps = 80;
    for (let index = 0; index < maxSteps; index += 1) {
      const current = await api.scanStep(session, scanRunId);
      const offset = current.result?.offset || 0;
      const total = current.result?.total || 0;
      const candidates = current.result?.candidates?.length || current.signals_count || 0;
      if (current.status === "completed") {
        setStatus({ type: "info", message: `스캔 완료: ${current.trade_date || "-"} / 후보 ${current.signals_count || 0}개 / 저장 ${current.shared_saved || 0}개` });
        await refresh();
        return;
      }
      if (current.status === "failed") {
        throw new Error(current.error || "스캔 실패");
      }
      setStatus({ type: "info", message: `스캔 진행: ${offset}/${total}개 처리 / 현재 후보 ${candidates}개` });
    }
    setStatus({ type: "info", message: "스캔 step 안전 제한에 도달했습니다. '진행 중 스캔 이어하기'를 누르면 같은 스캔을 이어서 처리합니다." });
  }

  async function runBacktest() {
    setPending("backtest");
    setStatus({ type: "info", message: "백테스트 잡 시작 중..." });
    try {
      const started = await api.startHistoricalBacktest(session, backtestDays, 300);
      await runBacktestLoop(started);
    } catch (error) {
      setStatus({ type: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setPending(null);
    }
  }

  async function resumeBacktest(runId: number | string) {
    setPending("backtest");
    setStatus({ type: "info", message: `백테스트 #${runId} 이어가기 중...` });
    try {
      const job = await api.getHistoricalBacktestJob(session, String(runId));
      await runBacktestLoop(job);
    } catch (error) {
      setStatus({ type: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setPending(null);
    }
  }

  async function runBacktestLoop(started: BacktestJob) {
    setBacktestJob(started);
    const runId = started.run_id || started.job_id;
    setStatus({ type: "info", message: "백테스트 실행 중: 진행상태를 DB에 저장하며 단계별로 계산합니다." });
    let current = started;
    let fetchFailures = 0;
    for (let attempt = 0; attempt < 240; attempt += 1) {
      try {
        current = await api.stepHistoricalBacktest(session, runId);
        fetchFailures = 0;
      } catch (error) {
        fetchFailures += 1;
        if (fetchFailures >= 3) throw error;
        setStatus({ type: "info", message: "백테스트 step이 잠시 실패했습니다. 저장된 진행 위치부터 다시 시도합니다." });
        await delay(3000);
        continue;
      }
      setBacktestJob(current);
      const progress = current.progress || {};
      if (current.status === "completed" && current.result) {
        setBacktest(current.result);
        setStatus({
          type: "info",
          message: `백테스트 완료: 재생성 후보 ${current.result.generated_signals || 0}개 / 검증 ${current.result.signals_tested}건 / 승률 ${current.result.win_rate}% / 평균 ${current.result.avg_return_pct}%`,
        });
        setBacktestRuns(await api.historicalBacktestRuns(session).catch(() => []));
        return;
      }
      if (current.status === "failed") {
        throw new Error(current.error || "백테스트 실패");
      }
      setStatus({
        type: "info",
        message: `백테스트 진행: ${progress.processed || 0}/${progress.total || 0}개 처리 / 누적 후보 ${progress.signals || 0}개`,
      });
      await delay(500);
    }
    setStatus({ type: "info", message: "백테스트 step 안전 제한에 도달했습니다. 같은 run id는 DB에 남아 있어 이어가기가 가능합니다." });
    setBacktestRuns(await api.historicalBacktestRuns(session).catch(() => []));
  }

  async function sendReport(tradeDate = selectedSignalDate) {
    if (!tradeDate) {
      setStatus({ type: "error", message: "리포트를 생성할 날짜가 없습니다." });
      return;
    }
    await run(
      "report",
      () => api.sendDailyReport(session, tradeDate, "report"),
      "AI 리포트 생성 큐 등록 완료:",
    );
  }

  async function sendBlogReport(tradeDate = selectedSignalDate) {
    if (!tradeDate) {
      setStatus({ type: "error", message: "블로그 글을 생성할 날짜가 없습니다." });
      return;
    }
    await run(
      "report",
      () => api.sendDailyReport(session, tradeDate, "blog"),
      "블로그 글 생성 큐 등록 완료:",
    );
  }

  async function handleDailyReportAction(tradeDate = selectedReportDate) {
    const completed = reportStatuses.some((report) => report.trade_date === tradeDate && report.report_type === "daily" && report.status === "completed");
    if (completed) {
      await downloadReport({
        key: "reportDownload",
        payload: { trade_date: tradeDate, report_type: "daily" as const },
      });
      return;
    }
    await sendReport(tradeDate);
  }

  async function handleDailyBlogReportAction(tradeDate = selectedReportDate) {
    const completed = reportStatuses.some((report) => report.trade_date === tradeDate && report.report_type === "daily_blog" && report.status === "completed");
    if (completed) {
      await downloadReport({
        key: "reportDownload",
        payload: { trade_date: tradeDate, report_type: "daily_blog" as const },
      });
      return;
    }
    await sendBlogReport(tradeDate);
  }

  async function sendSingleSignalReport(row: Record<string, unknown>) {
    const code = String(row.code || "").padStart(6, "0");
    if (!selectedSignalDate || !code) {
      setStatus({ type: "error", message: "리포트를 생성할 시그널 날짜 또는 종목코드가 없습니다." });
      return;
    }
    await run(
      "signalReport",
      () => api.sendSignalReport(session, { trade_date: selectedSignalDate, code, report_style: "report" }),
      "개별 기업 AI 리포트 생성 큐 등록 완료:",
    );
  }

  async function sendSingleSignalBlogReport(row: Record<string, unknown>) {
    const code = String(row.code || "").padStart(6, "0");
    if (!selectedSignalDate || !code) {
      setStatus({ type: "error", message: "블로그 글을 생성할 시그널 날짜 또는 종목코드가 없습니다." });
      return;
    }
    await run(
      "signalReport",
      () => api.sendSignalReport(session, { trade_date: selectedSignalDate, code, report_style: "blog" }),
      "개별 기업 블로그 글 생성 큐 등록 완료:",
    );
  }

  async function downloadSingleSignalReport(row: Record<string, unknown>) {
    const code = String(row.code || "").padStart(6, "0");
    const tradeDate = String(row.trade_date || selectedSignalDate || "");
    if (!tradeDate || !code) {
      setStatus({ type: "error", message: "다운로드할 리포트 날짜 또는 종목코드가 없습니다." });
      return;
    }
    await downloadReport({
      key: "signalReportDownload",
      payload: { trade_date: tradeDate, report_type: "signal" as const, code },
    });
  }

  async function downloadSingleSignalBlogReport(row: Record<string, unknown>) {
    const code = String(row.code || "").padStart(6, "0");
    const tradeDate = String(row.trade_date || selectedSignalDate || "");
    if (!tradeDate || !code) {
      setStatus({ type: "error", message: "다운로드할 블로그 글 날짜 또는 종목코드가 없습니다." });
      return;
    }
    await downloadReport({
      key: "signalReportDownload",
      payload: { trade_date: tradeDate, report_type: "signal_blog" as const, code },
    });
  }

  async function downloadReportStatus(row: Record<string, unknown>) {
    const reportType = String(row.report_type || "") as AiReportType;
    const tradeDate = String(row.trade_date || selectedSignalDate || "");
    const rawCode = String(row.code || "");
    const code = rawCode && rawCode !== "ALL" ? rawCode.padStart(6, "0") : undefined;
    if (!tradeDate || !reportType) {
      setStatus({ type: "error", message: "다운로드할 리포트 날짜 또는 종류가 없습니다." });
      return;
    }
    await downloadReport({
      key: reportType === "daily" || reportType === "daily_blog" ? "reportDownload" : "signalReportDownload",
      payload: { trade_date: tradeDate, report_type: reportType, code },
    });
  }

  async function forceLiquidatePosition(row: Record<string, unknown>) {
    const code = String(row.code || "").padStart(6, "0");
    const name = String(row.name || code);
    if (!code) {
      setStatus({ type: "error", message: "강제 청산할 종목코드가 없습니다." });
      return;
    }
    const confirmed = window.confirm(`${name} (${code}) 포지션을 시장가로 강제 청산할까요? 이 작업은 실제 주문을 낼 수 있습니다.`);
    if (!confirmed) return;
    await run(
      "forceLiquidate",
      () => api.forceLiquidatePosition(session, code, false),
      "강제 청산 주문 접수 완료:",
    );
    setDetail(null);
    await Promise.all([refreshPositionsOnly(), refreshTradeLogsOnly()]);
  }

  async function downloadReport({
    key,
    payload,
  }: {
    key: string;
    payload: { trade_date: string; report_type: AiReportType; code?: string };
  }) {
    setPending(key);
    setStatus({ type: "info", message: `${labelForPending(key)} 실행 중...` });
    try {
      const report = await api.getAiReport(session, payload);
      if (report.status !== "completed") {
        setStatus({ type: "info", message: `리포트가 아직 완료되지 않았습니다. 현재 상태: ${report.status}` });
        return;
      }
      if (!report.html) {
        setStatus({ type: "error", message: "완료된 리포트에 HTML 내용이 없습니다." });
        return;
      }
      downloadHtmlReport(report);
      setStatus({ type: "info", message: `리포트 다운로드 완료: ${report.title}` });
    } catch (error) {
      setStatus({ type: "error", message: error instanceof Error ? cleanErrorMessage(error.message) : String(error) });
    } finally {
      setPending(null);
    }
  }

  async function downloadBacktestTrades(row: Record<string, unknown>) {
    const runId = row.run_id || row.job_id;
    if (!runId) {
      setStatus({ type: "error", message: "다운로드할 백테스트 실행 ID가 없습니다." });
      return;
    }
    setPending("backtestExport");
    setStatus({ type: "info", message: "백테스트 전체 거래 CSV 생성 중..." });
    try {
      const trades = await api.historicalBacktestTrades(session, String(runId));
      exportBacktestTradesCsv(trades, `backtest_${runId}_trades.csv`);
      setStatus({ type: "info", message: `백테스트 전체 거래 다운로드 완료: ${trades.length}건` });
    } catch (error) {
      setStatus({ type: "error", message: error instanceof Error ? cleanErrorMessage(error.message) : String(error) });
    } finally {
      setPending(null);
    }
  }

  async function refresh() {
    try {
      const entitlementResult = await api.getEntitlements(session);
      setEntitlements(entitlementResult);

      const [brokerResult, accountResult, strategyResult, dateResult, reportDateResult, positionResult, logResult, watcherRunResult, dashboardResult, backtestRunResult, watchJobResult] = await Promise.all([
        api.getBrokerStatus(session),
        api.getBrokerAccounts(session),
        api.getStrategy(session),
        api.signalDates(session),
        entitlementResult.can_use_reports ? api.getAiReportDates(session).catch(() => []) : Promise.resolve([]),
        api.positions(session),
        api.tradeLogs(session),
        api.watcherRuns(session).catch(() => []),
        api.dailyDashboard(session).catch(() => null),
        entitlementResult.can_run_backtest ? api.historicalBacktestRuns(session).catch(() => []) : Promise.resolve([]),
        entitlementResult.can_run_admin_scan ? api.watchJobOverview(session).catch(() => null) : Promise.resolve(null),
      ]);
      const nextSignalDate = selectedSignalDate || dateResult[0] || "";
      const nextReportDate = selectedReportDate || reportDateResult[0] || nextSignalDate;
      const [signalResult, decisionResult, reportResult] = nextSignalDate
        ? await Promise.all([
            api.signalsByDate(session, nextSignalDate),
            api.tradeDecisions(session, nextSignalDate).catch(() => []),
            entitlementResult.can_use_reports ? api.getAiReportStatuses(session, nextSignalDate).catch(() => []) : Promise.resolve([]),
          ])
        : [[], [], []];
      const reportStatusResult = nextReportDate && entitlementResult.can_use_reports
        ? await api.getAiReportStatuses(session, nextReportDate).catch(() => [])
        : [];
      setBrokerStatus(brokerResult);
      setBrokerAccounts(accountResult);
      setStrategy(strategyResult);
      setSignalDates(dateResult);
      setSelectedSignalDate(nextSignalDate);
      setReportDates(reportDateResult);
      setSelectedReportDate(nextReportDate);
      setDailyDashboard(dashboardResult);
      if (brokerResult.configured) {
        setBroker((current) => ({
          ...current,
          kis_account_no: brokerResult.account_no || "",
          kis_account_product_code: brokerResult.account_product_code || "01",
          mode: brokerResult.mode || "paper",
          live_order_enabled: brokerResult.live_order_enabled || false,
        }));
        setTelegramSettings({ telegram_bot_token: "", telegram_chat_id: brokerResult.telegram_chat_id || "" });
        setEditingBroker(false);
        setEditingTelegram(false);
      }
      setSignals(signalResult);
      setAiReports(reportResult);
      setReportStatuses(reportStatusResult);
      setPositions(positionResult);
      setLogs(logResult);
      setWatcherRuns(watcherRunResult);
      setWatchJobOverview(watchJobResult);
      setDecisions(decisionResult);
      setBacktestRuns(backtestRunResult);
    } catch {
      // First-time users may not have credentials yet. Keep the form usable.
    }
  }

  async function saveBroker(event: React.FormEvent) {
    event.preventDefault();
    if (broker.mode === "live" && !canUseLiveTrading) {
      setStatus({ type: "error", message: "무료회원은 실전투자 계좌를 저장할 수 없습니다." });
      return;
    }
    setKisAccount(null);
    setAutoLoadedAccountKey("");
    await run("broker", () => api.saveBroker(session, broker), "KIS 정보 저장 완료:");
    setBroker((current) => ({ ...current, kis_app_key: "", kis_app_secret: "" }));
    setEditingBroker(false);
  }

  async function saveTelegram(event: React.FormEvent) {
    event.preventDefault();
    await run("telegram", () => api.saveTelegramSettings(session, telegramSettings), "매매 알림 저장 완료:");
    setTelegramSettings((current) => ({ ...current, telegram_bot_token: "" }));
    setEditingTelegram(false);
  }

  async function activateBrokerAccount(accountId: string) {
    setKisAccount(null);
    setAutoLoadedAccountKey("");
    await run("accountSwitch", () => api.activateBrokerAccount(session, accountId), "활성 계좌 변경 완료:");
  }

  function applyStrategyPreset(preset: StrategyPreset) {
    setStrategy(strategyPresets[preset]);
  }

  async function saveStrategy() {
    await run("strategy", () => api.saveStrategy(session, strategy), "전략 설정 저장 완료:");
    setEditingStrategy(false);
  }

  async function changeSignalDate(tradeDate: string) {
    setSelectedSignalDate(tradeDate);
    setPending("signals");
    setStatus({ type: "info", message: "시그널 조회 중..." });
    try {
      const [signalResult, decisionResult] = await Promise.all([
        api.signalsByDate(session, tradeDate),
        api.tradeDecisions(session, tradeDate).catch(() => []),
      ]);
      const reportResult = canUseReports ? await api.getAiReportStatuses(session, tradeDate).catch(() => []) : [];
      setSignals(signalResult);
      setAiReports(reportResult);
      setDecisions(decisionResult);
      setStatus({ type: "info", message: `시그널 조회 완료: ${tradeDate} / ${signalResult.length}개` });
    } catch (error) {
      setStatus({ type: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setPending(null);
    }
  }

  const shouldShowBrokerForm = !brokerStatus?.configured || editingBroker;
  const shouldShowTelegramForm = Boolean(brokerStatus?.configured && (!brokerStatus.telegram_configured || editingTelegram));
  const pages = dashboardPages({ isScanAdmin, canUseReports });
  const watcherIssue = latestWatcherIssue(watcherRuns);
  const accountSection = (
    <div className="grid two">
      <form className="panel" onSubmit={saveBroker}>
        <div className="section-title">
          <h2>KIS 연결</h2>
          {brokerStatus?.configured && (
            <button className="ghost small" type="button" onClick={() => setEditingBroker((value) => !value)}>
              {editingBroker ? "변경 취소" : "변경하기"}
            </button>
          )}
        </div>

        {brokerStatus?.configured && !editingBroker && (
          <div className="saved-box">
            <strong>저장된 연결 정보를 사용 중입니다.</strong>
            <span>계좌 {brokerStatus.account_no}-{brokerStatus.account_product_code || "01"}</span>
            <span>모드 {brokerStatus.mode || "paper"}</span>
            <span>실전주문 {brokerStatus.live_order_enabled ? "사용자 허용" : "사용자 차단"}</span>
            <span>매매 알림 {brokerStatus.telegram_configured ? "개인 봇 설정됨" : "미설정"}</span>
            {brokerStatus.mode === "live" && !brokerStatus.server_live_trading_allowed && (
              <span>서버 안전장치: 실전주문 차단 중</span>
            )}
            <p>앱키와 시크릿은 보안상 다시 표시하지 않습니다. 바꾸려면 변경하기를 누르고 새로 저장하세요.</p>
          </div>
        )}

        {brokerAccounts.length > 0 && (
          <div className="account-switcher">
            {brokerAccounts.map((account) => (
              <button
                key={account.id}
                className={account.is_active ? "account-chip active" : "account-chip"}
                type="button"
                disabled={pending !== null || account.is_active || (account.mode === "live" && !canUseLiveTrading)}
                onClick={() => activateBrokerAccount(account.id)}
              >
                <strong>{account.mode === "live" ? "실전투자" : "모의투자"}</strong>
                <span>{account.kis_account_no}-{account.kis_account_product_code}</span>
                <small>{account.mode === "live" && !canUseLiveTrading ? "유료회원 이상 사용 가능" : account.is_active ? `현재 사용 중 · 자동매매 ${account.enabled ? "ON" : "OFF"} · 매매알림 ${account.telegram_configured ? "ON" : "OFF"}` : "교체하기"}</small>
              </button>
            ))}
          </div>
        )}

        {shouldShowBrokerForm && (
          <>
            <label>
              KIS App Key
              <input value={broker.kis_app_key} onChange={(event) => setBroker({ ...broker, kis_app_key: event.target.value })} required />
            </label>
            <label>
              KIS App Secret
              <textarea value={broker.kis_app_secret} onChange={(event) => setBroker({ ...broker, kis_app_secret: event.target.value })} required />
            </label>
            <div className="grid two tight">
              <label>
                계좌번호 8자리
                <input value={broker.kis_account_no} onChange={(event) => setBroker({ ...broker, kis_account_no: event.target.value })} required />
              </label>
              <label>
                상품코드
                <input value={broker.kis_account_product_code} onChange={(event) => setBroker({ ...broker, kis_account_product_code: event.target.value })} required />
              </label>
            </div>
            <label>
              계좌 모드
              <select value={broker.mode} onChange={(event) => setBroker({ ...broker, mode: event.target.value as "paper" | "live", live_order_enabled: false })}>
                <option value="paper">모의투자</option>
                <option value="live" disabled={!canUseLiveTrading}>실전투자{canUseLiveTrading ? "" : " - 유료회원 이상"}</option>
              </select>
            </label>
            {!canUseLiveTrading && (
              <p className="command-copy">무료회원은 모의투자만 사용할 수 있습니다. 실전투자 계좌 저장과 실전 자동매매는 백엔드에서도 차단됩니다.</p>
            )}
            {broker.mode === "live" && (
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={broker.live_order_enabled}
                  onChange={(event) => setBroker({ ...broker, live_order_enabled: event.target.checked })}
                />
                실전 주문을 이 계정에서 허용
              </label>
            )}
            <button className="primary" disabled={pending === "broker"}>{pending === "broker" ? "저장 중..." : "저장"}</button>
          </>
        )}
      </form>

      <form className="panel" onSubmit={saveTelegram}>
        <div className="section-title">
          <h2>매매 알림</h2>
          {brokerStatus?.configured && brokerStatus.telegram_configured && (
            <button className="ghost small" type="button" onClick={() => setEditingTelegram((value) => !value)}>
              {editingTelegram ? "변경 취소" : "변경하기"}
            </button>
          )}
        </div>
        {brokerStatus?.configured && brokerStatus.telegram_configured && !editingTelegram && (
          <div className="saved-box">
            <strong>개인 텔레그램 봇 알림을 사용 중입니다.</strong>
            <span>Chat ID {brokerStatus.telegram_chat_id || "저장됨"}</span>
            <span>매수/매도 알림 ON</span>
            <span>Shared signal 알림 ON</span>
            <p>봇 토큰은 보안상 다시 표시하지 않습니다. 바꾸려면 변경하기를 누르고 새 토큰을 저장하세요.</p>
          </div>
        )}
        {!brokerStatus?.configured && (
          <p className="command-copy">KIS 계좌를 먼저 저장한 뒤 매매 알림을 설정할 수 있습니다.</p>
        )}
        {shouldShowTelegramForm && (
          <>
            <p className="command-copy">KIS 키와 별도로 저장합니다. 매수/매도 알림과 shared signal 알림을 받을 개인 텔레그램 봇 설정입니다.</p>
            <label>
              Telegram Bot Token
              <input
                value={telegramSettings.telegram_bot_token || ""}
                onChange={(event) => setTelegramSettings({ ...telegramSettings, telegram_bot_token: event.target.value })}
                placeholder="개인 봇 토큰"
              />
              <small>이미 저장된 토큰은 다시 표시하지 않습니다. 비워두면 기존 토큰을 유지합니다.</small>
            </label>
            <label>
              Telegram Chat ID
              <input
                value={telegramSettings.telegram_chat_id || ""}
                onChange={(event) => setTelegramSettings({ ...telegramSettings, telegram_chat_id: event.target.value })}
                placeholder="예: 6583699681"
              />
            </label>
            <button className="primary" disabled={pending === "telegram"}>
              {pending === "telegram" ? "저장 중..." : "매매 알림 저장"}
            </button>
          </>
        )}
      </form>

      <AccountPanel
        account={kisAccount}
        onRefresh={loadKisAccount}
        refreshing={pending === "account"}
        onDetail={(title, row) => setDetail({ title, kind: "account", row })}
      />
    </div>
  );

  return (
    <section className="dashboard">
      <div className="topbar">
        <div>
          <strong>{session.user.email}</strong>
          <span>
            {brokerStatus?.configured
              ? `KIS 저장됨 · ${brokerStatus.account_no}-${brokerStatus.account_product_code || "01"} · 자동매매 ${brokerStatus.enabled ? "ON" : "OFF"}`
              : "KIS 연결 정보 필요"}
          </span>
          <span>회원 유형 {membershipLabel(entitlements?.role)}</span>
        </div>
        <button className="ghost" onClick={() => supabase.auth.signOut()}>로그아웃</button>
      </div>

      <DashboardNav pages={pages} activePage={activePage} onChange={setActivePage} />

      {activePage === "overview" && (
        <div className="page-stack">
          <div className="grid two">
            <div className="panel command">
              <h2>자동매매</h2>
              <p className="command-copy">현재 활성 계정 기준으로 주문 감시를 켜거나 끕니다. 상세 설정은 전략 페이지에서 조정합니다.</p>
              <button disabled={pending !== null || !brokerStatus?.configured || brokerStatus?.enabled} onClick={() => run("enable", () => api.setAutoTradingEnabled(session, true), "자동매매 ON 완료:")}>
                {pending === "enable" ? "자동매매 켜는 중..." : "자동매매 ON"}
              </button>
              <button disabled={pending !== null || !brokerStatus?.configured || !brokerStatus?.enabled} onClick={() => run("disable", () => api.setAutoTradingEnabled(session, false), "자동매매 OFF 완료:")}>
                {pending === "disable" ? "자동매매 끄는 중..." : "자동매매 OFF"}
              </button>
              <button disabled={pending !== null || !brokerStatus?.configured} onClick={loadKisAccount}>
                {pending === "account" ? "계좌 조회 중..." : "KIS 계좌 조회"}
              </button>
              <a className="telegram-link" href="https://t.me/+TG17XtRVldkwYThl" target="_blank" rel="noreferrer">
                공용 텔레그램 공지방 추가하기
              </a>
              <StatusLine status={status} />
            </div>
            <DailyDashboardPanel dashboard={dailyDashboard} onRefresh={refreshDashboardOnly} refreshing={pending === "dashboardRefresh"} />
          </div>
          <AutoTradingRules strategy={strategy} mode={brokerStatus?.mode} liveOrderEnabled={brokerStatus?.live_order_enabled || false} serverLiveTradingAllowed={brokerStatus?.server_live_trading_allowed || false} />
        </div>
      )}

      {activePage === "signals" && (
        <div className="grid">
          <DataPanel
            title={selectedSignalDate ? `${selectedSignalDate} 시그널` : "시그널"}
            rows={signals.map(enrichPlanPercentRow)}
            columns={["score", "핵심군", "name", "entry", "stop_loss", "stop_loss_pct", "take_profit_2", "take_profit_2_pct", "code"]}
            maxRows={30}
            headerAction={signalDates.length > 0 ? (
              <div className="panel-actions">
                <select className="compact-select" value={selectedSignalDate} onChange={(event) => changeSignalDate(event.target.value)}>
                  {signalDates.map((tradeDate) => <option key={tradeDate} value={tradeDate}>{tradeDate}</option>)}
                </select>
                <button className="ghost small" type="button" disabled={pending === "signalsRefresh"} onClick={refreshSignalsOnly}>
                  {pending === "signalsRefresh" ? "갱신 중" : "새로고침"}
                </button>
              </div>
            ) : undefined}
            onRowClick={(row) => setDetail({ title: `${formatCell(row.name)} (${formatCell(row.code)})`, kind: "signal", row })}
          />
        </div>
      )}

      {activePage === "account" && accountSection}

      {activePage === "trading" && (
        <div className="page-stack">
          <div className="grid two">
            <DataPanel
              title="포지션"
              rows={positions.map(enrichPlanPercentRow)}
              columns={["code", "name", "entry_price", "stop_loss_pct", "take_profit_2_pct", "qty", "remaining_qty", "status"]}
              headerAction={(
                <button className="ghost small" type="button" disabled={pending === "positionsRefresh"} onClick={refreshPositionsOnly}>
                  {pending === "positionsRefresh" ? "갱신 중" : "새로고침"}
                </button>
              )}
              onRowClick={(row) => setDetail({ title: `${formatCell(row.name)} 포지션`, kind: "position", row })}
            />
            <DataPanel
              title="매매 로그"
              rows={logs.map(normalizeTradeLogRow).map(enrichPlanPercentRow)}
              columns={["action_ko", "name", "price", "qty", "stop_loss_pct", "take_profit_2_pct", "reason_ko", "created_at"]}
              className="trade-log-panel"
              pagination
              pageSize={12}
              headerAction={(
                <button className="ghost small" type="button" disabled={pending === "logsRefresh"} onClick={refreshTradeLogsOnly}>
                  {pending === "logsRefresh" ? "갱신 중" : "새로고침"}
                </button>
              )}
              onRowClick={(row) => setDetail({
                title: `${formatCell(row.action_ko)} ${formatCell(row.code)}`,
                kind: "log",
                row: enrichTradeLogRow(row, positions, signals),
              })}
            />
          </div>
          <div className="grid two">
            <DataPanel
              title={selectedSignalDate ? `${selectedSignalDate} 매수 제외 로그` : "매수 제외 로그"}
              rows={decisions.map(normalizeDecisionRow)}
              columns={["code", "name", "score", "price", "reason", "created_at"]}
              maxRows={30}
              headerAction={(
                <button className="ghost small" type="button" disabled={pending === "decisionsRefresh" || !selectedSignalDate} onClick={refreshDecisionsOnly}>
                  {pending === "decisionsRefresh" ? "갱신 중" : "새로고침"}
                </button>
              )}
              onRowClick={(row) => setDetail({
                title: `${formatCell(row.name)} 제외 사유`,
                kind: "decision",
                row,
              })}
            />
            {watcherIssue && (
              <WatcherIssuePanel
                issue={watcherIssue}
                refreshing={pending === "watcherRunsRefresh"}
                onRefresh={refreshWatcherRunsOnly}
              />
            )}
          </div>
        </div>
      )}

      {activePage === "strategy" && (
        <div className="page-stack">
          <StrategyPanel
            strategy={strategy}
            editing={editingStrategy}
            pending={pending === "strategy"}
            onToggleEdit={() => setEditingStrategy((value) => !value)}
            onPresetChange={applyStrategyPreset}
            onChange={setStrategy}
            onSave={saveStrategy}
          />
          <AutoTradingRules strategy={strategy} mode={brokerStatus?.mode} liveOrderEnabled={brokerStatus?.live_order_enabled || false} serverLiveTradingAllowed={brokerStatus?.server_live_trading_allowed || false} />
        </div>
      )}

      {activePage === "admin" && (
        <div className="page-stack">
          {isScanAdmin && (
            <div className="panel command admin-command">
              <h2>스캔/공지 관리자 메뉴</h2>
              <>
                <button disabled={pending !== null} onClick={() => startScan("all")}>
                  {pending === "scan" ? "스캔 중... 100개씩 처리" : "오늘 시그널 스캔"}
                </button>
                <button disabled={pending !== null} onClick={() => startScan("limited")}>
                  {pending === "scan" ? "스캔 중..." : "제한 유니버스 스캔"}
                </button>
                {hasRunningScan && (
                  <button disabled={pending !== null} onClick={continueLatestScan}>
                    {pending === "scan" ? "스캔 중..." : "진행 중 스캔 이어하기"}
                  </button>
                )}
                <div className="admin-notice-box">
                  <textarea
                    value={sharedNotice}
                    onChange={(event) => setSharedNotice(event.target.value)}
                    placeholder="공용 텔레그램으로 보낼 공지사항을 입력하세요."
                    rows={4}
                  />
                  <button disabled={pending !== null || !sharedNotice.trim()} onClick={sendSharedTelegramNotice}>
                    {pending === "telegramNotice" ? "공지 발송 중..." : "공용 텔레그램 공지 발송"}
                  </button>
                </div>
              </>
            </div>
          )}
          <StatusLine status={status} />
          <div className="grid two">
            {canUseReports && (
              <ReportCalendarPanel
                selectedDate={selectedReportDate}
                dates={reportDates}
                rows={reportStatuses}
                refreshing={pending === "reportsRefresh"}
                reportPending={pending === "report"}
                downloadPending={pending === "reportDownload"}
                onDateChange={changeReportDate}
                onRefresh={() => refreshReportsOnly()}
                onDailyReportAction={() => handleDailyReportAction(selectedReportDate)}
                onDailyBlogReportAction={() => handleDailyBlogReportAction(selectedReportDate)}
                onRowClick={(row) => setDetail({
                  title: `${formatCell(row.report_kind_ko)} ${formatCell(row.name || row.code)}`,
                  kind: "report",
                  row,
                })}
              />
            )}
            {isScanAdmin && (
              <BacktestPanel
                result={backtest}
                job={backtestJob}
                runs={backtestRuns}
                days={backtestDays}
                pending={pending === "backtest"}
                onDaysChange={setBacktestDays}
                onRun={runBacktest}
                onResume={resumeBacktest}
                onRunDetail={(run) => setDetail({
                  title: `백테스트 #${run.run_id || run.job_id}`,
                  kind: "backtest",
                  row: run as unknown as Record<string, unknown>,
                })}
              />
            )}
            {isScanAdmin && (
              <WatchJobPanel
                overview={watchJobOverview}
                pending={pending === "watchJobsRefresh" || pending === "watchJobsRetry"}
                onRefresh={refreshWatchJobsOnly}
                onRetryFailed={retryFailedWatchJobs}
              />
            )}
          </div>
        </div>
      )}
      {detail && (
        <DetailOverlay
          detail={detail}
          isScanAdmin={isScanAdmin}
          pending={pending}
          onSendSignalReport={sendSingleSignalReport}
          onSendSignalBlogReport={sendSingleSignalBlogReport}
          onDownloadSignalReport={downloadSingleSignalReport}
          onDownloadSignalBlogReport={downloadSingleSignalBlogReport}
          onDownloadReportStatus={downloadReportStatus}
          onDownloadBacktestTrades={downloadBacktestTrades}
          onForceLiquidatePosition={forceLiquidatePosition}
          aiReports={aiReports}
          onClose={() => setDetail(null)}
        />
      )}
    </section>
  );
}
