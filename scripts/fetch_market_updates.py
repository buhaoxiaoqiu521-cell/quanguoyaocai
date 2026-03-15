#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

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
YT_VERIFY_URL = "https://www.yt1998.com/ytw/yanzheng/yy.jsp"
YT_VERIFY_COOKIE = "zshcookiename"
MARKET_TARGETS = {
    "1": "亳州",
    "2": "安国",
    "3": "玉林",
}
PRICE_RANGE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:-|~|至|到)\s*(\d+(?:\.\d+)?)\s*(?:元|块)(?:/公斤|/千克|每公斤|每千克|左右|上下|之间)?"
)
PRICE_SINGLE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:元|块)(?:/公斤|/千克|每公斤|每千克|左右|上下|之间)?")
FOOTER_MARKET_RE = re.compile(r"作者[:：]\s*([^\s]+市场)")
FOOTER_HERB_RE = re.compile(r"品种[:：]\s*([^\s]+)")
CLAUSE_SPLIT_RE = re.compile(r"[；;。]")
PHRASE_SPLIT_RE = re.compile(r"[，,]")
PRICE_SUFFIX_RE = re.compile(r"(售价|售价格?|要价|价格在|价格|价在|价位在|价位|报价在|报价|成交价|货价)$")
PRICE_PREFIX_RE = re.compile(r"^(现阶段|近阶段|目前|当前|现)")
DETAIL_PREFIX_RE = re.compile(r"^【[^】]+】")
COPYRIGHT_RE = re.compile(r"声明：本文是中药材天地网原创资讯.*$")
DETAIL_DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})\s+\d{2}:\d{2}")
ENUMERATION_SPLIT_RE = re.compile(r"(?=[①②③④⑤⑥⑦⑧⑨⑩])")
LIST_MARKER_RE = re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩\d]+[\.、\)]?\s*")
DETAIL_SELECTORS = ("div.info-content", ".zx-info-detail .info-content")
PREVIEW_LIMIT = 140


def clean_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_detail_text(text: str) -> str:
    value = clean_text(text)
    value = DETAIL_PREFIX_RE.sub("", value)
    for marker in ("声明：本文是中药材天地网原创资讯", "关联品种", "最新评论", "文明上网理性发言", "发布评论"):
        value = value.split(marker, 1)[0]
    value = COPYRIGHT_RE.sub("", value)
    return clean_text(value)


def build_preview_text(text: str, fallback: str = "", limit: int = PREVIEW_LIMIT) -> str:
    value = normalize_detail_text(text) or clean_text(fallback)
    if len(value) <= limit:
        return value
    window = value[:limit]
    cut = max(window.rfind("。"), window.rfind("；"), window.rfind("！"), window.rfind("？"))
    if cut >= 32:
        return clean_text(window[: cut + 1])
    cut = max(window.rfind("，"), window.rfind(","), window.rfind(" "))
    if cut >= 32:
        return clean_text(window[:cut]) + "..."
    return clean_text(window) + "..."


def extract_zy_detail_payload(session: requests.Session, url: str) -> tuple[str, str]:
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
    for selector in (".zx-info-detail", ".info-title", "title"):
        node = soup.select_one(selector)
        if not node:
            continue
        text = clean_text(node.get_text(" ", strip=True))
        match = DETAIL_DATE_RE.search(text)
        if match:
            published_date = match.group(1)
            break
    detail_text = ""
    for selector in DETAIL_SELECTORS:
        node = soup.select_one(selector)
        if not node:
            continue
        text = normalize_detail_text(node.get_text(" ", strip=True))
        if len(text) >= 24:
            detail_text = text
            break
    return (detail_text, published_date)


def extract_price(text: str) -> tuple[str, str]:
    value = clean_text(text)
    if not value:
        return ("", "")
    price_points = extract_price_points(value)
    if price_points:
        price = clean_text(price_points[0]["price"])
        first_number = clean_text(price.split(" ")[0]).split("-")[0]
        return (first_number, price)
    range_match = PRICE_RANGE_RE.search(value)
    if range_match:
        start, end = range_match.groups()
        return (start, f"{start}-{end} 元/kg")
    single_match = PRICE_SINGLE_RE.search(value)
    if single_match:
        price = single_match.group(1)
        return (price, f"{price} 元/kg")
    return ("", "")


