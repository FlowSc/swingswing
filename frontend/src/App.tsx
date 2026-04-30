import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import {
  api,
  type AiReport,
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
} from "./api";
import { supabase } from "./supabase";

type AuthMode = "login" | "signup";
type Status = { type: "idle" | "info" | "error"; message: string };
type DetailKind = "signal" | "log" | "position" | "account" | "decision";
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
  const [status, setStatus] = useState<Status>({ type: "idle", message: "" });
  const [brokerStatus, setBrokerStatus] = useState<BrokerStatus | null>(null);
  const [brokerAccounts, setBrokerAccounts] = useState<BrokerAccount[]>([]);
  const [signals, setSignals] = useState<Array<Record<string, unknown>>>([]);
  const [signalDates, setSignalDates] = useState<string[]>([]);
  const [selectedSignalDate, setSelectedSignalDate] = useState("");
  const [positions, setPositions] = useState<Array<Record<string, unknown>>>([]);
  const [logs, setLogs] = useState<Array<Record<string, unknown>>>([]);
  const [decisions, setDecisions] = useState<TradeDecisionLog[]>([]);
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

  async function startScan() {
    setPending("scan");
    setStatus({ type: "info", message: "스캔 요청 중..." });
    try {
      const started = await api.scan(session);
      setStatus({ type: "info", message: `스캔 시작: 0/${started.total}개 처리` });
      await runScanSteps(started.scan_run_id);
    } catch (error) {
      setStatus({ type: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setPending(null);
    }
  }

  async function runScanSteps(scanRunId: number) {
    for (let index = 0; index < 20; index += 1) {
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
    setStatus({ type: "info", message: "스캔 step 제한에 도달했습니다. 다시 버튼을 누르면 이어서 처리하지 않고 새 스캔이 시작됩니다." });
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
      () => api.sendDailyReport(session, selectedSignalDate || undefined),
      "AI 리포트 생성 큐 등록 완료:",
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
      () => api.sendSignalReport(session, { trade_date: selectedSignalDate, code }),
      "개별 기업 AI 리포트 생성 큐 등록 완료:",
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

  async function downloadReport({
    key,
    payload,
  }: {
    key: string;
    payload: { trade_date: string; report_type: "daily" | "signal"; code?: string };
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
      const [brokerResult, accountResult, strategyResult, dateResult, positionResult, logResult, dashboardResult] = await Promise.all([
        api.getBrokerStatus(session),
        api.getBrokerAccounts(session),
        api.getStrategy(session),
        api.signalDates(session),
        api.positions(session),
        api.tradeLogs(session),
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
      }
      setSignals(signalResult);
      setAiReports(reportResult);
      setPositions(positionResult);
      setLogs(logResult);
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

      <DailyDashboardPanel dashboard={dailyDashboard} />

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
          </div>
          <p className="command-copy">KIS 키와 별도로 저장합니다. 매수/매도 알림과 shared signal 알림을 받을 개인 텔레그램 봇 설정입니다.</p>
          <label>
            Telegram Bot Token
            <input
              value={telegramSettings.telegram_bot_token || ""}
              onChange={(event) => setTelegramSettings({ ...telegramSettings, telegram_bot_token: event.target.value })}
              placeholder="개인 봇 토큰"
              disabled={!brokerStatus?.configured}
            />
            <small>이미 저장된 토큰은 다시 표시하지 않습니다. 비워두면 기존 토큰을 유지합니다.</small>
          </label>
          <label>
            Telegram Chat ID
            <input
              value={telegramSettings.telegram_chat_id || ""}
              onChange={(event) => setTelegramSettings({ ...telegramSettings, telegram_chat_id: event.target.value })}
              placeholder="예: 6583699681"
              disabled={!brokerStatus?.configured}
            />
          </label>
          <button className="primary" disabled={pending === "telegram" || !brokerStatus?.configured}>
            {pending === "telegram" ? "저장 중..." : "매매 알림 저장"}
          </button>
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
              <button disabled={pending !== null} onClick={startScan}>
                {pending === "scan" ? "스캔 중... 100개씩 처리" : "오늘 시그널 스캔"}
              </button>
              <button disabled={pending !== null || !selectedSignalDate || signals.length === 0} onClick={sendReport}>
                {pending === "report" ? "리포트 생성 요청 중..." : "AI 리포트 생성 요청"}
              </button>
              {dailyReportCompleted && (
                <button disabled={pending !== null || !selectedSignalDate} onClick={downloadDailyReport}>
                  {pending === "reportDownload" ? "종합 리포트 확인 중..." : "종합 리포트 다운로드"}
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
          rows={signals}
          columns={["score", "name", "entry", "stop_loss", "take_profit_2", "code"]}
          maxRows={30}
          headerAction={signalDates.length > 0 ? (
            <select className="compact-select" value={selectedSignalDate} onChange={(event) => changeSignalDate(event.target.value)}>
              {signalDates.map((tradeDate) => <option key={tradeDate} value={tradeDate}>{tradeDate}</option>)}
            </select>
          ) : undefined}
          onRowClick={(row) => setDetail({ title: `${formatCell(row.name)} (${formatCell(row.code)})`, kind: "signal", row })}
        />
      </div>

      <div className="grid three">
        <AccountPanel account={kisAccount} />
        <DataPanel
          title="포지션"
          rows={positions}
          columns={["code", "name", "entry_price", "qty", "remaining_qty", "status"]}
          onRowClick={(row) => setDetail({ title: `${formatCell(row.name)} 포지션`, kind: "position", row })}
        />
        <DataPanel
          title="매매 로그"
          rows={logs.map(normalizeTradeLogRow)}
          columns={["action_ko", "code", "price", "qty", "reason_ko", "created_at"]}
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
          onRowClick={(row) => setDetail({
            title: `${formatCell(row.name)} 제외 사유`,
            kind: "decision",
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
          onDownloadSignalReport={downloadSingleSignalReport}
          aiReports={aiReports}
          onClose={() => setDetail(null)}
        />
      )}
    </section>
  );
}

function DailyDashboardPanel({ dashboard }: { dashboard: DailyDashboard | null }) {
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
        <span className={`scan-badge ${scan?.status || "idle"}`}>
          스캔 {scan?.status || "대기"}
        </span>
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
          <span>추가 필터: 당일 캔들 {strategy.use_day_candle_filter ? "ON" : "OFF"} · 본전 손절 {strategy.use_breakeven_after_tp1 ? "ON" : "OFF"} · 기준선 이탈 매도 {strategy.use_kijun_exit ? "ON" : "OFF"}</span>
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
          <li>점수 높은 순서로 확인하되 장중 가격 필터 통과 필요</li>
          <li>현재가가 진입가 {formatPct(strategy.min_entry_discount - 1)}~+{formatPct(strategy.max_entry_premium - 1)} 범위 안</li>
          <li>일목 기준선 필터 {strategy.use_kijun_filter ? "사용" : "미사용"}, 볼린저 상단 필터 {strategy.use_bb_upper_filter ? "사용" : "미사용"}</li>
          <li>당일 캔들 위치 필터 {strategy.use_day_candle_filter ? `사용: 고점 대비 ${formatPct(strategy.max_pullback_from_day_high)} 이상 밀리면 제외` : "미사용"}</li>
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
        </ul>
      </div>
      <div>
        <strong>매도 조건</strong>
        <ul>
          <li>09:20~15:20 동안 5분 단위 감시</li>
          <li>손절가 도달 시 전량 매도</li>
          <li>1차/2차 익절가 도달 시 일부 매도</li>
          <li>익절 후 추적 손절 도달 시 잔량 매도</li>
          <li>1차 익절 후 본전 손절 {strategy.use_breakeven_after_tp1 ? "사용" : "미사용"}</li>
          <li>일목 기준선 이탈 매도 {strategy.use_kijun_exit ? "사용" : "미사용"}</li>
          <li>최대 보유일 도달 시 전량 매도</li>
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
  };
  return labels[key] || "요청";
}

function AccountPanel({ account }: { account: KisAccount | null }) {
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
      <h2>KIS 계좌</h2>
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

function hasCompletedReport(reports: AiReportStatus[], reportType: "daily" | "signal", code?: string) {
  return reports.some((report) => {
    if (report.report_type !== reportType || report.status !== "completed") return false;
    if (reportType === "daily") return report.code === "ALL";
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
}: {
  title: string;
  rows: Array<Record<string, unknown>>;
  columns: string[];
  onRowClick?: (row: Record<string, unknown>) => void;
  headerAction?: React.ReactNode;
  initialRows?: number;
  maxRows?: number;
}) {
  const [visibleRows, setVisibleRows] = useState(initialRows);
  const cappedMaxRows = Math.min(maxRows, rows.length);
  const displayRows = rows.slice(0, Math.min(visibleRows, cappedMaxRows));

  useEffect(() => {
    setVisibleRows(initialRows);
  }, [initialRows, rows.length, title]);

  return (
    <section className="panel data-panel">
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
          {visibleRows < cappedMaxRows && (
            <button className="ghost table-more" type="button" onClick={() => setVisibleRows(cappedMaxRows)}>
              더보기 {cappedMaxRows - visibleRows}개
            </button>
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
  onDownloadSignalReport,
  aiReports,
  onClose,
}: {
  detail: DetailSelection;
  isScanAdmin: boolean;
  pending: string | null;
  onSendSignalReport: (row: Record<string, unknown>) => void;
  onDownloadSignalReport: (row: Record<string, unknown>) => void;
  aiReports: AiReportStatus[];
  onClose: () => void;
}) {
  const detailLabel =
    detail.kind === "signal" ? "시그널 상세"
      : detail.kind === "log" ? "매매 로그 상세"
        : detail.kind === "decision" ? "매수 제외 상세"
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
            onSendReport={() => onSendSignalReport(detail.row)}
            onDownloadReport={() => onDownloadSignalReport(detail.row)}
          />
        )}
        {detail.kind === "log" && <TradeLogDetail row={detail.row} />}
        {detail.kind === "position" && <PositionDetail row={detail.row} />}
        {detail.kind === "decision" && <DecisionDetail row={detail.row} />}
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
  onSendReport,
  onDownloadReport,
}: {
  row: Record<string, unknown>;
  isScanAdmin: boolean;
  pending: boolean;
  downloadPending: boolean;
  reportCompleted: boolean;
  onSendReport: () => void;
  onDownloadReport: () => void;
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
          {reportCompleted && (
            <button className="detail-action" type="button" disabled={downloadPending} onClick={onDownloadReport}>
              {downloadPending ? "리포트 확인 중..." : "개별 리포트 다운로드"}
            </button>
          )}
        </>
      )}
      <DetailSection title="기업 개요" items={[
        ["시장", companyProfile.market || raw.Universe],
        ["섹터", companyProfile.sector],
        ["업종", companyProfile.industry],
        ["사업 요약", companyProfile.business_summary],
        ["시가총액", companyProfile.market_cap],
      ]} />
      <DetailSection title="매매 계획" items={[
        ["매수가", row.entry],
        ["손절가", row.stop_loss],
        ["1차 익절가", row.take_profit_1],
        ["2차 익절가", row.take_profit_2],
        ["추적 손절가", row.trailing_stop],
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
        ["시장 필터", raw.MarketFilter],
        ["유니버스", raw.Universe],
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
        ["1차 익절", exitPlan.take_profit_1],
        ["2차 익절", exitPlan.take_profit_2],
        ["추적 손절", exitPlan.trailing_stop],
        ["권장 보유", `${formatCell(exitPlan.hold_min_days)}-${formatCell(exitPlan.hold_preferred_days)}일`],
        ["최대 보유", `${formatCell(exitPlan.hold_max_days)}일`],
        ["매입 시간", exitPlan.planned_entry_window || "14:30-15:20"],
        ["관리 시간", exitPlan.planned_manage_window || "09:20-15:20"],
      ]} />
      <DetailSection title="장중 확인값" items={[
        ["현재가", quote.current_price],
        ["당일 고가", quote.day_high],
        ["당일 저가", quote.day_low],
        ["누적 거래량", quote.accumulated_volume],
        ["주문 응답", raw.order ? "저장됨" : "-"],
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
        ["1차 익절", row.take_profit_1],
        ["2차 익절", row.take_profit_2],
        ["추적 손절", row.trailing_stop],
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
        ["호가 기준", quote.price_source],
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

function normalizeDecisionRow(row: TradeDecisionLog): Record<string, unknown> {
  return {
    ...row,
    reason: row.reason || translateReason(row.reason_code),
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
    take_profit_1: row.take_profit_1 ?? raw.TakeProfit1,
    take_profit_2: row.take_profit_2 ?? raw.TakeProfit2,
    trailing_stop: row.trailing_stop ?? raw.TrailingStop,
    hold_min_days: raw.HoldMinDays,
    hold_preferred_days: raw.HoldPreferredDays,
    hold_max_days: raw.HoldMaxDays || 15,
    planned_entry_window: "14:30-15:20",
    planned_manage_window: "09:20-15:20",
  };
}

function translateReason(reason: unknown) {
  const value = String(reason || "");
  const map: Record<string, string> = {
    IntradayEntry: "장중 진입 조건 충족",
    StopLoss: "손절가 도달",
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
    AboveBBUpper: "현재가가 볼린저 상단 위",
    PulledBackFromDayHigh: "당일 고점 대비 과도하게 밀림",
    QuoteFailed: "현재가 조회 실패",
    InvalidQuote: "현재가 값 비정상",
    SizingRejected: "수량/리스크/최소주문금액 조건 미충족",
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
    "KOSPI above MA5": "코스피 5일선 위",
    KOSPI_TOP500: "코스피 시총 상위권",
    KOSDAQ150: "코스닥150 구성",
  };
  return value.split(",").map((item) => map[item.trim()] || item.trim()).filter(Boolean).join(", ");
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
