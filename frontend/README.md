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

## Vercel Deploy

Set the Vercel project root directory to `frontend`.

Build settings:

```text
Framework Preset: Vite
Install Command: npm install
Build Command: npm run build
Output Directory: dist
```

Vercel environment variables:

```text
VITE_SUPABASE_URL=https://xxxxx.supabase.co
VITE_SUPABASE_ANON_KEY=...
VITE_API_BASE_URL=https://your-railway-backend-domain
```

Use the Railway backend URL for `VITE_API_BASE_URL`. Do not use the old Railway frontend URL here.

## Flow

1. User signs up or logs in with Supabase Auth.
2. Frontend receives a Supabase session access token.
3. Frontend calls FastAPI with `Authorization: Bearer <access_token>`.
4. User saves KIS credentials.
5. User can run scan, test watch tick, or paper-order watch tick.
