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

create index if not exists idx_signals_trade_date_user on signals (trade_date, user_id);
create index if not exists idx_positions_user_status on positions (user_id, status);
create index if not exists idx_trade_logs_user_created_at on trade_logs (user_id, created_at desc);
create index if not exists idx_broker_accounts_user_active on broker_accounts (user_id, is_active);

alter table positions add column if not exists take_profit_1_done boolean not null default false;
alter table positions add column if not exists take_profit_2_done boolean not null default false;
alter table positions add column if not exists broker_account_id uuid;
alter table trade_logs add column if not exists broker_account_id uuid;
alter table broker_credentials add column if not exists live_order_enabled boolean not null default false;

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
alter table positions enable row level security;
alter table trade_logs enable row level security;

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

drop policy if exists "Users can read own positions" on positions;
create policy "Users can read own positions"
  on positions for select
  using (auth.uid() = user_id);

drop policy if exists "Users can read own trade logs" on trade_logs;
create policy "Users can read own trade logs"
  on trade_logs for select
  using (auth.uid() = user_id);
