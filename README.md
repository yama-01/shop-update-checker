# shop-update-checker

複数のお店（サイト）を毎日巡回し、更新の有無をLINEに通知するBotです。
GitHub Actions + Python + Supabase で構成されており、サーバー不要で動きます。

## できること

- 登録した複数のお店のページ（通常ページ／RSS／キャスト一覧など）を毎日1回巡回
- 巡回(0時)と通知(9時)を分離し、「前日分」のチェック結果を翌朝まとめて通知
- 更新があったお店・なかったお店をまとめて1通のLINEメッセージ（ダイジェスト）で通知
- 更新がなかった場合も「更新なし」として通知するので、Botが正常に動いているか一目で分かる
- 系列店・グループの店舗はまとめて合算し、「A株式会社に3名の入店がありました」のように
  グループ単位で通知（`group_name`を設定した場合のみ。設定しなければ店舗ごとに個別通知）
- 毎回のチェック結果を`update_logs`テーブルに記録（今後、日次・週次・月次で集計・閲覧できる
  クローズドなサイトを作る際の元データになります）

## 仕組み（巡回と通知が分かれている理由）

このBotは2本のスクリプト・2つのGitHub Actionsで構成されています。

| スクリプト | 実行時刻(JST) | 役割 |
|---|---|---|
| `crawl.py` | 毎日0:00 | 各お店を巡回し、前回チェック時からの差分（新着）を検知して`update_logs`に記録する。LINE送信はしない |
| `notify.py` | 毎日9:00 | 直前0:00の`crawl.py`実行結果を読み出し、系列店をまとめてLINEに1通のダイジェストを送信する |

例えば27日に更新があった場合、27日24時(=28日0時)の`crawl.py`が26日24時(=27日0時)
時点との差分を検知して記録し、28日9時の`notify.py`が「27日は〇〇店に…」というメッセージを
送信します。

## セットアップ手順

### 1. Supabaseプロジェクトを作成する

1. https://supabase.com でプロジェクトを作成
2. 「SQL Editor」を開き、`supabase_schema.sql` の内容を貼り付けて実行する
   （`stores`テーブルと`update_logs`テーブルが作成されます）
3. 「Project Settings」→「API Keys」から、次の2つを控えておく
   - Project URL（`SUPABASE_URL`。アドレスバーの`.../project/xxxxx/...`の`xxxxx`部分を使って
     `https://xxxxx.supabase.co`の形になります）
   - Secret key（`SUPABASE_SERVICE_KEY`。「Publishable and secret API keys」タブの
     「Secret keys」欄にあるものを使ってください）

### 2. LINE Messaging APIのチャネルを用意する

1. [LINE Developers](https://developers.line.biz/) でMessaging APIチャネルを作成
2. 発行された「チャネルアクセストークン（長期）」を控えておく（`LINE_CHANNEL_ACCESS_TOKEN`）
3. 作成したチャネルの公式アカウントを、通知を受け取りたいLINEアカウントで友だち追加する
   （このBotは`broadcast`（一斉送信）APIを使うため、その公式アカウントを友だち追加している
   全員に届きます。個人利用であれば自分だけが友だち追加した状態にしてください）

### 3. 巡回したいお店を登録する

Supabaseの「Table Editor」→「stores」テーブルに、お店を1件ずつ追加します。

| カラム | 内容 |
|---|---|
| `name` | LINE通知に表示するお店の名前 |
| `url`  | 巡回するページのURL |
| `type` | 監視方法（下記を参照） |
| `group_name` | 系列店・グループの名前（任意）。同じ名前を複数の店舗に設定すると、通知時に合算して1行にまとまる |

`type`に指定できる値:

- `page` : ページ内のリンク一覧を丸ごと監視（汎用。まず迷ったらこれでOK）
- `rss`  : サイトのRSS/Atomフィードを監視
- `cast_list` : `/cast/123456.html`のようなキャスト個別ページの一覧を監視
- `girl_list` : `/girl/115/`のような個別ページの一覧を監視
- `profile_list` : `/profile.html?id=xxxxxxxxxxxxxxxx`のようなプロフィールページの一覧を監視

`group_name`の例: 「A株式会社」の新宿店・池袋店・五反田店をそれぞれ1行ずつ登録し、
3行すべての`group_name`に「A株式会社」と入力すると、いずれかの店舗に新着があった日は
「【A株式会社】3名の入店がありました」のようにグループ合計で通知されます（単独の店舗は
`group_name`を空欄のままにしておけば、これまで通り店舗ごとに個別通知されます）。

登録した直後の1回目のチェックでは、その時点のリンクを「既知」として保存するだけで通知は
「初回チェック」扱いになります（登録前からある大量のリンクを新着として誤通知しないため）。

### 4. GitHub ActionsのSecretsを設定する

このリポジトリの Settings → Secrets and variables → Actions →「Repository secrets」で、
以下を登録します（「Environment secrets」ではありません）。

- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `LINE_CHANNEL_ACCESS_TOKEN`

### 5. 動作確認

Actionsタブを開き、以下の順に手動実行(Run workflow)して動作確認してください。

1. 「Crawl stores (daily at 0:00 JST)」を実行する（巡回してSupabaseに記録するだけ。
   LINEは届きません）
2. 続けて「Notify LINE (daily at 9:00 JST)」を実行する（1で記録された結果をLINEに送信する）

普段は`crawl.py`が毎日0時、`notify.py`が毎日9時に自動実行されます。

## 今後の予定

`update_logs`テーブルに日々の結果が溜まっていくので、これを使って日次・週次・月次の
更新状況を閲覧できるクローズドなWebサイトを別途作成する予定です。
