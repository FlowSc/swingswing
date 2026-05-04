import { useState } from "react";
import type { FormEvent } from "react";

import { api } from "../api";
import { supabase } from "../supabase";

type AuthMode = "login" | "signup";
type Status = { type: "idle" | "info" | "error"; message: string };

export function AuthCard() {
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState<Status>({ type: "idle", message: "" });
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setStatus({ type: "idle", message: "" });

    try {
      if (mode === "signup") {
        await api.signup({ email, password });
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