def clean_price_label(text: str) -> str:
    label = clean_text(text)
    label = LIST_MARKER_RE.sub("", label)
    label = PRICE_PREFIX_RE.sub("", label)
    label = PRICE_SUFFIX_RE.sub("", label)
    label = re.sub(r"[：:、，,；;。]+$", "", label)
    label = clean_text(label)
    return label or "主流货"


def extract_price_points(text: str) -> list[dict[str, str]]:
    value = clean_text(text)
    if not value:
        return []

    points: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for clause in CLAUSE_SPLIT_RE.split(value):
        clause = clean_text(clause)
        if not clause:
            continue
        segments = [clean_text(segment) for segment in ENUMERATION_SPLIT_RE.split(clause) if clean_text(segment)] or [clause]
        for segment in segments:
            parts = [clean_text(part) for part in PHRASE_SPLIT_RE.split(segment) if clean_text(part)]
            candidates = [segment] + [part for part in parts if part != segment]
            for part in candidates:
                range_match = PRICE_RANGE_RE.search(part)
                single_match = PRICE_SINGLE_RE.search(part)
                match = range_match or single_match
                if not match:
                    continue
                if "斤" in part[match.end() : match.end() + 4]:
                    continue
                label = clean_price_label(part[:match.start()])
                if range_match:
                    start, end = range_match.groups()
                    price = f"{start}-{end} 元/kg"
                else:
                    price = f"{single_match.group(1)} 元/kg"
                key = (label, price)
                if key in seen:
                    continue
                seen.add(key)
                points.append({"label": label, "price": price})
    return points


def normalize_market(value: str) -> str:
    text = clean_text(value).replace("药市", "市场")
    for target in MARKET_TARGETS.values():
        if target in text:
            return target
    return text.replace("市场", "")


def ensure_yt_verified(session: requests.Session, target_path: str = "/ytw/second/marketMgr/query.jsp") -> None:
    verify_response = session.post(
        YT_VERIFY_URL,
        data={"url": target_path},
        timeout=20,
    )
    verify_response.raise_for_status()
    payload = verify_response.json()
    uuid = clean_text(payload.get("uuid"))
    if not uuid:
        raise RuntimeError("药通网验证未返回 uuid。")
    session.cookies.set(YT_VERIFY_COOKIE, uuid, domain="www.yt1998.com", path="/")


def choose_target_dates(items: list[dict[str, Any]], target_date: str, days: int) -> list[str]:
    filtered_dates = sorted(
        {
            clean_text(item.get("date"))
            for item in items
            if clean_text(item.get("date")) and clean_text(item.get("date")) <= target_date
        },
        reverse=True,
    )
    if not filtered_dates:
        filtered_dates = sorted({clean_text(item.get("date")) for item in items if clean_text(item.get("date"))}, reverse=True)
    return filtered_dates[:days]


def fetch_yt_market(scid: str, target_date: str, days: int = 5, max_pages: int = 5, page_size: int = 20) -> tuple[list[str], list[dict[str, str]]]:
    url = "https://www.yt1998.com/ytw/second/marketMgr/query.jsp"
    payload_items: list[dict[str, Any]] = []

    with requests.Session() as session:
        session.headers.update(UA)
        ensure_yt_verified(session)
        for page in range(max_pages):
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
            except Exception as exc:
                raise RuntimeError(f"药通网市场接口返回了非 JSON 内容（scid={scid}, page={page}）。") from exc
            if not data:
                break
            payload_items.extend(data)
            item_dates = [clean_text(item.get("dtm")).split(" ")[0] for item in data if clean_text(item.get("dtm"))]
            if item_dates and all(date < target_date for date in item_dates):
                break

    chosen_dates = choose_target_dates(
        [{"date": clean_text(item.get("dtm")).split(" ")[0]} for item in payload_items],
        target_date,
        days,
    )
    records: list[dict[str, str]] = []

    for item in payload_items:
        item_date = clean_text(item.get("dtm")).split(" ")[0]
        if item_date not in chosen_dates:
            continue
        detail_text = clean_text(item.get("cont"))
        today_price, price_label = extract_price(detail_text)
        price_points = extract_price_points(detail_text)
        records.append(
            {
                "date": item_date,
                "herb": clean_text(item.get("ycnam")),
                "spec": "",
                "unit": "元/kg",
                "market": normalize_market(item.get("market")),
                "location": "",
                "today_price": today_price,
                "yesterday_price": "",
                "delta_amount": "",
                "delta_rate": "",
                "source": "药通网",
                "url": f"https://www.yt1998.com/hqzx/{clean_text(item.get('accode'))}_{clean_text(item.get('scid'))}.html",
                "summary": build_preview_text(detail_text, fallback=item.get("cont")),
                "content_full": detail_text,
                "price_label": price_label,
                "price_points": price_points,
            }
        )

    return chosen_dates, records


