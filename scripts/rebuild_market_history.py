#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any
import time

import requests
from bs4 import BeautifulSoup


UA = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.yt1998.com/marketInfo--3.html",
    "X-Requested-With": "XMLHttpRequest",
}
ZY_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.zyctd.com/",
}
MARKET_TARGETS = {
    "1": "亳州",
    "2": "安国",
    "3": "玉林",
}


def clean_text(value: Any) -> str:
    import re

    text = str(value or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_market(value: str) -> str:
    text = clean_text(value).replace("药市", "市场")
    for target in MARKET_TARGETS.values():
        if target in text:
            return target
    return text.replace("市场", "")


def dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str, str]] = set()
    output: list[dict[str, Any]] = []
    for item in records:
        key = (
            clean_text(item.get("date")),
            clean_text(item.get("market")),
            clean_text(item.get("herb")),
            clean_text(item.get("source")),
            clean_text(item.get("summary")),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    output.sort(key=lambda item: (clean_text(item.get("date")), clean_text(item.get("market")), clean_text(item.get("herb"))), reverse=True)
    return output


def fetch_yt_history(max_pages: int, page_size: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    url = "https://www.yt1998.com/ytw/second/marketMgr/query.jsp"
    with requests.Session() as session:
        session.headers.update(UA)
        for scid, market_name in MARKET_TARGETS.items():
            for page in range(max_pages):
                data: list[dict[str, Any]] | None = None
                for attempt in range(3):
                    response = session.post(
                        url,
                        data={
                            "scid": scid,
                            "lmid": "3",
                            "ycnam": "",
                            "times": scid,
                            "pageIndex": page,
                            "pageSize": page_size,
                        },
                        timeout=20,
                    )
                    response.raise_for_status()
                    try:
                        data = response.json().get("data", [])
                        break
                    except Exception:
                        if attempt == 2:
                            data = []
                        else:
                            time.sleep(1.0 + attempt)
                if data is None:
                    data = []
                if not data:
                    break
                for item in data:
                    detail_text = clean_text(item.get("cont"))
                    records.append(
                        {
                            "date": clean_text(item.get("dtm")).split(" ")[0],
                            "herb": clean_text(item.get("ycnam")),
                            "spec": "",
                            "unit": "元/kg",
                            "market": market_name,
                            "location": "",
                            "today_price": "",
                            "yesterday_price": "",
                            "delta_amount": "",
                            "delta_rate": "",
                            "source": "药通网",
                            "url": f"https://www.yt1998.com/hqzx/{clean_text(item.get('accode'))}_{clean_text(item.get('scid'))}.html",
                            "summary": detail_text,
                            "content_full": detail_text,
                            "price_label": "",
                            "price_points": [],
                        }
                    )
    return records


def fetch_zy_detail_payload(session: requests.Session, url: str) -> tuple[str, str]:
    import re

    href = clean_text(url)
    if not href:
        return ("", "")
    try:
        response = session.get(href, timeout=20)
        response.raise_for_status()
    except Exception:
        return ("", "")
    soup = BeautifulSoup(response.text, "html.parser")
    published_date = ""
    detail_date_re = re.compile(r"(20\d{2}-\d{2}-\d{2})\s+\d{2}:\d{2}")
    for selector in (".zx-info-detail", ".info-title", "title"):
        node = soup.select_one(selector)
        if not node:
            continue
        text = clean_text(node.get_text(" ", strip=True))
        match = detail_date_re.search(text)
        if match:
            published_date = match.group(1)
            break
    detail_text = ""
    for selector in ("div.info-content", ".zx-info-detail .info-content"):
        node = soup.select_one(selector)
        if not node:
            continue
        text = clean_text(node.get_text(" ", strip=True))
        for marker in ("声明：本文是中药材天地网原创资讯", "关联品种", "最新评论", "文明上网理性发言", "发布评论"):
            text = text.split(marker, 1)[0]
        if len(text) >= 24:
            detail_text = text
            break
    return detail_text, published_date


def fetch_zy_history(max_pages: int) -> list[dict[str, Any]]:
    import re

    footer_market_re = re.compile(r"作者[:：]\s*([^\s]+市场)")
    footer_herb_re = re.compile(r"品种[:：]\s*([^\s]+)")

    records: list[dict[str, Any]] = []
    with requests.Session() as session:
        session.headers.update(ZY_HEADERS)
        for page in range(1, max_pages + 1):
            url = "https://www.zyctd.com/zixun/200-1.html" if page == 1 else f"https://www.zyctd.com/zixun/200-{page}.html"
            response = session.get(url, timeout=20)
            response.raise_for_status()
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
                href = clean_text(link_node.get("href", "") if link_node else "")
                if href.startswith("//"):
                    href = "https:" + href
                elif href.startswith("/"):
                    href = "https://www.zyctd.com" + href

                market_match = footer_market_re.search(footer)
                herb_match = footer_herb_re.search(footer)
                market = normalize_market(market_match.group(1) if market_match else title)
                if market not in MARKET_TARGETS.values():
                    continue
                detail_text, published_date = fetch_zy_detail_payload(session, href)
                content_text = detail_text or summary
                date_text = published_date or footer.split(" ")[0]
                records.append(
                    {
                        "date": clean_text(date_text),
                        "herb": clean_text(herb_match.group(1) if herb_match else ""),
                        "spec": "",
                        "unit": "元/kg",
                        "market": market,
                        "location": "",
                        "today_price": "",
                        "yesterday_price": "",
                        "delta_amount": "",
                        "delta_rate": "",
                        "source": "中药材天地网",
                        "url": href,
                        "summary": content_text,
                        "content_full": content_text,
                        "price_label": "",
                        "price_points": [],
                    }
                )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="重抓市场行情历史深度并输出网站可用 JSON")
    parser.add_argument("--output", default="content/market_updates.json", help="输出 JSON 路径")
    parser.add_argument("--yt-pages", type=int, default=60, help="药通网每个市场最大抓取页数")
    parser.add_argument("--yt-page-size", type=int, default=20, help="药通网每页条数")
    parser.add_argument("--zy-pages", type=int, default=24, help="天地网市场快讯最大抓取页数")
    args = parser.parse_args()

    records = dedupe_records(fetch_yt_history(args.yt_pages, args.yt_page_size) + fetch_zy_history(args.zy_pages))
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "output": str(output_path),
        "records": len(records),
        "markets": dict(Counter(item["market"] for item in records)),
        "sources": dict(Counter(item["source"] for item in records)),
        "dates": sorted({item["date"] for item in records if item.get("date")}, reverse=True)[:20],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
