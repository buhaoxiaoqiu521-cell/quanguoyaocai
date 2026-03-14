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
MARKET_TARGETS = {
    "1": "亳州",
    "2": "安国",
    "3": "玉林",
}
PRICE_RANGE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:-|~|至|到)\s*(\d+(?:\.\d+)?)\s*元(?:/公斤|/千克|每公斤|每千克|左右|上下|之间)?"
)
PRICE_SINGLE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*元(?:/公斤|/千克|每公斤|每千克|左右|上下|之间)?")
FOOTER_MARKET_RE = re.compile(r"作者[:：]\s*([^\s]+市场)")
FOOTER_HERB_RE = re.compile(r"品种[:：]\s*([^\s]+)")
CLAUSE_SPLIT_RE = re.compile(r"[；;。]")
PHRASE_SPLIT_RE = re.compile(r"[，,]")
PRICE_SUFFIX_RE = re.compile(r"(售价|售价格?|要价|价格在|价格|价在|价位在|价位|报价在|报价|成交价|货价)$")
PRICE_PREFIX_RE = re.compile(r"^(现阶段|近阶段|目前|当前|现)")


def clean_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_price(text: str) -> tuple[str, str]:
    value = clean_text(text)
    if not value:
        return ("", "")
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
        parts = [clean_text(part) for part in PHRASE_SPLIT_RE.split(clause) if clean_text(part)]
        for part in parts:
            range_match = PRICE_RANGE_RE.search(part)
            single_match = PRICE_SINGLE_RE.search(part)
            match = range_match or single_match
            if not match:
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


def choose_target_date(items: list[dict[str, Any]], target_date: str) -> str:
    dates = sorted({clean_text(item.get("date")) for item in items if clean_text(item.get("date"))}, reverse=True)
    if target_date in dates:
        return target_date
    return dates[0] if dates else ""


def fetch_yt_market(scid: str, target_date: str, max_pages: int = 5, page_size: int = 20) -> tuple[str, list[dict[str, str]]]:
    url = "https://www.yt1998.com/ytw/second/marketMgr/query.jsp"
    payload_items: list[dict[str, Any]] = []

    with requests.Session() as session:
        session.headers.update(UA)
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
            data = response.json().get("data", [])
            if not data:
                break
            payload_items.extend(data)
            item_dates = [clean_text(item.get("dtm")).split(" ")[0] for item in data if clean_text(item.get("dtm"))]
            if item_dates and all(date < target_date for date in item_dates):
                break

    chosen_date = choose_target_date(
        [{"date": clean_text(item.get("dtm")).split(" ")[0]} for item in payload_items],
        target_date,
    )
    records: list[dict[str, str]] = []

    for item in payload_items:
        item_date = clean_text(item.get("dtm")).split(" ")[0]
        if item_date != chosen_date:
            continue
        today_price, price_label = extract_price(item.get("cont"))
        price_points = extract_price_points(item.get("cont"))
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
                "summary": clean_text(item.get("cont")),
                "price_label": price_label,
                "price_points": price_points,
            }
        )

    return chosen_date, records


def fetch_zy_market(target_date: str, max_pages: int = 5) -> tuple[dict[str, str], list[dict[str, str]]]:
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
                price_value, price_label = extract_price(summary)
                price_points = extract_price_points(summary)
                parsed_items.append(
                    {
                        "date": date,
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
                        "summary": summary,
                        "price_label": price_label,
                        "price_points": price_points,
                    }
                )

            box_dates = [clean_text(box.select_one("div.zixun-item-footer").get_text(" ", strip=True)).split(" ")[0] for box in boxes if box.select_one("div.zixun-item-footer")]
            if box_dates and all(date < target_date for date in box_dates if date):
                break

    chosen_dates: dict[str, str] = {}
    for market in MARKET_TARGETS.values():
        items = [item for item in parsed_items if item["market"] == market]
        chosen_dates[market] = choose_target_date(items, target_date)

    records = [
        item
        for item in parsed_items
        if item["market"] in chosen_dates and item["date"] == chosen_dates[item["market"]]
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
    args = parser.parse_args()

    yt_records: list[dict[str, str]] = []
    yt_dates: dict[str, str] = {}
    for scid, market_name in MARKET_TARGETS.items():
        chosen_date, records = fetch_yt_market(scid, args.target_date)
        yt_dates[market_name] = chosen_date
        yt_records.extend(records)

    zy_dates, zy_records = fetch_zy_market(args.target_date)
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
