import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { api, type BrokerAccount, type BrokerPayload, type BrokerStatus, type KisAccount } from "./api";
import { supabase } from "./supabase";

type AuthMode = "login" | "signup";
type Status = { type: "idle" | "info" | "error"; message: string };
type DetailKind = "signal" | "log" | "position" | "account";
type DetailSelection = { title: string; kind: DetailKind; row: Record<string, unknown> };

const emptyBroker: BrokerPayload = {
  kis_app_key: "",
  kis_app_secret: "",
  kis_account_no: "",
  kis_account_product_code: "01",
  mode: "paper",
  live_order_enabled: false,
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
  const [status, setStatus] = useState<Status>({ type: "idle", message: "" });
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setStatus({ type: "idle", message: "" });

    const result =
      mode === "signup"
        ? await supabase.auth.signUp({ email, password })
        : await supabase.auth.signInWithPassword({ email, password });

    setPending(false);
    if (result.error) {
      setStatus({ type: "error", message: result.error.message });
      return;
    }

    setStatus({
      type: "info",
      message: mode === "signup" ? "가입 요청 완료. Supabase 이메일 인증 설정에 따라 메일 확인이 필요할 수 있습니다." : "로그인 완료.",
    });
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
  const [editingBroker, setEditingBroker] = useState(false);
  const [status, setStatus] = useState<Status>({ type: "idle", message: "" });
  const [brokerStatus, setBrokerStatus] = useState<BrokerStatus | null>(null);
  const [brokerAccounts, setBrokerAccounts] = useState<BrokerAccount[]>([]);
  const [signals, setSignals] = useState<Array<Record<string, unknown>>>([]);
  const [positions, setPositions] = useState<Array<Record<string, unknown>>>([]);
  const [logs, setLogs] = useState<Array<Record<string, unknown>>>([]);
  const [kisAccount, setKisAccount] = useState<KisAccount | null>(null);
  const [autoLoadedAccountKey, setAutoLoadedAccountKey] = useState("");
  const [detail, setDetail] = useState<DetailSelection | null>(null);
  const [pending, setPending] = useState<string | null>(null);

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

  async function testBroker() {
    await run("test", async () => {
      const result = await api.testBroker(session);
      if (!result.ok) {
        throw new Error(result.error || "KIS 연결 테스트 실패");
      }
      return result;
    }, "KIS 연결 테스트 완료:");
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

  async function refresh() {
    try {
      const [brokerResult, accountResult, signalResult, positionResult, logResult] = await Promise.all([
        api.getBrokerStatus(session),
        api.getBrokerAccounts(session),
        api.todaySignals(session),
        api.positions(session),
        api.tradeLogs(session),
      ]);
      setBrokerStatus(brokerResult);
      setBrokerAccounts(accountResult);
      if (brokerResult.configured) {
        setBroker((current) => ({
          ...current,
          kis_account_no: brokerResult.account_no || "",
          kis_account_product_code: brokerResult.account_product_code || "01",
          mode: brokerResult.mode || "paper",
          live_order_enabled: brokerResult.live_order_enabled || false,
        }));
        setEditingBroker(false);
      }
      setSignals(signalResult);
      setPositions(positionResult);
      setLogs(logResult);
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

  async function activateBrokerAccount(accountId: string) {
    setKisAccount(null);
    setAutoLoadedAccountKey("");
    await run("accountSwitch", () => api.activateBrokerAccount(session, accountId), "활성 계좌 변경 완료:");
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
              {brokerStatus.mode === "live" && !brokerStatus.server_live_trading_allowed && (
                <span>서버 안전장치: 실전주문 차단 중</span>
              )}
              <span>텔레그램 {brokerStatus.telegram_configured ? "백엔드 고정 설정됨" : "미설정"}</span>
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
                  <small>{account.is_active ? `현재 사용 중 · 자동매매 ${account.enabled ? "ON" : "OFF"}` : "교체하기"}</small>
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

        <div className="panel command">
          <h2>자동매매</h2>
          <p className="command-copy">현재 활성 계정 기준으로 자동 스캔과 주문 감시를 켜거나 끕니다. 모의/실전 계정 모두 같은 방식으로 제어됩니다.</p>
          <button disabled={pending !== null || !brokerStatus?.configured || brokerStatus?.enabled} onClick={() => run("enable", () => api.setAutoTradingEnabled(session, true), "자동매매 ON 완료:")}>
            {pending === "enable" ? "자동매매 켜는 중..." : "자동매매 ON"}
          </button>
          <button disabled={pending !== null || !brokerStatus?.configured || !brokerStatus?.enabled} onClick={() => run("disable", () => api.setAutoTradingEnabled(session, false), "자동매매 OFF 완료:")}>
            {pending === "disable" ? "자동매매 끄는 중..." : "자동매매 OFF"}
          </button>
          <button disabled={pending !== null || !brokerStatus?.configured} onClick={testBroker}>
            {pending === "test" ? "KIS 테스트 중..." : "KIS 연결 테스트"}
          </button>
          <button disabled={pending !== null || !brokerStatus?.configured} onClick={loadKisAccount}>
            {pending === "account" ? "계좌 조회 중..." : "KIS 계좌 조회"}
          </button>
          <button disabled={pending !== null} onClick={() => run("scan", () => api.scan(session), "스캔 완료:")}>
            {pending === "scan" ? "스캔 중... 1분 정도 걸림" : "오늘 시그널 스캔"}
          </button>
          <StatusLine status={status} />
        </div>
      </div>

      <div className="grid three">
        <AccountPanel account={kisAccount} />
        <DataPanel
          title="오늘 시그널"
          rows={signals}
          columns={["code", "name", "entry", "stop_loss", "take_profit_2", "score"]}
          maxRows={30}
          onRowClick={(row) => setDetail({ title: `${formatCell(row.name)} (${formatCell(row.code)})`, kind: "signal", row })}
        />
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
      {detail && <DetailOverlay detail={detail} onClose={() => setDetail(null)} />}
    </section>
  );
}

function labelForPending(key: string) {
  const labels: Record<string, string> = {
    broker: "KIS 정보 저장",
    enable: "자동매매 ON",
    disable: "자동매매 OFF",
    test: "KIS 연결 테스트",
    account: "KIS 계좌 조회",
    accountSwitch: "활성 계좌 변경",
    scan: "오늘 시그널 스캔",
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

function DataPanel({
  title,
  rows,
  columns,
  onRowClick,
  initialRows = 10,
  maxRows = 10,
}: {
  title: string;
  rows: Array<Record<string, unknown>>;
  columns: string[];
  onRowClick?: (row: Record<string, unknown>) => void;
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
      <h2>{title}</h2>
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

function DetailOverlay({ detail, onClose }: { detail: DetailSelection; onClose: () => void }) {
  return (
    <div className="overlay-backdrop" onClick={onClose}>
      <aside className="detail-popover" onClick={(event) => event.stopPropagation()}>
        <div className="detail-head">
          <div>
            <span>{detail.kind === "signal" ? "시그널 상세" : detail.kind === "log" ? "매매 로그 상세" : "포지션 상세"}</span>
            <h2>{detail.title}</h2>
          </div>
          <button className="ghost small" onClick={onClose}>닫기</button>
        </div>
        {detail.kind === "signal" && <SignalDetail row={detail.row} />}
        {detail.kind === "log" && <TradeLogDetail row={detail.row} />}
        {detail.kind === "position" && <PositionDetail row={detail.row} />}
      </aside>
    </div>
  );
}

function SignalDetail({ row }: { row: Record<string, unknown> }) {
  const raw = asRecord(row.raw);
  return (
    <div className="detail-grid">
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
      ]} />
      <DetailSection title="리스크/시장" items={[
        ["손절폭", `${formatCell(raw["StopPct"] ?? raw.StopPct)}%`],
        ["리스크", `${formatCell(raw.RiskPct)}%`],
        ["20일 거래대금", raw.TradingValue20D],
        ["시장 필터", raw.MarketFilter],
        ["유니버스", raw.Universe],
        ["5일 수익률", `${formatCell(raw["Ret_5D(%)"])}%`],
        ["20일 수익률", `${formatCell(raw["Ret_20D(%)"])}%`],
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
    TakeProfit1: "1차 익절가 도달",
    TakeProfit2: "2차 익절가 도달",
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
