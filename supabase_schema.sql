-- Supabaseの「SQL Editor」にこの内容を貼り付けて実行してください（Runボタンを押すだけ）
-- ※すでにこのプロジェクトでテーブルを作成済みの場合は、このファイルの下の方にある
--   「既存プロジェクトへの追加分」セクションだけを実行すればOKです（差分だけ反映されます）。

-- 巡回対象の「お店」一覧
create table if not exists stores (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  url text not null,
  type text not null default 'page' check (
    type in ('page', 'rss', 'cast_list', 'girl_list', 'profile_list', 'custom_pattern')
  ),
  -- type='custom_pattern'の場合に使う、新着ページを判定するための正規表現
  -- （例: e1ns.jpなら '/girls/detail/\d+'）。サイトごとにURL構造が違っても
  -- コードを直さずここで対応できるようにするための汎用設定。
  link_pattern text,
  -- 「〇名の入店がありました」（true）か「〇件の新着がありました」（false）かの表示切り替え。
  -- 空欄(NULL)の場合はtypeから自動判定される（cast_list/girl_list/profile_listはtrue扱い）。
  is_staff_list boolean,
  -- 系列店・グループの名前。同じgroup_nameを持つ店舗はLINE通知で1つにまとめて集計される。
  -- 単独の店舗はNULLのままでOK（その場合は店舗名単位で個別に通知される）
  group_name text,
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
-- crawl.py（毎日0時）が書き込み、notify.py（毎日9時）がここから前日分を読み出して通知する。
create table if not exists update_logs (
  id uuid primary key default gen_random_uuid(),
  store_id uuid references stores(id) on delete set null,
  store_name text not null,
  group_name text,
  store_type text,
  is_staff_list boolean not null default false,
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
-- 単独店舗（group_nameを指定しない＝個別に通知される）
-- insert into stores (name, url, type) values
--   ('サンプル店A（ページ全体を監視）', 'https://example.com/news/', 'page');
--
-- 系列店（同じgroup_nameを指定すると「A株式会社に3名の入店がありました」のように合算通知される）
-- insert into stores (name, url, type, group_name) values
--   ('A株式会社 新宿店', 'https://example.com/shinjuku/cast/', 'cast_list', 'A株式会社'),
--   ('A株式会社 池袋店',   'https://example.com/ikebukuro/cast/', 'cast_list', 'A株式会社'),
--   ('A株式会社 五反田店', 'https://example.com/gotanda/cast/', 'cast_list', 'A株式会社');
--
-- 独自のURLパターンを使う場合（例: e1ns.jpの「/girls/detail/数字」形式のページを新着として検知）
-- insert into stores (name, url, type, link_pattern, is_staff_list) values
--   ('e1ns 新人一覧', 'https://e1ns.jp/girls/newcomer-list', 'custom_pattern', '/girls/detail/\d+', true);


-- ==============================
-- 既存プロジェクトへの追加分（すでにテーブルを作成済みの場合はここだけ実行すればOK）
-- ==============================
-- alter table stores add column if not exists group_name text;
-- alter table stores add column if not exists link_pattern text;
-- alter table stores add column if not exists is_staff_list boolean;
-- alter table update_logs add column if not exists group_name text;
-- alter table update_logs add column if not exists store_type text;
-- alter table update_logs add column if not exists is_staff_list boolean not null default false;
--
-- -- typeの制約に custom_pattern を追加する場合（すでにtype制約付きでテーブル作成済みの場合のみ必要）
-- alter table stores drop constraint if exists stores_type_check;
-- alter table stores add constraint stores_type_check
--   check (type in ('page', 'rss', 'cast_list', 'girl_list', 'profile_list', 'custom_pattern'));
