#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Connection": "close",
    "Referer": "https://www.yt1998.com/marketInfo--3.html",
    "X-Requested-With": "XMLHttpRequest",
}
ZY_HEADERS = {
    "User-Agent": UA["User-Agent"],
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Connection": "close",
    "Referer": "https://www.zyctd.com/",
}
YT_VERIFY_URL = "https://www.yt1998.com/ytw/yanzheng/yy.jsp"
YT_VERIFY_COOKIE = "zshcookiename"
REQUEST_TIMEOUT = (10, 35)
RETRY_DELAYS = (1.5, 4.0, 8.0, 14.0)
MARKET_TARGETS = {
    "1": "亳州",
    "2": "安国",
    "3": "玉林",
}
ZY_MARKET_TARGETS = {
    "安国": "130699",
    "亳州": "341699",
    "玉林": "450999",
    "成都": "510199",
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


def clean_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_published_at(value: str, fallback_date: str) -> str:
    text = clean_text(value)
    if not text:
        return f"{clean_text(fallback_date)} 00:00:00" if clean_text(fallback_date) else ""
    if " " in text:
        return text
    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", text):
        return f"{text} 00:00:00"
    return text


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
        response = request_with_retry(
            session,
            "GET",
            href,
            allow_http_fallback=href.startswith("https://www.zyctd.com/"),
        )
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
    last_error = ""
    for attempt in range(4):
        verify_response = request_with_retry(
            session,
            "POST",
            YT_VERIFY_URL,
            data={"url": target_path},
        )
        uuid = ""
        try:
            payload = verify_response.json()
            uuid = clean_text(payload.get("uuid"))
        except Exception:
            match = re.search(r'"uuid"\s*:\s*"([^"]+)"', verify_response.text)
            if match:
                uuid = clean_text(match.group(1))
            else:
                last_error = clean_text(verify_response.text[:120])
        if uuid:
            session.cookies.set(YT_VERIFY_COOKIE, uuid, domain="www.yt1998.com", path="/")
            return
        sleep_before_retry(attempt)
    raise RuntimeError(f"药通网验证未返回 uuid。响应片段：{last_error or 'empty'}")


def choose_target_dates(items: list[dict[str, Any]], target_date: str) -> list[str]:
    dates = [clean_text(item.get("date")) for item in items if clean_text(item.get("date"))]
    if target_date in dates:
        return [target_date]
    return [dates[0]] if dates else []


def fetch_yt_market(scid: str, target_date: str, max_pages: int = 5, page_size: int = 20) -> tuple[list[str], list[dict[str, str]]]:
    url = "https://www.yt1998.com/ytw/second/marketMgr/query.jsp"
    payload_items: list[dict[str, Any]] = []

    with requests.Session() as session:
        session.headers.update(UA)
        ensure_yt_verified(session)
        for page in range(max_pages):
            data = None
            last_error: Exception | None = None
            for attempt in range(3):
                response = request_with_retry(
                    session,
                    "POST",
                    url,
                    data={
                        "scid": scid,
                        "lmid": "3",
                        "ycnam": "",
                        "times": scid,
                        "pageIndex": page,
                        "pageSize": page_size,
                    },
                )
                try:
                    data = response.json().get("data", [])
                    break
                except Exception as exc:
                    last_error = exc
                    ensure_yt_verified(session)
                    sleep_before_retry(attempt)
            if data is None:
                if payload_items:
                    print(
                        f"[warn] 药通网市场接口异常，保留已抓到的数据（scid={scid}, page={page}）：{last_error}",
                        file=sys.stderr,
                    )
                    break
                raise RuntimeError(f"药通网市场接口返回了非 JSON 内容（scid={scid}, page={page}）。") from last_error
            if not data:
                break
            payload_items.extend(data)
            item_dates = [clean_text(item.get("dtm")).split(" ")[0] for item in data if clean_text(item.get("dtm"))]
            if item_dates and all(date < target_date for date in item_dates):
                break

    chosen_dates = choose_target_dates(
        [{"date": clean_text(item.get("dtm")).split(" ")[0]} for item in payload_items],
        target_date,
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
                "published_at": normalize_published_at(item.get("dtm", ""), item_date),
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


def fetch_zy_market(target_date: str, max_pages: int = 20) -> tuple[dict[str, list[str]], list[dict[str, str]]]:
    parsed_items: list[dict[str, str]] = []

    with requests.Session() as session:
        session.headers.update(ZY_HEADERS)
        for market_name, market_code in ZY_MARKET_TARGETS.items():
            market_items_before = len(parsed_items)
            for page in range(1, max_pages + 1):
                url = f"https://www.zyctd.com/zixun/200/{market_code}-{page}.html"
                response = None
                last_error: Exception | None = None
                for attempt in range(3):
                    try:
                        response = request_with_retry(session, "GET", url, allow_http_fallback=True)
                        break
                    except Exception as exc:
                        last_error = exc
                        if attempt < 2:
                            sleep_before_retry(attempt)
                if response is None:
                    if len(parsed_items) > market_items_before:
                        print(
                            f"[warn] 中药材天地网{market_name}市场列表异常，保留已抓到的数据（page={page}）：{last_error}",
                            file=sys.stderr,
                        )
                        break
                    raise RuntimeError(f"中药材天地网{market_name}市场列表抓取失败（page={page}）。") from last_error
                soup = BeautifulSoup(response.text, "html.parser")
                boxes = soup.select("div.zixun-item-box")
                if not boxes:
                    break
                box_dates: list[str] = []
                for box in boxes:
                    title_node = box.select_one("div.zixun-item-title")
                    desc_node = box.select_one("div.zixun-item-desc")
                    footer_node = box.select_one("div.zixun-item-footer")
                    link_node = box.select_one("div.zixun-item-title a")
                    summary = clean_text(desc_node.get_text(" ", strip=True) if desc_node else "")
                    footer = clean_text(footer_node.get_text(" ", strip=True) if footer_node else "")
                    href = clean_text(link_node.get("href", "") if link_node else "")
                    if href.startswith("//"):
                        href = "https:" + href
                    elif href.startswith("/"):
                        href = "https://www.zyctd.com" + href

                    date = footer.split(" ")[0] if footer else ""
                    if date:
                        box_dates.append(date)
                    herb_match = FOOTER_HERB_RE.search(footer)
                    detail_text, published_date = extract_zy_detail_payload(session, href)
                    content_text = detail_text or summary
                    price_value, price_label = extract_price(content_text)
                    price_points = extract_price_points(content_text)
                    parsed_items.append(
                        {
                            "date": published_date or date,
                            "published_at": normalize_published_at(published_date, published_date or date),
                            "herb": clean_text(herb_match.group(1) if herb_match else ""),
                            "spec": "",
                            "unit": "元/kg",
                            "market": market_name,
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

                if box_dates and all(date < target_date for date in box_dates if date):
                    break

    chosen_dates: dict[str, list[str]] = {}
    for market in list(MARKET_TARGETS.values()) + [name for name in ZY_MARKET_TARGETS if name not in MARKET_TARGETS.values()]:
        items = [item for item in parsed_items if item["market"] == market]
        chosen_dates[market] = choose_target_dates(items, target_date)

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
    output.sort(
        key=lambda item: (
            normalize_published_at(item.get("published_at", ""), item.get("date", "")),
            clean_text(item.get("date")),
            clean_text(item.get("market")),
            clean_text(item.get("herb")),
        ),
        reverse=True,
    )
    return output


def load_existing_records(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


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
        "--replace-output",
        action="store_true",
        help="覆盖输出文件，不保留历史市场记录",
    )
    args = parser.parse_args()

    yt_records: list[dict[str, str]] = []
    yt_dates: dict[str, list[str]] = {}
    yt_source_ok = False
    for scid, market_name in MARKET_TARGETS.items():
        try:
            chosen_dates, records = fetch_yt_market(scid, args.target_date)
            yt_dates[market_name] = chosen_dates
            yt_records.extend(records)
            yt_source_ok = True
        except Exception as exc:
            yt_dates[market_name] = []
            print(f"[warn] 药通网市场抓取失败（{market_name}）：{exc}", file=sys.stderr)

    zy_source_ok = False
    zy_dates: dict[str, list[str]] = {market: [] for market in MARKET_TARGETS.values()}
    zy_records: list[dict[str, str]] = []
    try:
        zy_dates, zy_records = fetch_zy_market(args.target_date)
        zy_source_ok = True
    except Exception as exc:
        print(f"[warn] 中药材天地网市场抓取失败：{exc}", file=sys.stderr)

    if not yt_source_ok and not zy_source_ok:
        raise RuntimeError("市场源站全部抓取失败。")

    output_path = Path(args.output).expanduser().resolve()
    existing_records = [] if args.replace_output else load_existing_records(output_path)
    new_records = dedupe_records(yt_records + zy_records)
    records = dedupe_records(new_records + existing_records)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    source_breakdown = Counter(item["source"] for item in new_records)
    market_breakdown = Counter(item["market"] for item in new_records)
    summary_markets = list(MARKET_TARGETS.values()) + [name for name in ZY_MARKET_TARGETS if name not in MARKET_TARGETS.values()]
    summary = {
        "target_date": args.target_date,
        "output": str(output_path),
        "new_records": len(new_records),
        "records": len(records),
        "markets": {market: market_breakdown.get(market, 0) for market in summary_markets},
        "sources": dict(source_breakdown),
        "yt_dates": yt_dates,
        "zy_dates": zy_dates,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
