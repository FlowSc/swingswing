# Railway/Supabase Migration Plan

This folder is reserved for the server version of the swing bot.

Target structure:

```text
app/
  main.py              # Railway worker entrypoint
  scheduler.py         # Seoul-time market schedule
  scanner.py           # Daily signal scan
  watcher.py           # Intraday position watcher
  kis.py               # KIS API adapter
  telegram.py          # Telegram notifications
  db.py                # Supabase access
```

Initial production shape:

- Railway runs one worker process.
- User API credentials stay in Railway environment variables for two users.
- Supabase stores signals, positions, and trade logs.
- Telegram sends Top 5 morning signals and trade events.

Do not store KIS API secrets in Supabase unless encryption is added.
