"""
毎日0時(JST)に実行する巡回スクリプト。
登録された「お店」のページを巡回し、前回チェック時からの差分（新着）を検知して
Supabaseのupdate_logsに記録する。LINE通知はここでは行わない
（通知は notify.py が9時に別途実行して担当する）。

GitHub Actionsから毎日0時(JST)に定期実行される想定。
"""

import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

# 「cast/123456.html」のようなキャスト個別ページのURLパターン
CAST_URL_PATTERN = re.compile(r"/cast/\d+\.html$")
# 「girl/115/」のような女性個別ページのURLパターン（girlreview等の下位ページは除外）
GIRL_URL_PATTERN = re.compile(r"/girl/\d+/$")
# 「profile.html?id=xxxxxxxx」のようなプロフィールページのURLパターン
PROFILE_URL_PATTERN = re.compile(r"/profile\.html\?id=[0-9a-f]{16,}", re.IGNORECASE)

# type=cast_list / girl_list / profile_list / custom_patternのお店は「新人が入店した」という
# 文脈で件数を表示するデフォルト対象（storesの`is_staff_list`列で個別に上書き可能）
DEFAULT_STAFF_LIST_TYPES = {"cast_list", "girl_list", "profile_list"}

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

MAX_LINKS_STORED = 2000
# update_logsに保存する新着リンクのサンプル件数（表示・記録用の上限。件数自体はnew_countで正確に保持する）
SAMPLE_ITEMS_LIMIT = 10


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


def log_check_result(store_id, store_name, group_name, store_type, is_staff_list, status, new_items_all, error_message=None):
    """このチェック結果をupdate_logsに記録する。new_countは実際の新着数を正確に保持し、
    new_itemsにはSAMPLE_ITEMS_LIMIT件までのサンプルのみ保存する（通知メッセージの表示用）。"""
    payload = {
        "store_id": store_id,
        "store_name": store_name,
        "group_name": group_name,
        "store_type": store_type,
        "is_staff_list": is_staff_list,
        "status": status,
        "new_count": len(new_items_all),
        "new_items": [
            {"title": title, "url": href} for title, href in new_items_all[:SAMPLE_ITEMS_LIMIT]
        ],
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


def fetch_pattern_list_links(url, pattern):
    """お店ごとに登録された正規表現（link_pattern）に一致するリンクのみを抽出する汎用関数。
    サイトごとにURL構造がバラバラなため、コードを直接変更しなくても
    Supabase側の設定だけで新しいサイト構造に対応できるようにするためのもの。"""
    if not pattern:
        raise ValueError("type=custom_patternのお店にはlink_pattern（正規表現）の設定が必要です")
    compiled = re.compile(pattern)
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    hrefs = []
    seen_in_page = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        # クエリやフラグメントを除いた素のURLで判定・保存する（?ref=xxxのような追跡パラメータで
        # 同じページが別リンクとして重複検知されるのを防ぐ）
        clean_href = href.split("?")[0].split("#")[0]
        if compiled.search(clean_href) and clean_href not in seen_in_page:
            seen_in_page.add(clean_href)
            hrefs.append(clean_href)
    return hrefs


def fetch_page_links(url):
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    links = []
    seen_hrefs = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        title = a.get_text(strip=True)
        # 同じリンクがページ内の複数箇所（一覧と右カラムなど）に出てきても1件だけ拾う
        if title and href.startswith("http") and href not in seen_hrefs:
            seen_hrefs.add(href)
            links.append((title, href))
    return links[:150]


def main():
    stores = get_stores()
    print(f"{len(stores)}件のお店をチェックします")

    for store in stores:
        store_id = store["id"]
        name = store["name"]
        store_type = store["type"]
        group_name = store.get("group_name")
        # is_staff_listが未設定(null)の場合は、typeから自動判定する
        is_staff_list = store.get("is_staff_list")
        if is_staff_list is None:
            is_staff_list = store_type in DEFAULT_STAFF_LIST_TYPES

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
            elif store_type == "custom_pattern":
                # お店ごとにSupabaseのlink_pattern列で正規表現を設定してもらう汎用タイプ
                links = [(None, href) for href in fetch_pattern_list_links(store["url"], store.get("link_pattern"))]
            else:
                links = fetch_page_links(store["url"])
        except Exception as e:
            print(f"[エラー] {name}: {e}", file=sys.stderr)
            log_check_result(store_id, name, group_name, store_type, is_staff_list, "error", [], error_message=str(e))
            continue

        seen = set(store.get("seen_links") or [])
        is_first_check = len(seen) == 0

        current_hrefs = []
        new_items = []
        new_item_hrefs = set()
        for title, href in links:
            if href not in current_hrefs:
                current_hrefs.append(href)
            # 同じURLがページ内の複数箇所（例：中央の一覧と右カラムに両方表示される等）に
            # 出てきても、新着としては1件だけカウントする
            if href not in seen and href not in new_item_hrefs:
                new_items.append((title, href))
                new_item_hrefs.add(href)

        # 初回チェック時は基準データを保存するだけ（大量通知を防ぐため「更新あり」とはしない）
        if is_first_check:
            log_check_result(store_id, name, group_name, store_type, is_staff_list, "first_check", [])
            print(f"[初回] {name}")
        elif new_items:
            log_check_result(store_id, name, group_name, store_type, is_staff_list, "updated", new_items)
            print(f"[更新あり] {name}: {len(new_items)}件の新着")
        else:
            log_check_result(store_id, name, group_name, store_type, is_staff_list, "no_update", [])
            print(f"[更新なし] {name}")

        # 既知リンクとして必ず保存する（重要：今回取得できたリンクだけで上書きせず、
        # これまでの既知リンクと合算（マージ）する。ページの表示順や一部入れ替わりで
        # 今回たまたま表示されなかった過去のリンクも既知として保持し続けることで、
        # 同じ項目を繰り返し「新着」と誤検知しないようにする）
        merged_links = list(seen | set(current_hrefs))
        update_store(store_id, merged_links[:MAX_LINKS_STORED])

    print("[巡回完了] 結果をupdate_logsに記録しました（LINE通知は次回のnotify.py実行時に送信されます）")


if __name__ == "__main__":
    main()
