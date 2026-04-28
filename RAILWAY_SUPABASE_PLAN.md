# Railway + Supabase Plan

## Goal

Run the KOSPI swing bot for two users without keeping a local Mac online.

## Recommended Deployment

- Railway: one always-on worker
- Supabase: signals, positions, and trade logs
- Railway variables: KIS and Telegram credentials for each user
- Timezone: `Asia/Seoul`

## Railway Variables

```text
TZ=Asia/Seoul

USER1_KEY=izak
USER1_KIS_APP_KEY=
USER1_KIS_APP_SECRET=
USER1_KIS_ACCOUNT_NO=
USER1_KIS_ACCOUNT_PRODUCT_CODE=01
USER1_TELEGRAM_CHAT_ID=

USER2_KEY=friend
USER2_KIS_APP_KEY=
USER2_KIS_APP_SECRET=
USER2_KIS_ACCOUNT_NO=
USER2_KIS_ACCOUNT_PRODUCT_CODE=01
USER2_TELEGRAM_CHAT_ID=

TELEGRAM_BOT_TOKEN=
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
```

## Runtime Flow

```text
08:45 scan and send Top 5
09:20 start entry/watch loop
09:20-10:30 allow new entries
09:20-15:10 manage open positions
15:20 stop watcher and send summary
```

## Migration Steps

1. Create Supabase tables using `supabase/schema.sql`.
2. Move local JSON position storage to Supabase.
3. Move local trade log CSV storage to Supabase.
4. Convert `run_swing_bot.py` into Railway worker entrypoint.
5. Read two users from Railway environment variables.
6. Send Telegram Top 5 and trade event notifications per user.
7. Deploy to Railway as a worker, not a web server.

## Security

Keep KIS secrets in Railway variables. Do not expose the Supabase service role key in a frontend.
