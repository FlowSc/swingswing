# KOSPI Swing Bot Backend

FastAPI backend for the Railway + Supabase version.

## Local Run

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

## Required Environment

```text
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY
BROKER_ENCRYPTION_KEY
TELEGRAM_BOT_TOKEN
SCHEDULER_ENABLED
TZ
TIMEZONE
```

Generate `BROKER_ENCRYPTION_KEY`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## API

- `GET /health`
- `GET /broker/kis/status`
- `POST /broker/kis`
- `POST /bot/control`
- `POST /bot/scan`
- `POST /bot/watch-tick`
- `GET /signals/today`
- `GET /positions`
- `GET /trade-logs`

Authenticated endpoints require a Supabase Auth bearer token from the React app.

## Supabase Setup

Run `supabase/schema.sql` in the Supabase SQL editor first.

Required Supabase values for Railway:

```text
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...
BROKER_ENCRYPTION_KEY=...
TELEGRAM_BOT_TOKEN=...
SCHEDULER_ENABLED=true
TZ=Asia/Seoul
TIMEZONE=Asia/Seoul
```

The backend uses the service role key for encrypted credential storage and bot jobs. Do not expose `SUPABASE_SERVICE_ROLE_KEY` to React.

## Bot Flow

1. React signs the user in with Supabase Auth.
2. React sends the Supabase access token as `Authorization: Bearer <token>`.
3. User saves KIS credentials through `POST /broker/kis`.
4. `POST /bot/scan` creates today's signals and stores them in Supabase.
5. `POST /bot/watch-tick` runs one entry/exit cycle for testing.
6. With `SCHEDULER_ENABLED=true`, Railway runs scan at 13:00 and watcher every 5 minutes during market hours. New entries are only allowed from 14:30 to 15:20.

`/bot/watch-tick` body:

```json
{
  "test_mode": false,
  "dry_run": false
}
```

`dry_run=true` does not place KIS orders. `dry_run=false` places paper-trading orders only; live trading is blocked in this backend version.
