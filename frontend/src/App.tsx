import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import {
  api,
  type AiReport,
  type AiReportType,
  type AiReportStatus,
  type BacktestResult,
  type BrokerAccount,
  type BrokerPayload,
  type BrokerStatus,
  type DailyDashboard,
  type KisAccount,
  type StrategyPreset,
  type StrategySettings,
  type TelegramSettingsPayload,
  type TradeDecisionLog,
  type WatcherRun,
} from "./api";
import { supabase } from "./supabase";

type AuthMode = "login" | "signup";
type Status = { type: "idle" | "info" | "error"; message: string };
type DetailKind = "signal" | "log" | "position" | "account" | "decision" | "watcher";
type DetailSelection = { title: string; kind: DetailKind; row: Record<string, unknown> };

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

const strategyPresets: Record<StrategyPreset, StrategySettings> = {
  conservative: {
    preset: "conservative",
    min_score: 13,
    max_open_positions: 4,
    max_new_positions_per_day: 1,
    position_capital_pct: 0.12,
    risk_per_trade_pct: 0.007,
    min_order_amount: 100000,
    min_entry_discount: 0.995,
    max_entry_premium: 1.015,
    max_pullback_from_day_high: 0.02,
    use_kijun_filter: true,
    use_bb_upper_filter: true,
    use_day_candle_filter: false,
    use_breakeven_after_tp1: false,
    use_kijun_exit: false,
    use_kijun_reentry_block: true,
    use_daily_loss_limit: true,
    daily_loss_limit_pct: 0.02,
    use_unrealized_loss_limit: true,
    unrealized_loss_limit_pct: 0.03,
    use_market_crash_filter: true,
    market_crash_limit_pct: -0.02,
    commission_tax_pct: 0.002,
    use_realtime_liquidity_filter: true,
    min_realtime_strength: 80,
    min_bid_ask_ratio: 0.7,
    max_realtime_spread_pct: 0.01,
    use_stoploss_reentry_block: true,
    use_vi_filter: true,
  },
  balanced: {
    preset: "balanced",
    min_score: 12,
    max_open_positions: 5,
    max_new_positions_per_day: 2,
    position_capital_pct: 0.18,
    risk_per_trade_pct: 0.01,
    min_order_amount: 100000,
    min_entry_discount: 0.995,
    max_entry_premium: 1.02,
    max_pullback_from_day_high: 0.03,
    use_kijun_filter: true,
    use_bb_upper_filter: true,
    use_day_candle_filter: false,
    use_breakeven_after_tp1: false,
    use_kijun_exit: false,
    use_kijun_reentry_block: true,
    use_daily_loss_limit: true,
    daily_loss_limit_pct: 0.03,
    use_unrealized_loss_limit: true,
    unrealized_loss_limit_pct: 0.04,
    use_market_crash_filter: true,
    market_crash_limit_pct: -0.02,
    commission_tax_pct: 0.002,
    use_realtime_liquidity_filter: true,
    min_realtime_strength: 75,
    min_bid_ask_ratio: 0.65,
    max_realtime_spread_pct: 0.012,
    use_stoploss_reentry_block: true,
    use_vi_filter: true,
  },
  aggressive: {
    preset: "aggressive",
    min_score: 10,
    max_open_positions: 7,
    max_new_positions_per_day: 3,
    position_capital_pct: 0.25,
    risk_per_trade_pct: 0.015,
    min_order_amount: 100000,
    min_entry_discount: 0.99,
    max_entry_premium: 1.03,
    max_pullback_from_day_high: 0.04,
    use_kijun_filter: true,
    use_bb_upper_filter: true,
    use_day_candle_filter: false,
    use_breakeven_after_tp1: false,
    use_kijun_exit: false,
    use_kijun_reentry_block: true,
    use_daily_loss_limit: true,
    daily_loss_limit_pct: 0.04,
    use_unrealized_loss_limit: true,
    unrealized_loss_limit_pct: 0.05,
    use_market_crash_filter: true,
    market_crash_limit_pct: -0.025,
    commission_tax_pct: 0.002,
    use_realtime_liquidity_filter: true,
    min_realtime_strength: 70,
    min_bid_ask_ratio: 0.6,
    max_realtime_spread_pct: 0.015,
    use_stoploss_reentry_block: true,
    use_vi_filter: true,
  },
};

