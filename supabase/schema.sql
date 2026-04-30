create table if not exists broker_credentials (
  user_id uuid primary key,
  kis_app_key_enc text not null,
  kis_app_secret_enc text not null,
  kis_account_no text not null,
  kis_account_product_code text not null default '01',
  mode text not null default 'paper',
  telegram_chat_id text,
  live_order_enabled boolean not null default false,
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists broker_accounts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  label text,
  kis_app_key_enc text not null,
  kis_app_secret_enc text not null,
  kis_account_no text not null,
  kis_account_product_code text not null default '01',
  mode text not null default 'paper',
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

create table if not exists signals (
  id bigint generated always as identity primary key,
  trade_date date not null,
  user_id uuid not null,
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

create unique index if not exists uq_signals_trade_date_user_code
  on signals (trade_date, user_id, code);

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
  signals_count integer not null default 0,
  shared_saved integer not null default 0,
  result jsonb not null default '{}'::jsonb,
  error text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
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

create table if not exists ai_reports (
  id bigint generated always as identity primary key,
  trade_date date not null,
  report_type text not null,
  code text not null default 'ALL',
  name text,
  title text not null,
  markdown text not null,
  raw jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create unique index if not exists uq_trade_decision_logs_daily_reason
  on trade_decision_logs (decision_date, user_id, broker_account_id, code, reason_code);

create unique index if not exists uq_ai_reports_daily_type_code
  on ai_reports (trade_date, report_type, code);

create index if not exists idx_signals_trade_date_user on signals (trade_date, user_id);
create index if not exists idx_shared_signals_trade_date on shared_signals (trade_date, score desc);
create index if not exists idx_scan_runs_created_at on scan_runs (created_at desc);
create index if not exists idx_positions_user_status on positions (user_id, status);
create index if not exists idx_trade_logs_user_created_at on trade_logs (user_id, created_at desc);
create index if not exists idx_trade_decision_logs_user_date on trade_decision_logs (user_id, decision_date, created_at desc);
create index if not exists idx_broker_accounts_user_active on broker_accounts (user_id, is_active);
create index if not exists idx_ai_reports_trade_date on ai_reports (trade_date desc, report_type, code);

alter table positions add column if not exists take_profit_1_done boolean not null default false;
alter table positions add column if not exists take_profit_2_done boolean not null default false;
alter table positions add column if not exists broker_account_id uuid;
alter table trade_logs add column if not exists broker_account_id uuid;
alter table broker_credentials add column if not exists live_order_enabled boolean not null default false;
alter table scan_runs add column if not exists started_at timestamptz;
alter table broker_accounts add column if not exists access_token_enc text;
alter table broker_accounts add column if not exists access_token_expires_at timestamptz;

create index if not exists idx_positions_user_account_status on positions (user_id, broker_account_id, status);
create index if not exists idx_trade_logs_user_account_created_at on trade_logs (user_id, broker_account_id, created_at desc);

insert into broker_accounts (
  user_id,
  label,
  kis_app_key_enc,
  kis_app_secret_enc,
  kis_account_no,
  kis_account_product_code,
  mode,
  telegram_chat_id,
  live_order_enabled,
  enabled,
  is_active,
  created_at,
  updated_at
)
select
  user_id,
  case when mode = 'live' then '실전투자' else '모의투자' end,
  kis_app_key_enc,
  kis_app_secret_enc,
  kis_account_no,
  kis_account_product_code,
  mode,
  telegram_chat_id,
  live_order_enabled,
  enabled,
  true,
  created_at,
  updated_at
from broker_credentials
on conflict (user_id, mode) do nothing;

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

alter table broker_credentials enable row level security;
alter table broker_accounts enable row level security;
alter table signals enable row level security;
alter table shared_signals enable row level security;
alter table scan_runs enable row level security;
alter table strategy_settings enable row level security;
alter table positions enable row level security;
alter table trade_logs enable row level security;
alter table trade_decision_logs enable row level security;
alter table ai_reports enable row level security;

drop policy if exists "Users can read own broker credentials" on broker_credentials;
create policy "Users can read own broker credentials"
  on broker_credentials for select
  using (auth.uid() = user_id);

drop policy if exists "Users can read own broker accounts" on broker_accounts;
create policy "Users can read own broker accounts"
  on broker_accounts for select
  using (auth.uid() = user_id);

drop policy if exists "Users can read own signals" on signals;
create policy "Users can read own signals"
  on signals for select
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

drop policy if exists "Users can read own trade decision logs" on trade_decision_logs;
create policy "Users can read own trade decision logs"
  on trade_decision_logs for select
  using (auth.uid() = user_id);

drop policy if exists "Authenticated users can read ai reports" on ai_reports;
create policy "Authenticated users can read ai reports"
  on ai_reports for select
  using (auth.uid() is not null);
