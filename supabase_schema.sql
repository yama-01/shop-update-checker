-- Supabaseの「SQL Editor」にこの内容を貼り付けて実行してください（Runボタンを押すだけ）

-- 巡回対象の「お店」一覧
create table if not exists stores (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  url text not null,
  type text not null default 'page' check (type in ('page', 'rss', 'cast_list', 'girl_list', 'profile_list')),
  seen_links jsonb not null default '[]'::jsonb,
  enabled boolean not null default true,
  last_checked_at timestamptz,
  created_at timestamptz not null default now()
);

-- 個人利用向けの簡易セキュリティ設定
-- （anon keyを知っている人だけが読み書きできます。URLとanon keyは他人に共有しないでください）
alter table stores enable row level security;

create policy "allow read/write with anon key"
  on stores
  for all
  using (true)
  with check (true);


-- 日々のチェック結果（更新の有無）を記録するテーブル。
-- 将来、クローズドなサイトで日次・週次・月次の集計を表示するための元データになります。
create table if not exists update_logs (
  id uuid primary key default gen_random_uuid(),
  store_id uuid references stores(id) on delete set null,
  store_name text not null,
  checked_at timestamptz not null default now(),
  status text not null check (status in ('updated', 'no_update', 'first_check', 'error')),
  new_count integer not null default 0,
  new_items jsonb not null default '[]'::jsonb,
  error_message text
);

alter table update_logs enable row level security;

create policy "allow read/write with anon key"
  on update_logs
  for all
  using (true)
  with check (true);

-- 日・週・月ごとの集計を高速にするためのインデックス
create index if not exists update_logs_checked_at_idx on update_logs (checked_at);
create index if not exists update_logs_store_checked_idx on update_logs (store_id, checked_at);


-- ==============================
-- お店の登録例（このまま実行してもOK。不要なら削除してください）
-- ==============================
-- insert into stores (name, url, type) values
--   ('サンプル店A（ページ全体を監視）', 'https://example.com/news/', 'page'),
--   ('サンプル店B（RSSを監視）', 'https://example.com/feed', 'rss'),
--   ('サンプル店C（キャスト一覧を監視）', 'https://example.com/cast/', 'cast_list');