const defaultStrategy = strategyPresets.balanced;

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

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="page">
      <section className="hero">
        <div>
          <p className="eyebrow">KOSPI AUTOMATED SWING</p>
          <h1>스윙봇</h1>
        </div>
        <div className="hero-card">
          <strong>KIS OPEN API 기반</strong>
        </div>
      </section>
      {children}
    </main>
  );
}

function AuthCard() {
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [status, setStatus] = useState<Status>({ type: "idle", message: "" });
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setStatus({ type: "idle", message: "" });

    try {
      if (mode === "signup") {
        await api.signup({ email, password, invite_code: inviteCode });
        const signIn = await supabase.auth.signInWithPassword({ email, password });
        if (signIn.error) {
          setStatus({ type: "info", message: "가입 완료. 이메일 인증 설정이 켜져 있으면 메일 확인 후 로그인하세요." });
          return;
        }
        setStatus({ type: "info", message: "가입 및 로그인 완료." });
        return;
      }

      const result = await supabase.auth.signInWithPassword({ email, password });
      if (result.error) {
        setStatus({ type: "error", message: result.error.message });
        return;
      }
      setStatus({ type: "info", message: "로그인 완료." });
    } catch (error) {
      setStatus({ type: "error", message: error instanceof Error ? cleanErrorMessage(error.message) : String(error) });
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="auth-grid">
      <form className="panel auth-panel" onSubmit={submit}>
        <div className="toggle">
          <button type="button" className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>로그인</button>
          <button type="button" className={mode === "signup" ? "active" : ""} onClick={() => setMode("signup")}>회원가입</button>
        </div>

        <label>
          이메일
          <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" placeholder="name@example.com" required />
        </label>
        <label>
          비밀번호
          <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" minLength={6} required />
        </label>
        {mode === "signup" && (
          <label>
            가입 코드
            <input value={inviteCode} onChange={(event) => setInviteCode(event.target.value)} type="password" required />
          </label>
        )}

        <button className="primary" disabled={pending}>{pending ? "처리 중..." : mode === "login" ? "로그인" : "회원가입"}</button>
        <StatusLine status={status} />
      </form>

      <aside className="panel explain">
        <h2>흐름</h2>
        <p>Supabase Auth로 로그인하고, FastAPI에는 Supabase access token만 전달합니다.</p>
        <p>KIS app secret은 백엔드에서 암호화되어 Supabase에 저장됩니다.</p>
      </aside>
    </section>
  );
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
  const [dailyDashboard, setDailyDashboard] = useState<DailyDashboard | null>(null);
  const [aiReports, setAiReports] = useState<AiReportStatus[]>([]);
  const [backtest, setBacktest] = useState<BacktestResult | null>(null);
  const [backtestDays, setBacktestDays] = useState(120);
  const [kisAccount, setKisAccount] = useState<KisAccount | null>(null);
  const [strategy, setStrategy] = useState<StrategySettings>(defaultStrategy);
  const [editingStrategy, setEditingStrategy] = useState(false);
  const [autoLoadedAccountKey, setAutoLoadedAccountKey] = useState("");
  const [detail, setDetail] = useState<DetailSelection | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const isScanAdmin = (session.user.email || "").toLowerCase() === "zelatool@gmail.com";
  const dailyReportCompleted = hasCompletedReport(aiReports, "daily");
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
        isScanAdmin ? api.getAiReportStatuses(session, selectedSignalDate).catch(() => []) : Promise.resolve([]),
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
      setStatus({ type: "info", message: `와쳐 실행 로그 새로고침 완료: ${result.length}개` });
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
    setStatus({ type: "info", message: "백테스트 실행 중..." });
    try {
      const result = await api.backtestSharedSignals(session, backtestDays, 300);
      setBacktest(result);
      setStatus({
        type: "info",
        message: `백테스트 완료: ${result.signals_tested}건 / 승률 ${result.win_rate}% / 평균 ${result.avg_return_pct}%`,
      });
    } catch (error) {
      setStatus({ type: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setPending(null);
    }
  }

  async function sendReport() {
    await run(
      "report",
      () => api.sendDailyReport(session, selectedSignalDate || undefined, "report"),
      "AI 리포트 생성 큐 등록 완료:",
    );
  }

  async function sendBlogReport() {
    await run(
      "report",
      () => api.sendDailyReport(session, selectedSignalDate || undefined, "blog"),
      "블로그 글 생성 큐 등록 완료:",
    );
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

  async function downloadDailyReport() {
    if (!selectedSignalDate) {
      setStatus({ type: "error", message: "다운로드할 리포트 날짜가 없습니다." });
      return;
    }
    await downloadReport({
      key: "reportDownload",
      payload: { trade_date: selectedSignalDate, report_type: "daily" as const },
    });
  }

  async function downloadDailyBlogReport() {
    if (!selectedSignalDate) {
      setStatus({ type: "error", message: "다운로드할 블로그 글 날짜가 없습니다." });
      return;
    }
    await downloadReport({
      key: "reportDownload",
      payload: { trade_date: selectedSignalDate, report_type: "daily_blog" as const },
    });
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

  async function refresh() {
    try {
      const [brokerResult, accountResult, strategyResult, dateResult, positionResult, logResult, watcherRunResult, dashboardResult] = await Promise.all([
        api.getBrokerStatus(session),
        api.getBrokerAccounts(session),
        api.getStrategy(session),
        api.signalDates(session),
        api.positions(session),
        api.tradeLogs(session),
        api.watcherRuns(session).catch(() => []),
        api.dailyDashboard(session).catch(() => null),
      ]);
      const nextSignalDate = selectedSignalDate || dateResult[0] || "";
      const [signalResult, decisionResult, reportResult] = nextSignalDate
        ? await Promise.all([
            api.signalsByDate(session, nextSignalDate),
            api.tradeDecisions(session, nextSignalDate).catch(() => []),
            isScanAdmin ? api.getAiReportStatuses(session, nextSignalDate).catch(() => []) : Promise.resolve([]),
          ])
        : [[], [], []];
      setBrokerStatus(brokerResult);
      setBrokerAccounts(accountResult);
      setStrategy(strategyResult);
      setSignalDates(dateResult);
      setSelectedSignalDate(nextSignalDate);
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
      setPositions(positionResult);
      setLogs(logResult);
      setWatcherRuns(watcherRunResult);
      setDecisions(decisionResult);
    } catch {
      // First-time users may not have credentials yet. Keep the form usable.
    }
  }

  async function saveBroker(event: React.FormEvent) {
    event.preventDefault();
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
      const reportResult = isScanAdmin ? await api.getAiReportStatuses(session, tradeDate).catch(() => []) : [];
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
        </div>
        <button className="ghost" onClick={() => supabase.auth.signOut()}>로그아웃</button>
      </div>

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
                  disabled={pending !== null || account.is_active}
                  onClick={() => activateBrokerAccount(account.id)}
                >
                  <strong>{account.mode === "live" ? "실전투자" : "모의투자"}</strong>
                  <span>{account.kis_account_no}-{account.kis_account_product_code}</span>
                  <small>{account.is_active ? `현재 사용 중 · 자동매매 ${account.enabled ? "ON" : "OFF"} · 매매알림 ${account.telegram_configured ? "ON" : "OFF"}` : "교체하기"}</small>
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
                  <option value="live">실전투자</option>
                </select>
              </label>
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

        <div className="panel command">
          <h2>자동매매</h2>
          <p className="command-copy">현재 활성 계정 기준으로 주문 감시를 켜거나 끕니다. 오늘 시그널은 관리자가 생성한 공용 스캔 데이터를 표시합니다.</p>
          <button disabled={pending !== null || !brokerStatus?.configured || brokerStatus?.enabled} onClick={() => run("enable", () => api.setAutoTradingEnabled(session, true), "자동매매 ON 완료:")}>
            {pending === "enable" ? "자동매매 켜는 중..." : "자동매매 ON"}
          </button>
          <button disabled={pending !== null || !brokerStatus?.configured || !brokerStatus?.enabled} onClick={() => run("disable", () => api.setAutoTradingEnabled(session, false), "자동매매 OFF 완료:")}>
            {pending === "disable" ? "자동매매 끄는 중..." : "자동매매 OFF"}
          </button>
          <button disabled={pending !== null || !brokerStatus?.configured} onClick={loadKisAccount}>
            {pending === "account" ? "계좌 조회 중..." : "KIS 계좌 조회"}
          </button>
          {isScanAdmin ? (
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
              <button disabled={pending !== null || !selectedSignalDate || signals.length === 0} onClick={sendReport}>
                {pending === "report" ? "리포트 생성 요청 중..." : "AI 리포트 생성 요청"}
              </button>
              <button disabled={pending !== null || !selectedSignalDate || signals.length === 0} onClick={sendBlogReport}>
                {pending === "report" ? "블로그 글 생성 요청 중..." : "블로그 글 생성 요청"}
              </button>
              {dailyReportCompleted && (
                <button disabled={pending !== null || !selectedSignalDate} onClick={downloadDailyReport}>
                  {pending === "reportDownload" ? "종합 리포트 확인 중..." : "종합 리포트 다운로드"}
                </button>
              )}
              {hasCompletedReport(aiReports, "daily_blog") && (
                <button disabled={pending !== null || !selectedSignalDate} onClick={downloadDailyBlogReport}>
                  {pending === "reportDownload" ? "블로그 글 확인 중..." : "종합 블로그 글 다운로드"}
                </button>
              )}
            </>
          ) : (
            <p className="command-copy">스캔 실행은 관리자만 가능하고, 사용자는 생성된 오늘 시그널만 조회합니다.</p>
          )}
          <a className="telegram-link" href="https://t.me/sc_swingbot" target="_blank" rel="noreferrer">
            텔레그램 봇 추가하기
          </a>
          <StatusLine status={status} />
        </div>
        <DailyDashboardPanel dashboard={dailyDashboard} onRefresh={refreshDashboardOnly} refreshing={pending === "dashboardRefresh"} />
      </div>

      <StrategyPanel
        strategy={strategy}
        editing={editingStrategy}
        pending={pending === "strategy"}
        onToggleEdit={() => setEditingStrategy((value) => !value)}
        onPresetChange={applyStrategyPreset}
        onChange={setStrategy}
        onSave={saveStrategy}
      />

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

      <div className="grid three">
        <AccountPanel account={kisAccount} onRefresh={loadKisAccount} refreshing={pending === "account"} />
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
        <DataPanel
          title="와쳐 실행 로그"
          rows={watcherRuns.map(normalizeWatcherRunRow)}
          columns={["created_at", "mode", "orders_allowed_ko", "cash", "remaining_daily_slots", "daily_slots", "action_count", "skip_reason_ko"]}
          maxRows={30}
          headerAction={(
            <button className="ghost small" type="button" disabled={pending === "watcherRunsRefresh"} onClick={refreshWatcherRunsOnly}>
              {pending === "watcherRunsRefresh" ? "갱신 중" : "새로고침"}
            </button>
          )}
          onRowClick={(row) => setDetail({
            title: `${formatCell(row.created_at)} 와쳐 실행`,
            kind: "watcher",
            row,
          })}
        />
        {isScanAdmin && (
          <BacktestPanel
            result={backtest}
            days={backtestDays}
            pending={pending === "backtest"}
            onDaysChange={setBacktestDays}
            onRun={runBacktest}
          />
        )}
      </div>
      <AutoTradingRules strategy={strategy} mode={brokerStatus?.mode} liveOrderEnabled={brokerStatus?.live_order_enabled || false} serverLiveTradingAllowed={brokerStatus?.server_live_trading_allowed || false} />
      {detail && (
        <DetailOverlay
          detail={detail}
          isScanAdmin={isScanAdmin}
          pending={pending}
          onSendSignalReport={sendSingleSignalReport}
          onSendSignalBlogReport={sendSingleSignalBlogReport}
          onDownloadSignalReport={downloadSingleSignalReport}
          onDownloadSignalBlogReport={downloadSingleSignalBlogReport}
          aiReports={aiReports}
          onClose={() => setDetail(null)}
        />
      )}
    </section>
  );
}

function DailyDashboardPanel({ dashboard, onRefresh, refreshing }: { dashboard: DailyDashboard | null; onRefresh: () => void; refreshing: boolean }) {
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

function StrategyPanel({
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

function BacktestPanel({
  result,
  days,
  pending,
  onDaysChange,
  onRun,
}: {
  result: BacktestResult | null;
  days: number;
  pending: boolean;
  onDaysChange: (days: number) => void;
  onRun: () => void;
}) {
  const summary = result
    ? [
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
        </div>
      </div>
      {!result ? (
        <p className="empty">공용 시그널 기준으로 진입가, 손절가, 익절가, 최대 보유일을 단순 검증합니다.</p>
      ) : (
        <>
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
    </section>
  );
}

function presetLabel(preset: StrategyPreset) {
  if (preset === "conservative") return "보수적";
  if (preset === "aggressive") return "공격적";
  return "기본";
}

function formatPct(value: number) {
  const rounded = (value * 100).toFixed(1).replace(/\.0$/, "");
  return `${rounded}%`;
}

function AutoTradingRules({
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

function labelForPending(key: string) {
  const labels: Record<string, string> = {
    broker: "KIS 정보 저장",
    enable: "자동매매 ON",
    disable: "자동매매 OFF",
    account: "KIS 계좌 조회",
    accountSwitch: "활성 계좌 변경",
    strategy: "전략 설정 저장",
    scan: "오늘 시그널 스캔",
    signals: "시그널 조회",
    backtest: "백테스트",
    report: "AI 리포트 생성 큐 등록",
    signalReport: "개별 기업 AI 리포트 생성 큐 등록",
    reportDownload: "종합 리포트 다운로드",
    signalReportDownload: "개별 리포트 다운로드",
    watcherRunsRefresh: "와쳐 실행 로그 새로고침",
  };
  return labels[key] || "요청";
}

function AccountPanel({ account, onRefresh, refreshing }: { account: KisAccount | null; onRefresh: () => void; refreshing: boolean }) {
  const rows = account?.holdings.map((holding) => ({
    code: holding.code,
    name: holding.name,
    qty: holding.qty,
    avg_price: holding.avg_price,
    current_price: holding.current_price,
    profit_loss: holding.profit_loss,
    profit_loss_rate: holding.profit_loss_rate,
  })) || [];

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
          <div className="account-summary">
            <span>계좌 {account.account}</span>
            <strong>예수금 {formatCell(account.cash)}원</strong>
            <strong>총평가 {formatCell(account.total_equity)}원</strong>
            <span>보유 {account.holdings_count}종목</span>
          </div>
          <MiniTable rows={rows} columns={["code", "name", "qty", "avg_price", "current_price", "profit_loss", "profit_loss_rate"]} />
        </>
      )}
    </section>
  );
}

function MiniTable({ rows, columns }: { rows: Array<Record<string, unknown>>; columns: string[] }) {
  if (rows.length === 0) {
    return <p className="empty">보유 종목 없음</p>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={String(row.code || index)}>
              {columns.map((column) => <td key={column}>{formatCell(row[column])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StatusLine({ status }: { status: Status }) {
  if (!status.message) return null;
  return <p className={`status ${status.type}`}>{status.message}</p>;
}

function cleanErrorMessage(message: string) {
  try {
    const parsed = JSON.parse(message);
    return parsed.detail || parsed.message || message;
  } catch {
    return message;
  }
}

function downloadHtmlReport(report: AiReport) {
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

function sanitizeFilename(value: string) {
  return value.replace(/[\\/:*?"<>|]+/g, "_").replace(/\s+/g, "_");
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function hasCompletedReport(reports: AiReportStatus[], reportType: AiReportType, code?: string) {
  return reports.some((report) => {
    if (report.report_type !== reportType || report.status !== "completed") return false;
    if (reportType === "daily" || reportType === "daily_blog") return report.code === "ALL";
    return report.code === code;
  });
}

function DataPanel({
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

function DetailOverlay({
  detail,
  isScanAdmin,
  pending,
  onSendSignalReport,
  onSendSignalBlogReport,
  onDownloadSignalReport,
  onDownloadSignalBlogReport,
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
  aiReports: AiReportStatus[];
  onClose: () => void;
}) {
  const detailLabel =
    detail.kind === "signal" ? "시그널 상세"
      : detail.kind === "log" ? "매매 로그 상세"
        : detail.kind === "decision" ? "매수 제외 상세"
          : detail.kind === "watcher" ? "와쳐 실행 상세"
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
        {detail.kind === "position" && <PositionDetail row={detail.row} />}
        {detail.kind === "decision" && <DecisionDetail row={detail.row} />}
        {detail.kind === "watcher" && <WatcherRunDetail row={detail.row} />}
      </aside>
    </div>
  );
}

function SignalDetail({
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

function TradeLogDetail({ row }: { row: Record<string, unknown> }) {
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

function PositionDetail({ row }: { row: Record<string, unknown> }) {
  const raw = asRecord(row.raw);
  return (
    <div className="detail-grid">
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

function DecisionDetail({ row }: { row: Record<string, unknown> }) {
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

function WatcherRunDetail({ row }: { row: Record<string, unknown> }) {
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

function DetailSection({ title, items }: { title: string; items: Array<[string, unknown]> }) {
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

function formatCell(value: unknown) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") return value.toLocaleString("ko-KR");
  return String(value);
}

function formatMarketCap(value: unknown) {
  const numeric = numericValue(value);
  if (numeric === null || numeric <= 0) return formatCell(value);
  const trillion = Math.floor(numeric / 1_000_000_000_000);
  const hundredMillion = Math.round((numeric % 1_000_000_000_000) / 100_000_000);
  if (trillion > 0 && hundredMillion > 0) return `${trillion}조 ${hundredMillion.toLocaleString("ko-KR")}억 원`;
  if (trillion > 0) return `${trillion}조 원`;
  return `${Math.round(numeric / 100_000_000).toLocaleString("ko-KR")}억 원`;
}

function numericValue(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(String(value).replace(/,/g, ""));
  return Number.isFinite(parsed) ? parsed : null;
}

function percentFromEntry(target: unknown, entry: unknown): number | null {
  const targetValue = numericValue(target);
  const entryValue = numericValue(entry);
  if (targetValue === null || entryValue === null || entryValue <= 0) return null;
  return (targetValue / entryValue - 1) * 100;
}

function formatPlanPct(value: unknown): string {
  const numeric = numericValue(value);
  if (numeric === null) return "";
  const sign = numeric > 0 ? "+" : "";
  return `${sign}${numeric.toFixed(2)}%`;
}

function formatPercentFromEntry(target: unknown, entry: unknown): string {
  const percent = percentFromEntry(target, entry);
  return percent === null ? "-" : formatPlanPct(percent);
}

function buildStopLossExplanation(row: Record<string, unknown>, raw: Record<string, unknown>) {
  const stopPct = formatPercentFromEntry(row.stop_loss, row.entry);
  const atrPct = raw["ATR(%)"] === undefined ? "-" : `${formatCell(raw["ATR(%)"])}%`;
  return `최근 10거래일 저점과 60일선 중 더 낮은 지지선에서 1% 아래로 설정. 현재 손절폭 ${stopPct}, ATR 변동성 ${atrPct}.`;
}

function buildTakeProfitExplanation(row: Record<string, unknown>) {
  const riskPct = formatRiskPct(row.entry, row.stop_loss);
  const tp1Pct = formatPercentFromEntry(row.take_profit_1, row.entry);
  const tp2Pct = formatPercentFromEntry(row.take_profit_2, row.entry);
  return `진입가와 손절가 사이의 리스크를 1R로 보고, 1차 익절은 +1R(${tp1Pct}), 2차 익절은 +2R(${tp2Pct})로 설정. 기준 리스크는 ${riskPct}.`;
}

function formatRiskPct(entry: unknown, stopLoss: unknown) {
  const entryValue = numericValue(entry);
  const stopValue = numericValue(stopLoss);
  if (entryValue === null || stopValue === null || entryValue <= 0) return "-";
  return `${Math.max(0, (entryValue - stopValue) / entryValue * 100).toFixed(2)}%`;
}

function formatOrderPolicy(value: unknown): string {
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

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function normalizeTradeLogRow(row: Record<string, unknown>) {
  return {
    ...row,
    action_ko: row.action === "BUY" ? "매수" : row.action === "SELL" ? "매도" : row.action,
    reason_ko: translateReason(row.reason),
    created_at: formatDateTime(row.created_at),
  };
}

function enrichPlanPercentRow(row: Record<string, unknown>) {
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

function normalizeDecisionRow(row: TradeDecisionLog): Record<string, unknown> {
  return {
    ...row,
    reason: row.reason || translateReason(row.reason_code),
    created_at: formatDateTime(row.created_at),
  };
}

function normalizeWatcherRunRow(row: WatcherRun): Record<string, unknown> {
  return {
    ...row,
    orders_allowed_ko: row.orders_allowed ? "허용" : "차단",
    skip_reason_ko: translateWatcherSkipReason(row.skip_reason),
    created_at: formatDateTime(row.created_at),
  };
}

function enrichTradeLogRow(
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

function exitPlanFromSource(source?: Record<string, unknown>) {
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

function translateReason(reason: unknown) {
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
    StrategySellCooldown: "매수 직후 전략 매도 쿨다운",
    UnrealizedLossLimit: "미실현손실 한도 도달",
  };
  return map[value] || value || "-";
}

function translateWatcherSkipReason(reason: unknown) {
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

function translateReasons(reasons: unknown) {
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

function isCoreUniverseSignal(raw: Record<string, unknown>) {
  return raw.CoreUniverse === true || raw.CoreUniverse === "true" || raw.CoreUniverse === 1;
}

function isPassed(value: unknown) {
  return value === true || value === "true" || value === 1;
}

function translateCoreUniverse(value: unknown) {
  const type = String(value || "");
  const map: Record<string, string> = {
    KOSPI_TOP1000: "KOSPI1000",
    KOSPI_TOP500: "KOSPI1000",
    KOSDAQ150: "KOSDAQ150",
  };
  return map[type] || type || "해당 없음";
}

function translateCloudType(value: unknown) {
  const type = String(value || "");
  if (type === "bullish") return "양운";
  if (type === "bearish") return "음운";
  if (type === "neutral") return "중립";
  return type || "-";
}

function formatDateTime(value: unknown) {
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
