"""
登録された「お店」のページを毎日巡回し、その日のチェック結果を1通のLINEメッセージ
（ダイジェスト）にまとめて送信するスクリプト。更新の有無にかかわらず毎日通知する。

また、あとで日次・週次・月次の集計サイトを作れるように、チェック結果を毎回
Supabaseのupdate_logsテーブルに記録する。

GitHub Actionsから毎朝9時(JST)に定期実行される想定。
"""

import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import feedparser
import requests
from bs4 import BeautifulSoup

JST = ZoneInfo("Asia/Tokyo")

# 「cast/123456.html」のようなキャスト個別ページのURLパターン
CAST_URL_PATTERN = re.compile(r"/cast/\d+\.html$")
# 「girl/115/」のような女性個別ページのURLパターン（girlreview等の下位ページは除外）
GIRL_URL_PATTERN = re.compile(r"/girl/\d+/$")
# 「profile.html?id=xxxxxxxx」のようなプロフィールページのURLパターン
PROFILE_URL_PATTERN = re.compile(r"/profile\.html\?id=[0-9a-f]{16,}", re.IGNORECASE)

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
LINE_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

MAX_LINKS_STORED = 2000
MAX_NOTIFY_PER_STORE = 10


def get_stores():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/stores?enabled=eq.true&select=*",
        headers=HEADERS,
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def update_store(store_id, seen_links):
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/stores?id=eq.{store_id}",
        headers=HEADERS,
        json={
            "seen_links": seen_links,
            "last_checked_at": datetime.now(timezone.utc).isoformat(),
        },
        timeout=20,
    )


def log_check_result(store_id, store_name, status, new_items, error_message=None):
    """このチェック結果をupdate_logsに記録する（日次・週次・月次の集計サイト用の元データ）"""
    payload = {
        "store_id": store_id,
        "store_name": store_name,
        "status": status,
        "new_count": len(new_items),
        "new_items": [{"title": title, "url": href} for title, href in new_items],
    }
    if error_message:
        payload["error_message"] = error_message[:500]
    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/update_logs",
            headers=HEADERS,
            json=payload,
            timeout=20,
        )
        if r.status_code >= 300:
            print(f"[ログ保存エラー] {store_name}: {r.status_code} {r.text}", file=sys.stderr)
    except Exception as e:
        print(f"[ログ保存エラー] {store_name}: {e}", file=sys.stderr)


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


def fetch_rss_links(url):
    feed = feedparser.parse(url)
    return [
        (e.get("title", url).strip(), e.get("link", url))
        for e in feed.entries[:30]
        if e.get("link")
    ]


def fetch_cast_list_links(url):
    """キャスト一覧ページから、個別キャストページ（cast/数字.html）のリンクのみを抽出する"""
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    hrefs = []
    seen_in_page = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        if CAST_URL_PATTERN.search(href) and href not in seen_in_page:
            seen_in_page.add(href)
            hrefs.append(href)
    return hrefs


def fetch_girl_list_links(url):
    """女性一覧ページから、個別ページ（girl/数字/）のリンクのみを抽出する（girlreview等は除外）"""
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    hrefs = []
    seen_in_page = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        # クエリやフラグメントを除いた素のパスで判定する
        clean_href = href.split("?")[0].split("#")[0]
        if not clean_href.endswith("/"):
            clean_href += "/"
        if GIRL_URL_PATTERN.search(clean_href) and clean_href not in seen_in_page:
            seen_in_page.add(clean_href)
            hrefs.append(clean_href)
    return hrefs


def fetch_profile_list_links(url):
    """セラピスト一覧ページから、個別プロフィールページ（profile.html?id=xxx）のリンクのみを抽出する"""
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    hrefs = []
    seen_in_page = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        if PROFILE_URL_PATTERN.search(href) and href not in seen_in_page:
            seen_in_page.add(href)
            hrefs.append(href)
    return hrefs


def fetch_page_links(url):
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        title = a.get_text(strip=True)
        if title and href.startswith("http"):
            links.append((title, href))
    return links[:150]


def build_updated_block(name, store_type, items):
    """1店舗分の「更新あり」ブロックを、通知メッセージ用に整形する"""
    shown = items[:3]
    remaining = len(items) - len(shown)

    if store_type in ("cast_list", "girl_list", "profile_list"):
        lines = [f"【{name}】新人が入店しました"]
    else:
        lines = [f"【{name}】{len(items)}件の新着"]
    for title, href in shown:
        lines.append(href)

    if remaining > 0:
        lines.append(f"…ほか{remaining}件")
    return "\n".join(lines)


def main():
    stores = get_stores()
    print(f"{len(stores)}件のお店をチェックします")

    blocks = []

    for store in stores:
        store_id = store["id"]
        name = store["name"]
        store_type = store["type"]
        try:
            if store_type == "rss":
                links = fetch_rss_links(store["url"])
            elif store_type == "cast_list":
                # cast_listはURLのみのリストなので (title, href) の形に揃える
                links = [(None, href) for href in fetch_cast_list_links(store["url"])]
            elif store_type == "girl_list":
                links = [(None, href) for href in fetch_girl_list_links(store["url"])]
            elif store_type == "profile_list":
                links = [(None, href) for href in fetch_profile_list_links(store["url"])]
            else:
                links = fetch_page_links(store["url"])
        except Exception as e:
            print(f"[エラー] {name}: {e}", file=sys.stderr)
            blocks.append(f"【{name}】⚠️チェックに失敗しました")
            log_check_result(store_id, name, "error", [], error_message=str(e))
            continue

        seen = set(store.get("seen_links") or [])
        is_first_check = len(seen) == 0

        current_hrefs = []
        new_items = []
        for title, href in links:
            if href not in current_hrefs:
                current_hrefs.append(href)
            if href not in seen and len(new_items) < MAX_NOTIFY_PER_STORE:
                new_items.append((title, href))

        # 初回チェック時は基準データを保存するだけ（大量通知を防ぐため「更新あり」とはしない）
        if is_first_check:
            blocks.append(f"【{name}】初回チェックのため基準データを保存しました")
            log_check_result(store_id, name, "first_check", [])
            print(f"[初回] {name}")
        elif new_items:
            blocks.append(build_updated_block(name, store_type, new_items))
            log_check_result(store_id, name, "updated", new_items)
            print(f"[更新あり] {name}: {len(new_items)}件の新着")
        else:
            blocks.append(f"【{name}】更新なし")
            log_check_result(store_id, name, "no_update", [])
            print(f"[更新なし] {name}")

        # LINE送信の成否に関わらず、既知リンクとして必ず保存する
        # 重要：今回取得できたリンクだけで上書きせず、これまでの既知リンクと合算（マージ）する。
        # ページの表示順や一部入れ替わりで今回たまたま表示されなかった過去のリンクも、
        # 既知として保持し続けることで、同じキャストを繰り返し「新着」と誤検知しないようにする。
        merged_links = list(seen | set(current_hrefs))
        update_store(store_id, merged_links[:MAX_LINKS_STORED])

    # 更新の有無にかかわらず、全店舗分の結果を1通のダイジェストにまとめて毎日送信する
    today_str = datetime.now(JST).strftime("%Y-%m-%d")
    message = f"◆本日の更新チェック結果({today_str})\n\n" + "\n\n".join(blocks)
    send_line(message)
    print("[LINE送信] 本日分のダイジェストを送信しました")


if __name__ == "__main__":
    main()
