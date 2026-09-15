"""
毎日9時(JST)に実行する通知スクリプト。
直前0時(JST)のcrawl.py実行結果（update_logs）を読み出し、系列店（group_name）ごとに
まとめた上で、前日分の更新チェック結果を1通のLINEダイジェストとして送信する。

例: 27日に更新があった場合、27日24時(=28日0時)のcrawl.pyが26日24時(=27日0時)時点との
差分を検知してSupabaseに記録し、28日9時のこのスクリプトが「27日は〇〇店に…」という
メッセージを送信する。

GitHub Actionsから毎日9時(JST)に定期実行される想定。
"""

import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

JST = ZoneInfo("Asia/Tokyo")

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
LINE_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


def get_todays_crawl_logs():
    """今日のJST 0:00以降に記録されたチェック結果を取得する（＝直前に実行されたcrawl.py分）"""
    today_start_jst = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start_jst.astimezone(timezone.utc).isoformat()
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/update_logs",
        headers=HEADERS,
        # paramsを使うことで、日時に含まれる「+」等の記号がURL上で正しくエンコードされるようにする
        # （文字列結合で直接URLに埋め込むと「+00:00」の「+」がスペースとして扱われ400エラーになる）
        params={
            "checked_at": f"gte.{today_start_utc}",
            "order": "checked_at.asc",
            "select": "*",
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def send_line(text: str):
    if not text:
        return
    resp = requests.post(
        "https://api.line.me/v2/bot/message/broadcast",
        headers={
            "Authorization": f"Bearer {LINE_TOKEN}",
            "Content-Type": "application/json",
        },
        json={"messages": [{"type": "text", "text": text[:5000]}]},
        timeout=20,
    )
    if resp.status_code >= 300:
        print(f"LINE送信エラー: {resp.status_code} {resp.text}", file=sys.stderr)


def build_group_block(group_name, members):
    """1グループ（系列店。単独店舗の場合はメンバー1件のグループ）分の通知ブロックを作る"""
    updated = [m for m in members if m["status"] == "updated"]
    no_update = [m for m in members if m["status"] == "no_update"]
    first_check = [m for m in members if m["status"] == "first_check"]
    errors = [m for m in members if m["status"] == "error"]

    header = f"【{group_name}】"
    lines = []

    if updated:
        total_new = sum(m["new_count"] for m in updated)
        # is_staff_listはcrawl.py側で確定済みの値（storesのis_staff_list列、未設定ならtypeから自動判定）
        is_hire = all(m.get("is_staff_list") for m in updated)
        if is_hire:
            lines.append(header + f"{total_new}名の入店がありました")
        else:
            lines.append(header + f"{total_new}件の新着がありました")

        samples = []
        for m in updated:
            for item in m.get("new_items") or []:
                samples.append(item["url"])
        shown = samples[:3]
        for url in shown:
            lines.append(url)
        remaining = total_new - len(shown)
        if remaining > 0:
            lines.append(f"…ほか{remaining}件")
    elif no_update:
        lines.append(header + "更新なし")
    elif first_check:
        lines.append(header + "初回チェックのため基準データを保存しました")
    else:
        # メンバー全員がエラーだった場合
        lines.append(header + "チェックに失敗しました")

    # 一部の店舗だけ初回チェック中だった場合の補足
    if (updated or no_update) and first_check:
        names = "、".join(m["store_name"] for m in first_check)
        lines.append(f"(初回チェック中: {names})")

    # エラーだった店舗の個別表示（グループ全体がエラーの場合は上ですでに表示済みなので除く）
    if errors and (updated or no_update or first_check):
        for m in errors:
            lines.append(f"⚠️{m['store_name']}のチェックに失敗しました")

    return "\n".join(lines)


def main():
    logs = get_todays_crawl_logs()
    report_date = (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")

    if not logs:
        print("本日分のチェック結果が見つかりません（crawl.pyがまだ実行されていない可能性があります）")
        send_line(
            f"◆{report_date}の更新チェック結果\n\n"
            "チェック結果が見つかりませんでした。crawl.pyの実行状況を確認してください。"
        )
        return

    groups = defaultdict(list)
    for log in logs:
        key = log.get("group_name") or log["store_name"]
        groups[key].append(log)

    blocks = [build_group_block(name, members) for name, members in groups.items()]

    message = f"◆{report_date}の更新チェック結果\n\n" + "\n\n".join(blocks)
    send_line(message)
    print(f"[LINE送信] {report_date}分のダイジェストを送信しました（{len(groups)}グループ分）")


if __name__ == "__main__":
    main()
