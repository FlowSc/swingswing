import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { api, type BrokerPayload } from "./api";
import { supabase } from "./supabase";

type AuthMode = "login" | "signup";
type Status = { type: "idle" | "info" | "error"; message: string };

const emptyBroker: BrokerPayload = {
  kis_app_key: "",
  kis_app_secret: "",
  kis_account_no: "",
  kis_account_product_code: "01",
  mode: "paper",
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

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="page">
      <section className="hero">
        <div>
          <p className="eyebrow">KOSPI AUTOMATED SWING</p>
          <h1>장 시작 전 스캔하고, 장중에는 봇이 감시한다.</h1>
        </div>
        <div className="hero-card">
          <span>Paper only</span>
          <strong>KIS 모의투자 우선</strong>
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
  const [status, setStatus] = useState<Status>({ type: "idle", message: "" });
  const [brokerStatus, setBrokerStatus] = useState<Record<string, unknown> | null>(null);
  const [signals, setSignals] = useState<Array<Record<string, unknown>>>([]);
  const [positions, setPositions] = useState<Array<Record<string, unknown>>>([]);
  const [logs, setLogs] = useState<Array<Record<string, unknown>>>([]);
  const [pending, setPending] = useState<string | null>(null);

  useEffect(() => {
    refresh();
  }, []);

  async function run<T>(key: string, action: () => Promise<T>, doneMessage: string) {
    setPending(key);
    setStatus({ type: "idle", message: "" });
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

  async function refresh() {
    try {
      const [brokerResult, signalResult, positionResult, logResult] = await Promise.all([
        api.getBrokerStatus(session),
        api.todaySignals(session),
        api.positions(session),
        api.tradeLogs(session),
      ]);
      setBrokerStatus(brokerResult);
      setSignals(signalResult);
      setPositions(positionResult);
      setLogs(logResult);
    } catch {
      // First-time users may not have credentials yet. Keep the form usable.
    }
  }

  async function saveBroker(event: React.FormEvent) {
    event.preventDefault();
    await run("broker", () => api.saveBroker(session, broker), "KIS 정보 저장 완료:");
  }

  return (
    <section className="dashboard">
      <div className="topbar">
        <div>
          <strong>{session.user.email}</strong>
          <span>{brokerStatus?.configured ? "KIS 연결 정보 있음" : "KIS 연결 정보 필요"}</span>
        </div>
        <button className="ghost" onClick={() => supabase.auth.signOut()}>로그아웃</button>
      </div>

      <div className="grid two">
        <form className="panel" onSubmit={saveBroker}>
          <h2>KIS 연결</h2>
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
            텔레그램 Chat ID
            <input value={broker.telegram_chat_id} onChange={(event) => setBroker({ ...broker, telegram_chat_id: event.target.value })} placeholder="선택" />
          </label>
          <button className="primary" disabled={pending === "broker"}>{pending === "broker" ? "저장 중..." : "저장"}</button>
        </form>

        <div className="panel command">
          <h2>봇 제어</h2>
          <button onClick={() => run("enable", () => api.setBotEnabled(session, true), "봇 활성화 완료:")}>봇 켜기</button>
          <button onClick={() => run("disable", () => api.setBotEnabled(session, false), "봇 비활성화 완료:")}>봇 끄기</button>
          <button onClick={() => run("scan", () => api.scan(session), "스캔 완료:")}>오늘 시그널 스캔</button>
          <button onClick={() => run("dry", () => api.watchTick(session, { test_mode: true, dry_run: true }), "테스트 감시 완료:")}>테스트 감시 1회</button>
          <button className="danger" onClick={() => run("order", () => api.watchTick(session, { test_mode: false, dry_run: false }), "모의주문 감시 완료:")}>모의주문 감시 1회</button>
          <StatusLine status={status} />
        </div>
      </div>

      <div className="grid three">
        <DataPanel title="오늘 시그널" rows={signals} columns={["code", "name", "entry", "stop_loss", "take_profit_2", "score"]} />
        <DataPanel title="포지션" rows={positions} columns={["code", "name", "entry_price", "qty", "remaining_qty", "status"]} />
        <DataPanel title="매매 로그" rows={logs} columns={["action", "code", "price", "qty", "reason"]} />
      </div>
    </section>
  );
}

function StatusLine({ status }: { status: Status }) {
  if (!status.message) return null;
  return <p className={`status ${status.type}`}>{status.message}</p>;
}

function DataPanel({ title, rows, columns }: { title: string; rows: Array<Record<string, unknown>>; columns: string[] }) {
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
              {rows.slice(0, 10).map((row, index) => (
                <tr key={String(row.id || index)}>
                  {columns.map((column) => <td key={column}>{formatCell(row[column])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function formatCell(value: unknown) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") return value.toLocaleString("ko-KR");
  return String(value);
}
