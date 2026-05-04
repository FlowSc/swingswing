create table if not exists broker_accounts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  label text,
  kis_app_key_enc text not null,
  kis_app_secret_enc text not null,
  kis_account_no text not null,
  kis_account_product_code text not null default '01',
  mode text not null default 'paper',
  telegram_bot_token_enc text,
  telegram_chat_id text,
  live_order_enabled boolean not null default false,
  enabled boolean not null default true,
  is_active boolean not null default false,
  access_token_enc text,
  access_token_expires_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_broker_accounts_user_mode unique (user_id, mode)
);

create table if not exists user_memberships (
  user_id uuid primary key,
  role text not null default 'free' check (role in ('admin', 'free', 'paid')),
  paid_until timestamptz,
  report_enabled boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists shared_signals (
  id bigint generated always as identity primary key,
  trade_date date not null,
  code text not null,
  name text not null,
  entry numeric,
  stop_loss numeric,
  take_profit_1 numeric,
  take_profit_2 numeric,
  trailing_stop numeric,
  score numeric,
  raw jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create unique index if not exists uq_shared_signals_trade_date_code
  on shared_signals (trade_date, code);

create table if not exists scan_runs (
  id bigint generated always as identity primary key,
  requested_by uuid,
  status text not null default 'running',
  trade_date date,
  universe_scope text not null default 'all',
  signals_count integer not null default 0,
  shared_saved integer not null default 0,
  result jsonb not null default '{}'::jsonb,
  error text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);

create table if not exists backtest_runs (
  id bigint generated always as identity primary key,
  requested_by uuid not null,
  status text not null default 'running',
  source text not null default 'historical_rescan',
  strategy_key text not null default 'swing_default',
  strategy_version text not null default '2026-05-04',
  days integer not null default 120,
  max_signals integer not null default 200,
  start_date date,
  end_date date,
  universe_scope text not null default 'limited',
  processed_count integer not null default 0,
  total_count integer not null default 0,
  candidates_count integer not null default 0,
  tested_count integer not null default 0,
  result jsonb not null default '{}'::jsonb,
  summary jsonb not null default '{}'::jsonb,
  error text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);

create table if not exists backtest_trades (
  id bigint generated always as identity primary key,
  backtest_run_id bigint not null references backtest_runs(id) on delete cascade,
  trade_date date not null,
  entry_date date not null,
  code text not null,
  name text,
  score numeric,
  entry numeric,
  exit_price numeric,
  return_pct numeric,
  hold_days integer,
  exit_reason text,
  tp1_done boolean not null default false,
  tp2_done boolean not null default false,
  remaining_qty_ratio numeric,
  raw jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists strategy_settings (
  user_id uuid primary key,
  preset text not null default 'balanced',
  min_score numeric not null default 12,
  max_open_positions integer not null default 5,
  max_new_positions_per_day integer not null default 2,
  position_capital_pct numeric not null default 0.18,
  risk_per_trade_pct numeric not null default 0.01,
  min_order_amount integer not null default 100000,
  min_entry_discount numeric not null default 0.995,
  max_entry_premium numeric not null default 1.02,
  max_pullback_from_day_high numeric not null default 0.03,
  use_kijun_filter boolean not null default true,
  use_bb_upper_filter boolean not null default true,
  use_day_candle_filter boolean not null default false,
  use_breakeven_after_tp1 boolean not null default false,
  use_kijun_exit boolean not null default false,
  use_kijun_reentry_block boolean not null default true,
  use_daily_loss_limit boolean not null default true,
  daily_loss_limit_pct numeric not null default 0.03,
  use_unrealized_loss_limit boolean not null default true,
  unrealized_loss_limit_pct numeric not null default 0.04,
  use_market_crash_filter boolean not null default true,
  market_crash_limit_pct numeric not null default -0.02,
  commission_tax_pct numeric not null default 0.002,
  use_realtime_liquidity_filter boolean not null default true,
  min_realtime_strength numeric not null default 75,
  min_bid_ask_ratio numeric not null default 0.65,
  max_realtime_spread_pct numeric not null default 0.012,
  use_stoploss_reentry_block boolean not null default true,
  use_vi_filter boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists positions (
  id bigint generated always as identity primary key,
  user_id uuid not null,
  broker_account_id uuid,
  code text not null,
  name text not null,
  entry_date date not null,
  entry_price numeric not null,
  qty integer not null,
  remaining_qty integer not null,
  stop_loss numeric,
  take_profit_1 numeric,
  take_profit_2 numeric,
  trailing_stop numeric,
  status text not null default 'OPEN',
  take_profit_1_done boolean not null default false,
  take_profit_2_done boolean not null default false,
  raw jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists trade_logs (
  id bigint generated always as identity primary key,
  user_id uuid not null,
  broker_account_id uuid,
  action text not null,
  code text not null,
  name text,
  price numeric,
  qty integer,
  reason text,
  raw jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists pending_orders (
  id bigint generated always as identity primary key,
  user_id uuid not null,
  broker_account_id uuid,
  side text not null,
  code text not null,
  name text,
  qty integer not null,
  price numeric,
  order_no text,
  order_org_no text,
  status text not null default 'OPEN',
  reason text,
  raw jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists trade_decision_logs (
  id bigint generated always as identity primary key,
  decision_date date not null,
  user_id uuid not null,
  broker_account_id uuid,
  decision text not null,
  code text not null,
  name text,
  price numeric,
  score numeric,
  reason_code text not null,
  reason text not null,
  raw jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists watcher_runs (
  id bigint generated always as identity primary key,
  user_id uuid not null,
  broker_account_id uuid,
  mode text,
  orders_allowed boolean not null default false,
  entry_window_open boolean not null default false,
  manage_window_open boolean not null default false,
  cash numeric,
  total_equity numeric,
  signals_count integer not null default 0,
  open_positions_count integer not null default 0,
  kis_holdings_count integer not null default 0,
  pending_orders_count integer not null default 0,
  today_entry_count integer not null default 0,
  today_pending_buy_count integer not null default 0,
  remaining_daily_slots integer,
  available_slots integer,
  affordable_slots integer,
  daily_slots integer,
  action_count integer not null default 0,
  buy_order_count integer not null default 0,
  sell_order_count integer not null default 0,
  cooldown_skip_count integer not null default 0,
  skip_reason text,
  raw jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists watch_jobs (
  id bigint generated always as identity primary key,
  job_type text not null check (job_type in ('intraday', 'realtime_position')),
  user_id uuid not null,
  broker_account_id uuid not null,
  status text not null default 'pending' check (status in ('pending', 'running', 'completed', 'failed', 'skipped')),
  scheduled_for timestamptz not null,
  run_after timestamptz not null default now(),
  attempts integer not null default 0,
  locked_by text,
  locked_until timestamptz,
  error text,
  result jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);

create table if not exists ai_reports (
  id bigint generated always as identity primary key,
  trade_date date not null,
  report_type text not null,
  code text not null default 'ALL',
  name text,
  title text not null,
  status text not null default 'queued',
  markdown text not null default '',
  html text not null default '',
  error text,
  raw jsonb not null default '{}'::jsonb,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now()
);

create unique index if not exists uq_trade_decision_logs_daily_reason
  on trade_decision_logs (decision_date, user_id, broker_account_id, code, reason_code);

create unique index if not exists uq_ai_reports_daily_type_code
  on ai_reports (trade_date, report_type, code);

create index if not exists idx_shared_signals_trade_date on shared_signals (trade_date, score desc);
create index if not exists idx_scan_runs_created_at on scan_runs (created_at desc);
create index if not exists idx_backtest_runs_user_created_at on backtest_runs (requested_by, created_at desc);
create index if not exists idx_backtest_runs_status_created_at on backtest_runs (status, created_at desc);
create index if not exists idx_backtest_runs_strategy_date on backtest_runs (strategy_key, strategy_version, start_date, end_date);
create index if not exists idx_backtest_trades_run_return on backtest_trades (backtest_run_id, return_pct desc);
create index if not exists idx_positions_user_status on positions (user_id, status);
create index if not exists idx_trade_logs_user_created_at on trade_logs (user_id, created_at desc);
create index if not exists idx_trade_decision_logs_user_date on trade_decision_logs (user_id, decision_date, created_at desc);
create index if not exists idx_watcher_runs_user_created_at on watcher_runs (user_id, created_at desc);
create index if not exists idx_watcher_runs_account_created_at on watcher_runs (user_id, broker_account_id, created_at desc);
create unique index if not exists uq_watch_jobs_type_account_scheduled
  on watch_jobs (job_type, broker_account_id, scheduled_for);
create index if not exists idx_watch_jobs_status_run_after
  on watch_jobs (job_type, status, run_after, scheduled_for);
create index if not exists idx_watch_jobs_user_created_at on watch_jobs (user_id, created_at desc);
create index if not exists idx_broker_accounts_user_active on broker_accounts (user_id, is_active);
create index if not exists idx_ai_reports_trade_date on ai_reports (trade_date desc, report_type, code);
create index if not exists idx_ai_reports_status_created_at on ai_reports (status, created_at);
create index if not exists idx_pending_orders_user_account_status on pending_orders (user_id, broker_account_id, status);

alter table positions add column if not exists take_profit_1_done boolean not null default false;
alter table positions add column if not exists take_profit_2_done boolean not null default false;
alter table positions add column if not exists broker_account_id uuid;
alter table trade_logs add column if not exists broker_account_id uuid;
alter table scan_runs add column if not exists started_at timestamptz;
alter table scan_runs add column if not exists finished_at timestamptz;
alter table scan_runs add column if not exists universe_scope text not null default 'all';
alter table broker_accounts add column if not exists access_token_enc text;
alter table broker_accounts add column if not exists access_token_expires_at timestamptz;
alter table broker_accounts add column if not exists telegram_bot_token_enc text;
alter table strategy_settings add column if not exists use_day_candle_filter boolean not null default false;
alter table strategy_settings add column if not exists use_breakeven_after_tp1 boolean not null default false;
alter table strategy_settings add column if not exists use_kijun_exit boolean not null default false;
alter table strategy_settings add column if not exists use_kijun_reentry_block boolean not null default true;
alter table strategy_settings add column if not exists use_daily_loss_limit boolean not null default true;
alter table strategy_settings add column if not exists daily_loss_limit_pct numeric not null default 0.03;
alter table strategy_settings add column if not exists use_unrealized_loss_limit boolean not null default true;
alter table strategy_settings add column if not exists unrealized_loss_limit_pct numeric not null default 0.04;
alter table strategy_settings add column if not exists use_market_crash_filter boolean not null default true;
alter table strategy_settings add column if not exists market_crash_limit_pct numeric not null default -0.02;
alter table strategy_settings add column if not exists commission_tax_pct numeric not null default 0.002;
alter table strategy_settings add column if not exists use_realtime_liquidity_filter boolean not null default true;
alter table strategy_settings add column if not exists min_realtime_strength numeric not null default 75;
alter table strategy_settings add column if not exists min_bid_ask_ratio numeric not null default 0.65;
alter table strategy_settings add column if not exists max_realtime_spread_pct numeric not null default 0.012;
alter table strategy_settings add column if not exists use_stoploss_reentry_block boolean not null default true;
alter table strategy_settings add column if not exists use_vi_filter boolean not null default true;

update strategy_settings
set
  use_daily_loss_limit = true,
  use_unrealized_loss_limit = true,
  use_market_crash_filter = true,
  use_realtime_liquidity_filter = true,
  use_stoploss_reentry_block = true,
  use_kijun_reentry_block = true,
  use_vi_filter = true;

alter table ai_reports add column if not exists status text not null default 'queued';
alter table ai_reports add column if not exists error text;
alter table ai_reports add column if not exists started_at timestamptz;
alter table ai_reports add column if not exists finished_at timestamptz;
alter table ai_reports add column if not exists html text not null default '';
alter table ai_reports alter column markdown set default '';
alter table ai_reports alter column markdown set not null;
alter table watcher_runs add column if not exists cooldown_skip_count integer not null default 0;
alter table watcher_runs add column if not exists today_entry_count integer not null default 0;
alter table watcher_runs add column if not exists today_pending_buy_count integer not null default 0;
alter table watcher_runs add column if not exists remaining_daily_slots integer;

create index if not exists idx_positions_user_account_status on positions (user_id, broker_account_id, status);
create index if not exists idx_trade_logs_user_account_created_at on trade_logs (user_id, broker_account_id, created_at desc);

update positions
set broker_account_id = broker_accounts.id
from broker_accounts
where positions.broker_account_id is null
  and positions.user_id = broker_accounts.user_id
  and broker_accounts.mode = 'paper';

update trade_logs
set broker_account_id = broker_accounts.id
from broker_accounts
where trade_logs.broker_account_id is null
  and trade_logs.user_id = broker_accounts.user_id
  and broker_accounts.mode = 'paper';

alter table broker_accounts enable row level security;
alter table user_memberships enable row level security;
alter table shared_signals enable row level security;
alter table scan_runs enable row level security;
alter table strategy_settings enable row level security;
alter table positions enable row level security;
alter table trade_logs enable row level security;
alter table pending_orders enable row level security;
alter table trade_decision_logs enable row level security;
alter table watcher_runs enable row level security;
alter table watch_jobs enable row level security;
alter table ai_reports enable row level security;

drop policy if exists "Users can read own broker accounts" on broker_accounts;
create policy "Users can read own broker accounts"
  on broker_accounts for select
  using (auth.uid() = user_id);

drop policy if exists "Users can read own membership" on user_memberships;
create policy "Users can read own membership"
  on user_memberships for select
  using (auth.uid() = user_id);

drop policy if exists "Users can read shared signals" on shared_signals;
create policy "Users can read shared signals"
  on shared_signals for select
  using (auth.uid() is not null);

drop policy if exists "Users can read scan runs" on scan_runs;
create policy "Users can read scan runs"
  on scan_runs for select
  using (auth.uid() is not null);

drop policy if exists "Users can read own strategy settings" on strategy_settings;
create policy "Users can read own strategy settings"
  on strategy_settings for select
  using (auth.uid() = user_id);

drop policy if exists "Users can read own positions" on positions;
create policy "Users can read own positions"
  on positions for select
  using (auth.uid() = user_id);

drop policy if exists "Users can read own trade logs" on trade_logs;
create policy "Users can read own trade logs"
  on trade_logs for select
  using (auth.uid() = user_id);

drop policy if exists "Users can read own pending orders" on pending_orders;
create policy "Users can read own pending orders"
  on pending_orders for select
  using (auth.uid() = user_id);

drop policy if exists "Users can read own trade decision logs" on trade_decision_logs;
create policy "Users can read own trade decision logs"
  on trade_decision_logs for select
  using (auth.uid() = user_id);

drop policy if exists "Users can read own watcher runs" on watcher_runs;
create policy "Users can read own watcher runs"
  on watcher_runs for select
  using (auth.uid() = user_id);

drop policy if exists "Users can read own watch jobs" on watch_jobs;
create policy "Users can read own watch jobs"
  on watch_jobs for select
  using (auth.uid() = user_id);

drop policy if exists "Authenticated users can read ai reports" on ai_reports;
drop policy if exists "Report members can read ai reports" on ai_reports;
create policy "Report members can read ai reports"
  on ai_reports for select
  using (
    exists (
      select 1
      from user_memberships
      where user_memberships.user_id = auth.uid()
        and (
          user_memberships.role = 'admin'
          or (
            user_memberships.role = 'paid'
            and user_memberships.report_enabled = true
            and user_memberships.paid_until is not null
            and user_memberships.paid_until > now()
          )
        )
    )
  );

drop table if exists broker_credentials;
drop table if exists signals cascade;
