# shop-update-checker

複数のお店（サイト）を毎日巡回し、更新の有無をLINEに通知するBotです。
GitHub Actions + Python + Supabase で構成されており、サーバー不要で動きます。

## できること

- 登録した複数のお店のページ（通常ページ／RSS／キャスト一覧など）を毎日1回巡回
- 更新があったお店・なかったお店をまとめて1通のLINEメッセージ（ダイジェスト）で通知
- 更新がなかった場合も「更新なし」として通知するので、Botが正常に動いているか一目で分かる
- 毎回のチェック結果を`update_logs`テーブルに記録（今後、日次・週次・月次で集計・閲覧できる
  クローズドなサイトを作る際の元データになります）

## セットアップ手順

### 1. Supabaseプロジェクトを作成する

1. https://supabase.com でプロジェクトを作成
2. 「SQL Editor」を開き、`supabase_schema.sql` の内容を貼り付けて実行する
   （`stores`テーブルと`update_logs`テーブルが作成されます）
3. 「Project Settings」→「API」から、次の2つを控えておく
   - Project URL（`SUPABASE_URL`）
   - `service_role` キー（`SUPABASE_SERVICE_KEY`。anonキーではなく`service_role`キーを使ってください）

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

`type`に指定できる値:

- `page` : ページ内のリンク一覧を丸ごと監視（汎用。まず迷ったらこれでOK）
- `rss`  : サイトのRSS/Atomフィードを監視
- `cast_list` : `/cast/123456.html`のようなキャスト個別ページの一覧を監視
- `girl_list` : `/girl/115/`のような個別ページの一覧を監視
- `profile_list` : `/profile.html?id=xxxxxxxxxxxxxxxx`のようなプロフィールページの一覧を監視

登録した直後の1回目のチェックでは、その時点のリンクを「既知」として保存するだけで通知は
「初回チェック」扱いになります（登録前からある大量のリンクを新着として誤通知しないため）。

### 4. GitHub ActionsのSecretsを設定する

このリポジトリの Settings → Secrets and variables → Actions で、以下を登録します。

- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `LINE_CHANNEL_ACCESS_TOKEN`

### 5. 動作確認

Actionsタブ →「Check stores for updates」→「Run workflow」で手動実行し、LINEに
ダイジェストメッセージが届くか確認してください。普段は毎朝9時（日本時間）に自動実行されます。

## 今後の予定

`update_logs`テーブルに日々の結果が溜まっていくので、これを使って日次・週次・月次の
更新状況を閲覧できるクローズドなWebサイトを別途作成する予定です。