def fetch_zy_market(target_date: str, days: int = 5, max_pages: int = 20) -> tuple[dict[str, list[str]], list[dict[str, str]]]:
    parsed_items: list[dict[str, str]] = []

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

                date = footer.split(" ")[0] if footer else ""
                market_match = FOOTER_MARKET_RE.search(footer)
                herb_match = FOOTER_HERB_RE.search(footer)
                market = normalize_market(market_match.group(1) if market_match else title)
                if market not in MARKET_TARGETS.values():
                    continue
                detail_text, published_date = extract_zy_detail_payload(session, href)
                content_text = detail_text or summary
                price_value, price_label = extract_price(content_text)
                price_points = extract_price_points(content_text)
                parsed_items.append(
                    {
                        "date": published_date or date,
                        "herb": clean_text(herb_match.group(1) if herb_match else ""),
                        "spec": "",
                        "unit": "元/kg",
                        "market": market,
                        "location": "",
                        "today_price": price_value,
                        "yesterday_price": "",
                        "delta_amount": "",
                        "delta_rate": "",
                        "source": "中药材天地网",
                        "url": href,
                        "summary": build_preview_text(content_text, fallback=summary),
                        "content_full": content_text,
                        "price_label": price_label,
                        "price_points": price_points,
                    }
                )

            box_dates = [clean_text(box.select_one("div.zixun-item-footer").get_text(" ", strip=True)).split(" ")[0] for box in boxes if box.select_one("div.zixun-item-footer")]
            if box_dates and all(date < target_date for date in box_dates if date):
                break

    chosen_dates: dict[str, list[str]] = {}
    for market in MARKET_TARGETS.values():
        items = [item for item in parsed_items if item["market"] == market]
        chosen_dates[market] = choose_target_dates(items, target_date, days)

    records = [
        item
        for item in parsed_items
        if item["market"] in chosen_dates and item["date"] in chosen_dates[item["market"]]
    ]
    return chosen_dates, records


def dedupe_records(records: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str, str, str]] = set()
    output: list[dict[str, str]] = []
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
    output.sort(key=lambda item: (item["date"], item["market"], item["herb"]), reverse=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取药通网 + 中药材天地网市场行情，输出网站可用 JSON")
    parser.add_argument(
        "--target-date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="目标日期，默认今天；若某市场当天没有数据，则自动回退到该市场最近有效日期",
    )
    parser.add_argument(
        "--output",
        default="content/market_updates.json",
        help="输出 JSON 路径",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=5,
        help="保留最近几日的市场行情，默认 5 日",
    )
    args = parser.parse_args()

    yt_records: list[dict[str, str]] = []
    yt_dates: dict[str, list[str]] = {}
    for scid, market_name in MARKET_TARGETS.items():
        chosen_dates, records = fetch_yt_market(scid, args.target_date, days=args.days)
        yt_dates[market_name] = chosen_dates
        yt_records.extend(records)

    zy_dates, zy_records = fetch_zy_market(args.target_date, days=args.days)
    records = dedupe_records(yt_records + zy_records)

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    source_breakdown = Counter(item["source"] for item in records)
    market_breakdown = Counter(item["market"] for item in records)
    summary = {
        "target_date": args.target_date,
        "output": str(output_path),
        "records": len(records),
        "markets": {market: market_breakdown.get(market, 0) for market in MARKET_TARGETS.values()},
        "sources": dict(source_breakdown),
        "yt_dates": yt_dates,
        "zy_dates": zy_dates,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
