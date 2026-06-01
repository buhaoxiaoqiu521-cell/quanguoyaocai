#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Connection": "close",
    "Referer": "https://www.zyctd.com/",
}
HOTSPOT_CHANNELS = [
    {"code": "204", "kind": "产业观察"},
    {"code": "223", "kind": "政策解读"},
]
REQUEST_TIMEOUT = (10, 35)
RETRY_DELAYS = (1.5, 4.0, 8.0, 14.0)
DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})\s+\d{2}:\d{2}")
AUTHOR_RE = re.compile(r"作者[:：]\s*([^\s]+)")
DETAIL_SELECTORS = ("div.info-content", ".zx-info-detail .info-content")
COPYRIGHT_RE = re.compile(r"声明：本文是中药材天地网原创资讯.*$")
NOTICE_START_RE = re.compile(r"声\s*明[:：]\s*转载此文是出于传递更多信息之目的。?")
NOTICE_KEEP_RE = re.compile(
    r"(声\s*明[:：]\s*转载此文是出于传递更多信息之目的。?"
    r"\s*若有来源标注错误或侵犯了您的合法权益，请作者持权属证明与本网联系，我们将及时更正、删除，谢谢。)"
)
PREVIEW_LIMIT = 110


def clean_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def sleep_before_retry(attempt: int) -> None:
    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
    time.sleep(delay + random.uniform(0, 0.8))


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    allow_http_fallback: bool = False,
    **kwargs: Any,
) -> requests.Response:
    urls = [url]
    if allow_http_fallback and url.startswith("https://"):
        urls.append("http://" + url[len("https://") :])

    last_error: Exception | None = None
    for current_url in urls:
        for attempt in range(len(RETRY_DELAYS)):
            try:
                response = session.request(method, current_url, timeout=REQUEST_TIMEOUT, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt < len(RETRY_DELAYS) - 1:
                    sleep_before_retry(attempt)
        if last_error and not isinstance(last_error, (requests.exceptions.SSLError, requests.exceptions.ConnectionError)):
            break
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"请求失败：{url}")


def normalize_detail_text(text: str) -> str:
    value = clean_text(text)
    for marker in (
        "声明：本文是中药材天地网原创资讯",
        "关联品种",
        "最新评论",
        "文明上网理性发言",
        "发布评论",
    ):
        value = value.split(marker, 1)[0]
    value = COPYRIGHT_RE.sub("", value)
    notice_match = NOTICE_KEEP_RE.search(value)
    if notice_match:
        prefix = value[: notice_match.start()].rstrip()
        value = f"{prefix} {clean_text(notice_match.group(1))}".strip()
    elif NOTICE_START_RE.search(value):
        value = NOTICE_START_RE.split(value, 1)[0].strip()
    return clean_text(value)


def build_preview(text: str, fallback: str = "", limit: int = PREVIEW_LIMIT) -> str:
    value = normalize_detail_text(text) or clean_text(fallback)
    if len(value) <= limit:
        return value
    window = value[:limit]
    cut = max(window.rfind("。"), window.rfind("；"), window.rfind("！"), window.rfind("？"))
    if cut >= 36:
        return clean_text(window[: cut + 1])
    cut = max(window.rfind("，"), window.rfind(","), window.rfind(" "))
    if cut >= 36:
        return clean_text(window[:cut]) + "..."
    return clean_text(window) + "..."


def normalize_href(href: str) -> str:
    value = clean_text(href)
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("/"):
        return "https://www.zyctd.com" + value
    return value


def extract_detail(session: requests.Session, url: str) -> tuple[str, str]:
    href = normalize_href(url)
    if not href:
        return ("", "")
    try:
        response = request_with_retry(session, "GET", href, allow_http_fallback=href.startswith("https://www.zyctd.com/"))
    except Exception:
        return ("", "")

    soup = BeautifulSoup(response.text, "html.parser")
    detail_text = ""
    for selector in DETAIL_SELECTORS:
        node = soup.select_one(selector)
        if not node:
            continue
        text = normalize_detail_text(node.get_text(" ", strip=True))
        if len(text) >= 24:
            detail_text = text
            break

    published_date = ""
    for selector in (".zx-info-detail", ".info-title", "title"):
        node = soup.select_one(selector)
        if not node:
            continue
        text = clean_text(node.get_text(" ", strip=True))
        match = DATE_RE.search(text)
        if match:
            published_date = match.group(1)
            break

    return (detail_text, published_date)


def fetch_hotspots(limit: int, max_pages: int) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    channel_items: list[list[dict[str, str]]] = []
    seen_urls: set[str] = set()
    per_channel_limit = max(1, (limit + len(HOTSPOT_CHANNELS) - 1) // len(HOTSPOT_CHANNELS))
    with requests.Session() as session:
        session.headers.update(HEADERS)
        for channel in HOTSPOT_CHANNELS:
            code = channel["code"]
            kind = channel["kind"]
            current_items: list[dict[str, str]] = []
            for page in range(1, max_pages + 1):
                url = f"https://www.zyctd.com/zixun/{code}" if page == 1 else f"https://www.zyctd.com/zixun/{code}-{page}.html"
                response = request_with_retry(session, "GET", url, allow_http_fallback=True)
                soup = BeautifulSoup(response.text, "html.parser")
                boxes = soup.select("div.zixun-item-box")
                if not boxes:
                    break

                for box in boxes:
                    title_node = box.select_one("div.zixun-item-title")
                    desc_node = box.select_one("div.zixun-item-desc")
                    footer_node = box.select_one("div.zixun-item-footer")
                    link_node = box.select_one("div.zixun-item-title a")
                    title = clean_text(title_node.get_text(" ", strip=True) if title_node else "")
                    summary = clean_text(desc_node.get_text(" ", strip=True) if desc_node else "")
                    footer = clean_text(footer_node.get_text(" ", strip=True) if footer_node else "")
                    href = normalize_href(link_node.get("href", "") if link_node else "")
                    if not href or href in seen_urls:
                        continue
                    seen_urls.add(href)
                    detail_text, published_date = extract_detail(session, href)
                    author_match = AUTHOR_RE.search(footer)
                    source = clean_text(author_match.group(1) if author_match else "") or "中药材天地网"
                    date_text = published_date or footer.split(" ")[0]

                    current_items.append(
                        {
                            "date": clean_text(date_text),
                            "title": title,
                            "kind": kind,
                            "summary": build_preview(detail_text, fallback=summary),
                            "content_full": detail_text or summary,
                            "source": source,
                            "url": href,
                            "herb": "",
                            "location": "",
                        }
                    )
                    if len(current_items) >= per_channel_limit:
                        break
                if len(current_items) >= per_channel_limit:
                    break
            channel_items.append(current_items)

    for index in range(per_channel_limit):
        for current_items in channel_items:
            if index < len(current_items):
                items.append(current_items[index])
                if len(items) >= limit:
                    return items
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取中药材天地网行业热点栏目，输出网站可用 JSON")
    parser.add_argument("--limit", type=int, default=30, help="提取最近多少条热点，默认 30")
    parser.add_argument("--pages", type=int, default=6, help="最多抓取多少页列表，默认 6")
    parser.add_argument("--output", default="content/hotspots.json", help="输出 JSON 路径")
    args = parser.parse_args()

    records = fetch_hotspots(limit=max(1, args.limit), max_pages=max(1, args.pages))
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "output": str(output_path),
        "records": len(records),
        "latest_date": records[0]["date"] if records else "",
        "sources": dict(Counter(item["source"] for item in records)),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
