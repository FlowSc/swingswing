# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in values before running
uvicorn app.main:app --reload
```

Generate `BROKER_ENCRYPTION_KEY`:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env      # fill in VITE_* values
npm run dev               # dev server
npm run build             # tsc --noEmit then vite build
```

## Architecture

### Backend (`backend/app/`)

- **`core/config.py`** — Pydantic `Settings` loaded from `.env`. `get_settings()` is `@lru_cache`d. Key flags: `scheduler_enabled` (false locally, true on Railway), `allow_live_trading` (false by default — live orders are blocked at the code level).
- **`core/auth.py`** — `get_current_user` dependency validates the Supabase JWT by calling `/auth/v1/user` and returns a `CurrentUser(id, email, access_token)` dataclass.
- **`routers/`** — Four routers: `broker` (KIS credentials, account queries), `bot` (scan, watch-tick, strategy settings, AI reports), `trading` (signals, positions, trade logs, watcher runs, dashboard, backtest), `auth` (signup).
- **`services/supabase_rest.py`** — Thin async `httpx` wrapper around Supabase REST and Auth Admin APIs. Uses `service_role_key` for all server-side DB ops; only uses the user token for token validation.
- **`services/kis.py`** — KIS Open API HTTP client. Separates paper (`openapivts…:29443`) and live (`openapi…:9443`) base URLs and TR IDs. Handles OAuth token issuance and refresh.
- **`services/scanner.py`** — Daily KOSPI swing candidate scan. Chunked execution: `prepare_chunked_scan_state` → repeated `process_scan_chunk` calls → `finalize_chunked_scan`. Results written to `shared_signals` table.
- **`services/watcher.py`** — Intraday position manager. Entry window 14:30–15:20 KST, manage window 09:20–15:20 KST. Ticks every 5 minutes via scheduler. Handles buy orders, stop-loss, trailing stop, take-profit, and breakeven logic.
- **`services/scheduler.py`** — APScheduler `AsyncIOScheduler`. Jobs: daily scan at 13:30 KST Mon–Fri; intraday watcher every 5 min 09:00–15:00 KST Mon–Fri; optional AI report worker on an interval.
- **`services/broker_credentials.py`** — Encrypts/decrypts KIS app_key and app_secret with `BROKER_ENCRYPTION_KEY` (Fernet) before storing in Supabase.
- **`services/realtime_risk.py`** — Real-time entry safeguards (liquidity filter, bid/ask ratio, spread) fetched via KIS websocket at entry time.
- **`services/sizing.py`** — Position size calculation based on `DEFAULT_CAPITAL`, `risk_per_trade_pct`, and stop-loss distance.

### Frontend (`frontend/src/`)

- **`supabase.ts`** — Creates the Supabase client with `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`.
- **`api.ts`** — All backend calls. Two helpers: `request()` (authenticated, auto-refreshes Supabase token on 401) and `publicRequest()` (unauthenticated, used only for signup). Exports a single `api` object with typed methods.
- **`App.tsx`** — Single-page React app; all screens rendered here.

### Database (Supabase)

Schema is in `supabase/schema.sql`. Key tables: `broker_credentials`, `shared_signals`, `positions`, `trade_logs`, `trade_decision_logs`, `watcher_runs`, `scan_runs`, `strategy_settings`, `ai_reports`.

### Access control

- Scan admin actions (scan, AI reports) are restricted to the email in `scan_admin_email` setting (`zelatool@gmail.com` by default).
- Signup requires an `invite_code` when `signup_invite_code` is set in the environment.
- Live order execution requires both `allow_live_trading=true` (server env) and `live_order_enabled=true` on the broker credential row.
