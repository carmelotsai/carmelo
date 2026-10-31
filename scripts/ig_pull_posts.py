#!/usr/bin/env python3
"""
抓取 IG 專業帳號最近 N 則貼文的 Insights，輸出 CSV / Markdown 表格。

用法:
    export IG_USER_ID=...        # Instagram 專業帳號的 IG User ID (純數字)
    export IG_ACCESS_TOKEN=...   # 具 instagram_basic + instagram_manage_insights 權限的 token
    python3 scripts/ig_pull_posts.py --limit 30 --out out/

產出:
    out/ig_posts.csv   原始欄位（API 沒給的留空，不估算）
    out/ig_posts.md    貼上就能看的表格

注意：API 拿不到的欄位（非追蹤者占比、3 秒留存）本腳本不產生、也不推估。
"""
import argparse
import csv
import json
import os
import sys
import urllib.parse
import urllib.request

API = "https://graph.facebook.com/v23.0"

# 各媒體類型要求的 insight metrics。API 對不支援的 metric 會整個請求報錯，
# 所以按類型分開要，並且在失敗時逐一退化（見 fetch_insights）。
METRICS_BY_TYPE = {
    "REELS":     ["views", "reach", "shares", "saved", "likes", "comments",
                  "total_interactions", "ig_reels_avg_watch_time", "follows"],
    "VIDEO":     ["views", "reach", "shares", "saved", "likes", "comments",
                  "total_interactions", "ig_reels_avg_watch_time", "follows"],
    "CAROUSEL_ALBUM": ["views", "reach", "shares", "saved", "likes", "comments",
                       "total_interactions", "follows"],
    "IMAGE":     ["views", "reach", "shares", "saved", "likes", "comments",
                  "total_interactions", "follows"],
}

COLUMNS = [
    "序", "日期", "類型", "永久連結",
    "觀看(views)", "觸及(reach)", "分享(shares)", "儲存(saved)",
    "平均觀看時間(秒)", "新增追蹤(follows)",
    "讚", "留言", "互動總數",
    "非追蹤者占比", "3秒留存",          # API 不提供，固定留空
    "開頭那句話", "產品/系列", "鞋款",   # 由 caption 整理，需人工確認
]


def get(path, params):
    params = dict(params)
    params["access_token"] = os.environ["IG_ACCESS_TOKEN"]
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise SystemExit(f"API 錯誤 {e.code} @ {path}\n{body}")


def fetch_media(user_id, limit):
    media, after = [], None
    while len(media) < limit:
        params = {
            "fields": "id,caption,media_type,media_product_type,timestamp,permalink",
            "limit": min(50, limit - len(media)),
        }
        if after:
            params["after"] = after
        page = get(f"{user_id}/media", params)
        media.extend(page.get("data", []))
        after = page.get("paging", {}).get("cursors", {}).get("after")
        if not after or not page.get("data"):
            break
    return media[:limit]


def fetch_insights(media_id, media_type):
    """逐一要 metric：某個 metric 不支援時只有那一欄留空，不會整篇抓不到。"""
    wanted = METRICS_BY_TYPE.get(media_type, METRICS_BY_TYPE["IMAGE"])
    out = {}
    try:
        res = get(f"{media_id}/insights", {"metric": ",".join(wanted)})
        for row in res.get("data", []):
            vals = row.get("values") or [{}]
            out[row["name"]] = vals[0].get("value")
        return out
    except SystemExit:
        pass
    for m in wanted:                      # 整批失敗才退化成逐一要
        try:
            res = get(f"{media_id}/insights", {"metric": m})
            row = res["data"][0]
            out[m] = (row.get("values") or [{}])[0].get("value")
        except Exception:
            out[m] = None                 # 這個 metric 這篇不支援 → 留空
    return out


def first_line(caption):
    if not caption:
        return ""
    for line in caption.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--out", default="out")
    args = ap.parse_args()

    for var in ("IG_USER_ID", "IG_ACCESS_TOKEN"):
        if not os.environ.get(var):
            sys.exit(f"缺少環境變數 {var}")

    os.makedirs(args.out, exist_ok=True)
    media = fetch_media(os.environ["IG_USER_ID"], args.limit)
    print(f"取得 {len(media)} 則貼文，開始抓 insights…", file=sys.stderr)

    rows = []
    for i, m in enumerate(media, 1):
        mt = m.get("media_product_type") or m.get("media_type") or "IMAGE"
        ins = fetch_insights(m["id"], mt)
        rows.append({
            "序": i,
            "日期": (m.get("timestamp") or "")[:10],
            "類型": mt,
            "永久連結": m.get("permalink", ""),
            "觀看(views)": ins.get("views"),
            "觸及(reach)": ins.get("reach"),
            "分享(shares)": ins.get("shares"),
            "儲存(saved)": ins.get("saved"),
            "平均觀看時間(秒)": ins.get("ig_reels_avg_watch_time"),
            "新增追蹤(follows)": ins.get("follows"),
            "讚": ins.get("likes"),
            "留言": ins.get("comments"),
            "互動總數": ins.get("total_interactions"),
            "非追蹤者占比": "",
            "3秒留存": "",
            "開頭那句話": first_line(m.get("caption")),
            "產品/系列": "",
            "鞋款": "",
        })
        print(f"  {i}/{len(media)} {m.get('permalink','')}", file=sys.stderr)

    csv_path = os.path.join(args.out, "ig_posts.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in COLUMNS})

    md_path = os.path.join(args.out, "ig_posts.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("| " + " | ".join(COLUMNS) + " |\n")
        f.write("|" + "---|" * len(COLUMNS) + "\n")
        for r in rows:
            cells = ["" if r.get(k) is None else str(r.get(k)).replace("|", "\\|")
                     for k in COLUMNS]
            f.write("| " + " | ".join(cells) + " |\n")

    print(f"完成：{csv_path}\n      {md_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
