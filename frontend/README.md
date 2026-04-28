# KOSPI Swing Bot Frontend

React frontend for Supabase Auth and the FastAPI bot backend.

## Local Run

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

## Required `.env`

```text
VITE_SUPABASE_URL=https://xxxxx.supabase.co
VITE_SUPABASE_ANON_KEY=...
VITE_API_BASE_URL=http://localhost:8000
```

Only use the Supabase anon key here. Never put `SUPABASE_SERVICE_ROLE_KEY` or `BROKER_ENCRYPTION_KEY` in the frontend.

## Flow

1. User signs up or logs in with Supabase Auth.
2. Frontend receives a Supabase session access token.
3. Frontend calls FastAPI with `Authorization: Bearer <access_token>`.
4. User saves KIS credentials.
5. User can run scan, test watch tick, or paper-order watch tick.
