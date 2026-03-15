#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zipfile import ZipFile


SHEET_NAME = "报价录入"
COLS = list("ABCDEFGHIJKLM")
MARKET_TARGETS = ["亳州", "安国", "玉林"]
UP_KEYWORDS = ("上涨", "上扬", "走快", "畅快", "走畅", "上浮", "寻货", "走动良好", "偏强")
STEADY_KEYWORDS = ("平稳", "价稳", "稳定", "持稳", "正常走动", "正常走销", "波动不大", "延续")
DOWN_KEYWORDS = ("走缓", "走慢", "走动不快", "交易不畅", "不畅", "观望", "疲软", "货源充足")
XML_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
YT_QUERY_URL = "https://www.yt1998.com/ytw/second/marketMgr/query.jsp"
YT_HEADERS = {"User-Agent": "Mozilla/5.0"}
PRICE_RANGE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:-|~|至|到)\s*(\d+(?:\.\d+)?)\s*(?:元|块)(?:/公斤|/千克|每公斤|每千克|左右|上下|之间)?"
)
PRICE_SINGLE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:元|块)(?:/公斤|/千克|每公斤|每千克|左右|上下|之间)?")
CLAUSE_SPLIT_RE = re.compile(r"[；;。]")
PHRASE_SPLIT_RE = re.compile(r"[，,]")
PRICE_SUFFIX_RE = re.compile(r"(售价为|收购价格?|收购价|售价|售价格?|要价|多要|少要|要|价格维持在|价格维持|价格为|价格在|价格|价在|价位在|价位|报价在|报价|成交价|货价)$")
PRICE_PREFIX_RE = re.compile(r"^(现阶段|近阶段|目前|当前|现)")
INVALID_PRICE_LABEL_RE = re.compile(
    r"(回调|上调|下调|上涨|下滑|下降|下跌|反弹|略跌|显跌|显滑|相比昨日|较昨日|交易走势|上市量|成交约|气温|天气|湿度|体感|能见度|空气质量|浏览|评论|作者|分享|昨前天|昨天|前日)"
)
GENERIC_PRICE_LABEL_RE = re.compile(r"^(近期|目前|当前|现阶段|近阶段|现|价格|售价|货价|近期价格|当前价格|目前价格|本地|产地|现货|新货)$")
CHANGE_ONLY_PRICE_RE = re.compile(
    r"(?:(?:价格|行情)(?:相比昨日|较昨日)?|相比昨日|较昨日)?(?:回调|上调|下调|上涨|下滑|下降|下跌|反弹)"
    r"\s*\d+(?:\.\d+)?(?:\s*(?:-|~|至|到)\s*\d+(?:\.\d+)?)?\s*(?:元|块)"
)
LOCATION_SPLIT_RE = re.compile(r"(?:省|市|州|县|区|旗|镇|乡|村|口岸|地区|盟)")
NOISE_LOCATION_RE = re.compile(r"^\d{4}年(?:\d{1,2}(?:月(?:\d{1,2}日)?)?)?$|^\d{1,2}月(?:\d{1,2}日)?$|^星期[一二三四五六日天]$")
ENUMERATION_SPLIT_RE = re.compile(r"(?=[①②③④⑤⑥⑦⑧⑨⑩])")
LIST_MARKER_RE = re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩\d]+[\.、\)]?\s*")
TAIL_SPEC_RE = re.compile(
    r"([一-龥A-Za-z0-9%./+\-]{2,24}"
    r"(?:统货|饮片货|药厂货|选装货|净货|毛草|鲜货|鲜果|切片货|对开货|圆果货|圆果|包检货|小肉货|色青货|装货|货|片|丝|个|果|穗|枝|壳|仁|草|皮|叶|花|根|段|头|条|连))$"
)
NOISY_LABEL_RE = re.compile(r"(走动|行情|市场|货源|商家|近期|近日|目前|当前|价格|售价|报价|要价|多要|可供|库存|关注|稳定|平稳|疲软|走销|交易|略有|继续|依然|产新)")
GENERIC_PRICE_LABELS = {"主流报价", "主流货", "主流"}
PROVINCE_PREFIXES = sorted(
    [
        "内蒙古", "黑龙江",
        "北京", "天津", "上海", "重庆",
        "河北", "山西", "辽宁", "吉林", "江苏", "浙江", "安徽", "福建", "江西", "山东",
        "河南", "湖北", "湖南", "广东", "广西", "海南", "四川", "贵州", "云南", "西藏",
        "陕西", "甘肃", "青海", "宁夏", "新疆", "香港", "澳门", "台湾",
    ],
    key=len,
    reverse=True,
)


@dataclass
class WorkbookRecord:
    date: str
    herb: str
    spec: str
    unit: str
    market: str
    location: str
    today_price: str
    yesterday_price: str
    delta_amount: str
    delta_rate: str
    source: str
    url: str
    summary: str
    content_full: str = ""
    price_label: str = ""
    price_points: list[dict[str, str]] | None = None


def clean_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_number(value: str) -> float | None:
    text = clean_text(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def format_number(value: float | None) -> str:
    if value is None:
        return ""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def format_price(value: str, unit: str) -> str:
    number = parse_number(value)
    if number is None:
        return ""
    unit_text = clean_text(unit) or "元/kg"
    return f"{format_number(number)} {unit_text}"


def normalize_source_url(source: str, url: str) -> str:
    source_text = clean_text(source)
    url_text = clean_text(url)
    if not url_text:
        return ""
    if source_text == "药通网" and "/ytw/second/marketMgr/detail.jsp" in url_text:
        # 药通网这类旧 detail.jsp 链接已经失效，前端不再展示 404 按钮
        return ""
    return url_text


def normalize_lookup_text(value: Any) -> str:
    text = clean_text(value)
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text)


def clean_price_point_label(text: str) -> str:
    label = clean_text(text)
    label = PRICE_PREFIX_RE.sub("", label)
    label = PRICE_SUFFIX_RE.sub("", label)
    label = re.sub(r"[：:、，,；;。]+$", "", label)
    label = clean_text(label)
    return label or "主流货"


def normalize_price_point_label(text: str) -> str:
    label = clean_text(text)
    label = LIST_MARKER_RE.sub("", label)
    label = PRICE_PREFIX_RE.sub("", label)
    label = PRICE_SUFFIX_RE.sub("", label)
    label = re.sub(r"[：:、，,；;。]+$", "", label)
    label = clean_text(label)
    if not label:
        return "主流报价"
    if INVALID_PRICE_LABEL_RE.search(label):
        return ""
    if GENERIC_PRICE_LABEL_RE.fullmatch(label):
        return "主流报价"
    return refine_price_point_label(label)


def price_label_candidates(label: str) -> list[str]:
    text = clean_text(label)
    if not text:
        return []
    candidates = [text]
    for sep in ("，", ",", "；", ";", "。", "：", ":"):
        if sep in text:
            candidates.append(clean_text(text.split(sep)[-1]))
    if "市场" in text:
        candidates.append(clean_text(text.split("市场")[-1]))
    if "的" in text:
        candidates.append(clean_text(text.split("的")[-1]))
    for prefix in ("现本地", "现当地", "本地", "当地", "现", "市场", "产地"):
        if text.startswith(prefix):
            candidates.append(clean_text(text[len(prefix) :]))
    match = TAIL_SPEC_RE.search(text)
    if match:
        candidates.append(clean_text(match.group(1)))
    unique: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in unique:
            unique.append(candidate)
    return unique


def price_label_score(label: str) -> int:
    text = clean_text(label)
    if not text:
        return -999
    score = 0
    length = len(text)
    if text in GENERIC_PRICE_LABELS:
        score -= 2
    if 2 <= length <= 6:
        score += 5
    elif length <= 12:
        score += 3
    elif length <= 18:
        score += 1
    else:
        score -= 3
    if NOISY_LABEL_RE.search(text):
        score -= 6
    if any(ch in text for ch in "，,；;。:： "):
        score -= 4
    if TAIL_SPEC_RE.search(text):
        score += 4
    if re.search(r"\d+%|家种|饮片|药厂|统货|选装|净货|鲜果|鲜货", text):
        score += 1
    return score


def refine_price_point_label(label: str) -> str:
    candidates = price_label_candidates(label)
    if not candidates:
        return "主流报价"
    best = max(candidates, key=lambda candidate: (price_label_score(candidate), -len(candidate), candidate))
    return best or "主流报价"


def has_change_only_price(summary: str) -> bool:
    return bool(CHANGE_ONLY_PRICE_RE.search(clean_text(summary)))


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
                label = normalize_price_point_label(part[:match.start()])
                if not label:
                    continue
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


def normalize_price_points(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    points: list[dict[str, str]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        label = normalize_price_point_label(raw.get("label") or raw.get("spec") or raw.get("name"))
        price = clean_text(raw.get("price") or raw.get("value"))
        if not label or not price:
            continue
        points.append({"label": label, "price": price})
    return points


def detect_province(text: str) -> str:
    value = clean_text(text)
    for prefix in PROVINCE_PREFIXES:
        if value.startswith(prefix):
            return prefix
    return ""


def is_noise_location_text(text: str) -> bool:
    value = clean_text(text)
    if not value:
        return False
    if NOISE_LOCATION_RE.match(value):
        return True
    return bool(re.search(r"\d{4}年|\d{1,2}月|\d{1,2}日|星期[一二三四五六日天]", value))


def location_keywords(text: str) -> list[str]:
    value = clean_text(text)
    if not value:
        return []
    province = detect_province(value)
    remainder = value[len(province):] if province and value.startswith(province) else value
    keywords: list[str] = [province] if province else []
    keywords.extend(
        clean_text(part)
        for part in LOCATION_SPLIT_RE.split(remainder)
        if len(clean_text(part)) >= 2 and not is_noise_location_text(clean_text(part))
    )
    if not keywords and len(value) >= 2:
        keywords.append(value)
    return keywords


def primary_location_token(text: str) -> str:
    keywords = location_keywords(text)
    if not keywords:
        return ""
    province = keywords[0] if keywords[0] in PROVINCE_PREFIXES else ""
    non_province = [keyword for keyword in keywords if keyword != province]
    return non_province[-1] if non_province else (province or keywords[-1])


def merge_price_points(points: list[dict[str, str]]) -> list[dict[str, str]]:
    def price_numbers(text: str) -> list[float]:
        values: list[float] = []
        for match in re.findall(r"\d+(?:\.\d+)?", text):
            try:
                values.append(float(match))
            except ValueError:
                continue
        return values

    def prefer_price(existing: str, candidate: str) -> str:
        existing_numbers = price_numbers(existing)
        candidate_numbers = price_numbers(candidate)
        if len(existing_numbers) == 2 and len(candidate_numbers) == 1:
            start, end = sorted(existing_numbers)
            if start <= candidate_numbers[0] <= end:
                return existing
        if len(candidate_numbers) == 2 and len(existing_numbers) == 1:
            start, end = sorted(candidate_numbers)
            if start <= existing_numbers[0] <= end:
                return candidate
        if existing in candidate or ("-" in candidate and "-" not in existing):
            return candidate
        if candidate in existing:
            return existing
        return f"{existing} / {candidate}"

    merged: dict[str, str] = {}
    order: list[str] = []
    best_label_by_price: dict[str, str] = {}
    for point in points:
        raw_label = clean_text(point.get("label"))
        if raw_label in GENERIC_PRICE_LABELS:
            label = "主流报价"
        else:
            label = refine_price_point_label(clean_price_point_label(raw_label))
        price = clean_text(point.get("price"))
        if not label or not price:
            continue
        current_best_label = best_label_by_price.get(price)
        if current_best_label is None or price_label_score(label) > price_label_score(current_best_label):
            best_label_by_price[price] = label
        if label not in merged:
            merged[label] = price
            order.append(label)
            continue
        if merged[label] == price:
            continue
        merged[label] = prefer_price(merged[label], price)
    rows: list[dict[str, str]] = []
    for label in order:
        price = merged[label]
        best_label = best_label_by_price.get(price, label)
        if best_label != label and price_label_score(best_label) >= price_label_score(label):
            continue
        rows.append({"label": label, "price": price})

    specific_prices = {
        row["price"]
        for row in rows
        if row["label"] not in GENERIC_PRICE_LABELS
    }
    filtered_rows: list[dict[str, str]] = []
    for row in rows:
        if row["label"] not in GENERIC_PRICE_LABELS:
            filtered_rows.append(row)
            continue
        remaining_parts = [part for part in row["price"].split(" / ") if part not in specific_prices]
        if not remaining_parts:
            continue
        filtered_rows.append({"label": row["label"], "price": " / ".join(remaining_parts)})
    return filtered_rows


def build_item_price_points(item: dict[str, Any]) -> list[dict[str, str]]:
    detail_text = item.get("content_full") or item.get("summary")
    points = normalize_price_points(item.get("price_points"))
    extracted_points = extract_price_points(detail_text)
    points = merge_price_points(points + extracted_points)
    price = clean_text(item.get("price"))
    spec = clean_text(item.get("spec"))
    if price and not points:
        if has_change_only_price(detail_text):
            return []
        if spec and spec not in {"产地快讯", "市场快讯", "待补规格"}:
            label = normalize_price_point_label(spec)
            if not label:
                return []
        else:
            label = "主流报价"
        points.append({"label": label, "price": price})
    return merge_price_points(points)


def tag_rank(tag: str) -> int:
    value = clean_text(tag)
    if value in {"走快", "上扬"}:
        return 4
    if value in {"平稳"}:
        return 3
    if value in {"关注"}:
        return 2
    if value in {"走缓", "回落"}:
        return 1
    return 0


def source_entry_score(item: dict[str, Any]) -> tuple[int, int]:
    return (
        1 if "/hqzx/" in clean_text(item.get("url")) else 0,
        len(build_item_price_points(item)),
        len(clean_text(item.get("content_full") or item.get("summary"))),
    )


def locations_match(item: dict[str, Any], group_items: list[dict[str, Any]]) -> bool:
    item_location = clean_text(item.get("location"))
    item_summary = clean_text(item.get("summary"))
    item_province = detect_province(item_location or item_summary)
    item_primary = primary_location_token(item_location or item_summary)
    item_tokens = [token for token in location_keywords(item_location or item_summary) if token not in PROVINCE_PREFIXES]
    item_context = normalize_lookup_text(f"{item_location} {item_summary}")

    for current in group_items:
        current_location = clean_text(current.get("location"))
        current_summary = clean_text(current.get("summary"))
        current_province = detect_province(current_location or current_summary)
        current_primary = primary_location_token(current_location or current_summary)
        current_tokens = [token for token in location_keywords(current_location or current_summary) if token not in PROVINCE_PREFIXES]
        current_context = normalize_lookup_text(f"{current_location} {current_summary}")

        if item_province and current_province and item_province != current_province:
            continue
        if item_primary and current_primary and item_primary == current_primary:
            return True
        if set(item_tokens) & set(current_tokens):
            return True
        if any(token and token in current_context for token in item_tokens):
            return True
        if any(token and token in item_context for token in current_tokens):
            return True
    return False


def merged_origin_location(items: list[dict[str, Any]]) -> str:
    province = ""
    tails: list[str] = []
    for item in items:
        location = clean_text(item.get("location"))
        current_province = detect_province(location)
        if not province and current_province:
            province = current_province
        tail = primary_location_token(location)
        if tail and tail not in PROVINCE_PREFIXES and not is_noise_location_text(tail) and tail not in tails:
            tails.append(tail)
    if province and tails:
        return province + "/".join(tails[:2])
    if province:
        return province
    return clean_text(items[0].get("location")) if items else ""


def merge_origin_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    for item in items:
        if not clean_text(item.get("date")) or not clean_text(item.get("herb")):
            groups.append([item])
            continue
        matched = False
        for group in groups:
            sample = group[0]
            if clean_text(sample.get("date")) != clean_text(item.get("date")):
                continue
            if clean_text(sample.get("herb")) != clean_text(item.get("herb")):
                continue
            if locations_match(item, group):
                group.append(item)
                matched = True
                break
        if not matched:
            groups.append([item])

    merged_items: list[dict[str, Any]] = []
    for group in groups:
        sorted_group = sorted(group, key=lambda entry: (source_entry_score(entry), len(clean_text(entry.get("summary")))), reverse=True)
        primary = sorted_group[0]
        price_points = merge_price_points([point for entry in sorted_group for point in build_item_price_points(entry)])
        source_names: list[str] = []
        source_links: dict[str, tuple[tuple[int, int], str]] = {}
        for entry in sorted_group:
            source = clean_text(entry.get("source"))
            if source and source not in source_names:
                source_names.append(source)
            url = clean_text(entry.get("url"))
            if not source or not url:
                continue
            score = source_entry_score(entry)
            if source not in source_links or score > source_links[source][0]:
                source_links[source] = (score, url)

        merged = {
            "date": primary.get("date", ""),
            "herb": primary.get("herb", ""),
            "spec": "",
            "location": merged_origin_location(sorted_group) or primary.get("location", ""),
            "market": "产地",
            "price": price_points[0]["price"] if len(price_points) == 1 else "",
            "price_value": parse_number(price_points[0]["price"].split(" ")[0]) if len(price_points) == 1 else None,
            "unit": primary.get("unit", "元/kg"),
            "delta_amount": primary.get("delta_amount", ""),
            "delta_rate": primary.get("delta_rate", ""),
            "tag": max(sorted_group, key=lambda entry: tag_rank(entry.get("tag", ""))).get("tag", "关注"),
            "summary": max(sorted_group, key=lambda entry: len(clean_text(entry.get("summary")))).get("summary", ""),
            "content_full": max(sorted_group, key=lambda entry: len(clean_text(entry.get("content_full") or entry.get("summary")))).get("content_full") or "",
            "source": "、".join(source_names) if source_names else clean_text(primary.get("source")),
            "url": "",
            "source_links": [{"label": source, "url": url} for source, (_, url) in source_links.items()],
            "price_points": price_points,
        }
        merged_items.append(merged)

    merged_items.sort(key=lambda item: (date_key(item.get("date", ""))[1], item.get("herb", ""), item.get("location", "")), reverse=True)
    return merged_items


def normalize_row(record: dict[str, str]) -> WorkbookRecord:
    today_num = parse_number(record["今日价"])
    yesterday_num = parse_number(record["昨日价"])
    delta_amount = record["涨跌额"]
    delta_rate = record["涨跌幅"]

    if today_num is not None and yesterday_num is not None:
        if not clean_text(delta_amount):
            delta_amount = format_number(today_num - yesterday_num)
        if not clean_text(delta_rate) and yesterday_num != 0:
            delta_rate = format_number((today_num - yesterday_num) / yesterday_num)

    return WorkbookRecord(
        date=clean_text(record["记录日期"]),
        herb=clean_text(record["品种"]),
        spec=clean_text(record["规格"]),
        unit=clean_text(record["单位"]),
        market=clean_text(record["市场"]),
        location=clean_text(record["产区"]),
        today_price=clean_text(record["今日价"]),
        yesterday_price=clean_text(record["昨日价"]),
        delta_amount=clean_text(delta_amount),
        delta_rate=clean_text(delta_rate),
        source=clean_text(record["来源网站"]),
        url=normalize_source_url(record["来源网站"], record["来源链接"]),
        summary=clean_text(record["备注"]),
        content_full="",
    )


def detect_tag(summary: str, delta_amount: str) -> str:
    summary_text = clean_text(summary)
    delta_num = parse_number(delta_amount)
    if delta_num is not None:
        if delta_num > 0:
            return "上扬"
        if delta_num < 0:
            return "回落"
    if any(keyword in summary_text for keyword in UP_KEYWORDS):
        return "走快"
    if any(keyword in summary_text for keyword in DOWN_KEYWORDS):
        return "走缓"
    if any(keyword in summary_text for keyword in STEADY_KEYWORDS):
        return "平稳"
    return "关注"


def value_from_cell(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    inline = cell.find(f"{XML_NS}is")
    if inline is not None:
        return "".join(node.text or "" for node in inline.iter(f"{XML_NS}t"))
    value = cell.find(f"{XML_NS}v")
    if value is None:
        return ""
    raw = value.text or ""
    if cell_type == "s" and raw.isdigit():
        return shared_strings[int(raw)]
    return raw


def load_workbook_rows(path: Path) -> list[WorkbookRecord]:
    with ZipFile(path) as archive:
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {item.attrib["Id"]: item.attrib["Target"] for item in relationships}
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in shared_root.findall(f"{XML_NS}si"):
                shared_strings.append("".join(node.text or "" for node in item.iter(f"{XML_NS}t")))

        target = None
        for sheet in workbook.find(f"{XML_NS}sheets") or []:
            if sheet.attrib.get("name") == SHEET_NAME:
                target = "xl/" + rel_map[sheet.attrib[REL_NS]]
                break
        if target is None:
            raise ValueError(f"Workbook does not contain sheet: {SHEET_NAME}")

        sheet_root = ET.fromstring(archive.read(target))
        raw_rows: list[dict[str, str]] = []
        for row in sheet_root.findall(f".//{XML_NS}sheetData/{XML_NS}row"):
            row_map: dict[str, str] = {}
            for cell in row.findall(f"{XML_NS}c"):
                ref = cell.attrib.get("r", "")
                col = "".join(char for char in ref if char.isalpha())
                row_map[col] = clean_text(value_from_cell(cell, shared_strings))
            raw_rows.append(row_map)

    if not raw_rows:
        return []

    headers = [raw_rows[0].get(col, "") for col in COLS]
    normalized: list[WorkbookRecord] = []
    for row in raw_rows[1:]:
        if not any(clean_text(row.get(col, "")) for col in COLS):
            continue
        record = {headers[idx]: clean_text(row.get(col, "")) for idx, col in enumerate(COLS)}
        normalized.append(normalize_row(record))
    return normalized


def fetch_yt_items(lmid: str, min_date: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for page in range(1, 61):
        params = {"lmid": lmid, "pageIndex": str(page), "pageSize": "20"}
        if lmid == "3":
            params["times"] = "1"
        else:
            params["ycnam"] = ""
        request = Request(f"{YT_QUERY_URL}?{urlencode(params)}", headers=YT_HEADERS)
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8", "ignore"))
        page_items = payload.get("data") or []
        if not page_items:
            break
        items.extend(page_items)
        page_dates = [clean_text(item.get("dtm"))[:10] for item in page_items]
        if min_date and page_dates and all(date and date < min_date for date in page_dates):
            break
    return items


def yt_detail_url(item: dict[str, Any], is_origin: bool) -> str:
    accode = clean_text(item.get("accode"))
    if not accode:
        return ""
    if is_origin:
        return f"https://www.yt1998.com/hqzx/{accode}.html"
    scid = clean_text(item.get("scid")) or "1"
    return f"https://www.yt1998.com/hqzx/{accode}_{scid}.html"


def score_yt_match(record: WorkbookRecord, item: dict[str, Any]) -> int:
    record_date = clean_text(record.date)
    item_date = clean_text(item.get("dtm"))[:10]
    if not record_date or record_date != item_date:
        return -1

    record_herb = normalize_lookup_text(record.herb)
    record_summary = normalize_lookup_text(record.summary)
    record_location = normalize_lookup_text(record.location)
    record_market = normalize_lookup_text(record.market)

    item_herb = normalize_lookup_text(item.get("ycnam"))
    item_title = normalize_lookup_text(item.get("title"))
    item_content = normalize_lookup_text(item.get("cont"))
    item_market = normalize_lookup_text(item.get("market"))

    score = 0
    if record_herb and record_herb == item_herb:
        score += 3
    elif record_herb and record_herb in (item_title + item_content):
        score += 1

    if record_summary and record_summary == item_title:
        score += 6
    elif record_summary and record_summary in item_title:
        score += 5
    elif record_summary and record_summary in item_content:
        score += 4

    if record.market == "产地":
        if record_location and record_location in item_title:
            score += 3
        elif record_location and record_location in item_content:
            score += 2
    else:
        if record_market and record_market in item_market:
            score += 2

    return score


def backfill_yt1998_urls(records: list[WorkbookRecord]) -> list[WorkbookRecord]:
    target_records = [
        record
        for record in records
        if record.source == "药通网" and not clean_text(record.url)
    ]
    if not target_records:
        return records

    origin_targets = [record for record in target_records if record.market == "产地"]
    market_targets = [record for record in target_records if record.market != "产地"]

    origin_items: list[dict[str, Any]] = []
    market_items: list[dict[str, Any]] = []
    if origin_targets:
        origin_min_date = min(record.date for record in origin_targets if record.date)
        origin_items = fetch_yt_items("9", origin_min_date)
    if market_targets:
        market_min_date = min(record.date for record in market_targets if record.date)
        market_items = fetch_yt_items("3", market_min_date)

    updated: list[WorkbookRecord] = []
    for record in records:
        if record.source != "药通网" or clean_text(record.url):
            updated.append(record)
            continue

        candidates = origin_items if record.market == "产地" else market_items
        best_score = -1
        best_item: dict[str, Any] | None = None
        for item in candidates:
            score = score_yt_match(record, item)
            if score > best_score:
                best_score = score
                best_item = item

        next_url = record.url
        if best_item is not None and best_score >= 8:
            next_url = yt_detail_url(best_item, record.market == "产地")

        updated.append(
            WorkbookRecord(
                date=record.date,
                herb=record.herb,
                spec=record.spec,
                unit=record.unit,
                market=record.market,
                location=record.location,
                today_price=record.today_price,
                yesterday_price=record.yesterday_price,
                delta_amount=record.delta_amount,
                delta_rate=record.delta_rate,
                source=record.source,
                url=next_url,
                summary=record.summary,
                content_full=record.content_full,
                price_label=record.price_label,
                price_points=record.price_points,
            )
        )

    return updated


def date_key(value: str) -> tuple[int, str]:
    text = clean_text(value)
    if not text:
        return (0, "")
    try:
        return (1, datetime.strptime(text, "%Y-%m-%d").strftime("%Y%m%d"))
    except ValueError:
        return (1, text)


def item_sort_key(item: WorkbookRecord) -> tuple[str, str, str]:
    has_date, normalized_date = date_key(item.date)
    return (normalized_date if has_date else "", item.herb, item.location)


def to_origin_item(item: WorkbookRecord) -> dict[str, Any]:
    today_num = parse_number(item.today_price)
    display_spec = clean_text(item.spec)
    if display_spec in {"市场快讯", "待补规格"}:
        display_spec = ""
    detail_text = item.content_full or item.summary
    price_points = merge_price_points(normalize_price_points(item.price_points) + extract_price_points(detail_text))
    display_price = ""
    if len(price_points) == 1:
        display_price = price_points[0]["price"]
    elif item.price_label and not has_change_only_price(detail_text):
        display_price = item.price_label
    elif not price_points and not has_change_only_price(detail_text):
        display_price = format_price(item.today_price, item.unit)
    payload = {
        "date": item.date,
        "herb": item.herb,
        "spec": display_spec,
        "location": item.location or "待补产区",
        "market": item.market or "产地",
        "price": display_price,
        "price_value": today_num,
        "unit": item.unit or "元/kg",
        "delta_amount": format_number(parse_number(item.delta_amount)),
        "delta_rate": format_number(parse_number(item.delta_rate)),
        "tag": detect_tag(detail_text or item.summary, item.delta_amount),
        "summary": item.summary,
        "content_full": detail_text,
        "source": item.source or "待补来源",
        "url": item.url,
    }
    if price_points:
        payload["price_points"] = price_points
    return payload


def build_hotspot_items(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Hotspot file must be a JSON array.")

    items: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        base_id = normalize_lookup_text(
            raw.get("id")
            or raw.get("url")
            or f"{clean_text(raw.get('date'))}-{clean_text(raw.get('title'))}"
        )[:80] or f"hotspot{len(items) + 1}"
        hotspot_id = f"hotspot-{base_id}"
        suffix = 2
        while hotspot_id in used_ids:
            hotspot_id = f"hotspot-{base_id}-{suffix}"
            suffix += 1
        used_ids.add(hotspot_id)
        items.append(
            {
                "id": hotspot_id,
                "date": clean_text(raw.get("date")),
                "title": clean_text(raw.get("title")),
                "kind": clean_text(raw.get("kind")) or "行业热点",
                "summary": clean_text(raw.get("summary")),
                "content_full": clean_text(raw.get("content_full")),
                "source": clean_text(raw.get("source")) or "待补来源",
                "url": clean_text(raw.get("url")),
                "herb": clean_text(raw.get("herb")),
                "location": clean_text(raw.get("location")),
            }
        )
    items.sort(key=lambda item: (date_key(item["date"])[1], item["title"]), reverse=True)
    return items


def load_json_records(path: Path | None, empty_error: str) -> list[WorkbookRecord]:
    if path is None or not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(empty_error)

    records: list[WorkbookRecord] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        records.append(
            WorkbookRecord(
                date=clean_text(raw.get("date")),
                herb=clean_text(raw.get("herb")),
                spec=clean_text(raw.get("spec")) or ("产地快讯" if clean_text(raw.get("market")) in ("", "产地") else ""),
                unit=clean_text(raw.get("unit")) or "元/kg",
                market=clean_text(raw.get("market")) or "产地",
                location=clean_text(raw.get("location")),
                today_price=clean_text(raw.get("today_price")),
                yesterday_price=clean_text(raw.get("yesterday_price")),
                delta_amount=clean_text(raw.get("delta_amount")),
                delta_rate=clean_text(raw.get("delta_rate")),
                source=clean_text(raw.get("source")),
                url=normalize_source_url(raw.get("source"), raw.get("url")),
                summary=clean_text(raw.get("summary")),
                content_full=clean_text(raw.get("content_full")),
                price_label=clean_text(raw.get("price_label")),
                price_points=normalize_price_points(raw.get("price_points")),
            )
        )
    return records


def dedupe_records(records: list[WorkbookRecord]) -> list[WorkbookRecord]:
    def record_quality(record: WorkbookRecord) -> int:
        score = 0
        if clean_text(record.url):
            score += 2
        if clean_text(record.price_label):
            score += 1
        if record.price_points:
            score += 4 + len(record.price_points)
        if clean_text(record.today_price):
            score += 1
        if clean_text(record.location):
            score += 1
        if clean_text(record.spec) and clean_text(record.spec) not in {"市场快讯", "产地快讯"}:
            score += 1
        return score

    seen: dict[tuple[str, str, str, str, str, str], WorkbookRecord] = {}
    order: list[tuple[str, str, str, str, str, str]] = []
    for record in records:
        key = (
            clean_text(record.date),
            clean_text(record.market),
            clean_text(record.herb),
            clean_text(record.location),
            clean_text(record.source),
            clean_text(record.summary),
        )
        if key not in seen:
            seen[key] = record
            order.append(key)
            continue
        if record_quality(record) > record_quality(seen[key]):
            seen[key] = record
    return [seen[key] for key in order]


def build_dashboard(records: list[WorkbookRecord], source_label: str, hotspot_path: Path | None) -> dict[str, Any]:
    records = sorted(records, key=item_sort_key, reverse=True)
    latest_date = records[0].date if records else ""
    dates = sorted({record.date for record in records if record.date}, reverse=True)
    sources = Counter(record.source for record in records if record.source)
    herbs = Counter(record.herb for record in records if record.herb)
    origin_records = [record for record in records if record.market == "产地"]
    market_records = [record for record in records if record.market != "产地"]
    origin_sources = Counter(record.source for record in origin_records if record.source)
    origin_items = merge_origin_items([to_origin_item(record) for record in origin_records])
    market_items = [to_origin_item(record) for record in market_records]

    market_counter = Counter(record.market for record in market_records if record.market)
    market_order = MARKET_TARGETS + sorted(name for name in market_counter if name not in MARKET_TARGETS)
    market_groups: list[dict[str, Any]] = []
    for market_name in market_order:
        items = [item for item in market_items if item["market"] == market_name]
        source_breakdown = Counter(item["source"] for item in items)
        market_groups.append(
            {
                "name": market_name,
                "count": len(items),
                "latest_date": items[0]["date"] if items else "",
                "sources": [f"{name} {count} 条" for name, count in source_breakdown.most_common()],
                "items": items,
            }
        )

    hotspots = build_hotspot_items(hotspot_path)
    latest_day_records = [record for record in records if record.date == latest_date] if latest_date else []
    latest_day_herbs = Counter(record.herb for record in latest_day_records if record.herb).most_common(5)

    return {
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source_file": source_label,
            "latest_date": latest_date,
            "available_dates": dates,
            "total_records": len(records),
            "origin_records": len(origin_records),
            "market_records": len(market_records),
            "source_count": len(sources),
            "herb_count": len(herbs),
            "market_targets": MARKET_TARGETS,
        },
        "status": f"真实数据版 · 最新整理于 {latest_date}" if latest_date else "数据待补充",
        "hero": {
            "eyebrow": "产地行情 / 市场行情 / 行业热点",
            "title": "先把真实记录摊开，再做判断与趋势。",
            "lead": "首页围绕中药材真实记录来搭建：产地行情完整铺开，市场行情围绕亳州、安国、玉林持续更新，行业热点单独维护，不和报价信息混在一起。",
            "source_strip": [
                f"总记录：{len(records)} 条",
                f"产地：{len(origin_records)} 条",
                f"市场：{len(market_records)} 条",
                f"来源站点：{len(sources)} 个",
            ],
        },
        "snapshot": {
            "latest_date": latest_date,
            "latest_count": len(latest_day_records),
            "top_herbs": [{"name": name, "count": count} for name, count in latest_day_herbs],
            "sources": [{"name": name, "count": count} for name, count in sources.most_common(4)],
        },
        "origin": {
            "total": len(origin_items),
            "latest_date": origin_items[0]["date"] if origin_items else "",
            "date_options": dates,
            "source_options": [name for name, _ in origin_sources.most_common()],
            "items": origin_items,
            "empty_text": "当前还没有产地行情记录。",
        },
        "markets": {
            "title": "市场行情",
            "targets": MARKET_TARGETS,
            "total": len(market_items),
            "covered_count": sum(1 for group in market_groups if group["name"] in MARKET_TARGETS and group["count"] > 0),
            "extra_market_count": sum(1 for group in market_groups if group["name"] not in MARKET_TARGETS and group["count"] > 0),
            "groups": market_groups,
            "empty_text": "当前市场行情记录还不完整，后续会继续补齐药通网市场行情。",
        },
        "hotspots": {
            "total": len(hotspots),
            "latest_date": hotspots[0]["date"] if hotspots else "",
            "kind_options": sorted({item["kind"] for item in hotspots if item["kind"]}),
            "items": hotspots,
            "empty_text": "行业热点表已经预留好，后面补进 JSON 就能直接显示。",
        },
        "footer": {
            "left": f"数据文件：{source_label}",
            "right": "站点结构已兼容后续继续补药通网市场行情与行业热点。",
        },
    }


def resolve_input_path(raw_input: str | None, required: bool = True) -> Path | None:
    candidates: list[Path] = []
    env_path = os.environ.get("DASHBOARD_INPUT_XLSX")
    if raw_input:
      candidates.append(Path(raw_input).expanduser())
    if env_path:
      candidates.append(Path(env_path).expanduser())
    candidates.extend(
        [
            Path("data-source/latest.xlsx"),
            Path("/Users/bohao/Desktop/中药材全国追踪_近3日整理_2026-03-13.xlsx"),
        ]
    )

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists():
            return resolved
    if not required:
        return None
    searched = "\n".join(f"- {candidate}" for candidate in candidates)
    raise SystemExit(f"Excel file not found. Checked:\n{searched}")


def main() -> None:
    parser = argparse.ArgumentParser(description="从中药材 Excel 生成静态站 dashboard.json")
    parser.add_argument(
        "--input",
        default=None,
        help="输入 Excel 文件路径；默认优先读取 data-source/latest.xlsx",
    )
    parser.add_argument(
        "--hotspots",
        default="content/hotspots.json",
        help="行业热点 JSON 文件路径（可为空数组）",
    )
    parser.add_argument(
        "--output",
        default="public/data/dashboard.json",
        help="输出 dashboard.json 的路径",
    )
    parser.add_argument(
        "--openclaw-origin",
        default="content/openclaw_origin.json",
        help="OpenClaw 产地 JSON 文件路径；存在时会自动并入产地行情",
    )
    parser.add_argument(
        "--market-json",
        default="content/market_updates.json",
        help="市场行情 JSON 文件路径；存在时会自动并入市场行情",
    )
    parser.add_argument(
        "--exclude-workbook-origin",
        action="store_true",
        help="构建时排除 Excel 里的旧产地记录，仅保留市场记录与 JSON 导入数据",
    )
    parser.add_argument(
        "--exclude-workbook-market",
        action="store_true",
        help="构建时排除 Excel 里的旧市场记录，仅保留产地记录与 JSON 导入数据",
    )
    args = parser.parse_args()

    openclaw_path = Path(args.openclaw_origin).expanduser().resolve()
    market_path = Path(args.market_json).expanduser().resolve()
    openclaw_records = load_json_records(
        openclaw_path if openclaw_path.exists() else None,
        "OpenClaw origin file must be a JSON array.",
    )
    market_json_records = load_json_records(
        market_path if market_path.exists() else None,
        "Market updates file must be a JSON array.",
    )
    source_path = resolve_input_path(args.input, required=not (openclaw_records or market_json_records))
    hotspot_path = Path(args.hotspots).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    records = load_workbook_rows(source_path) if source_path else []
    if args.exclude_workbook_origin:
        records = [record for record in records if record.market != "产地"]
    if args.exclude_workbook_market:
        records = [record for record in records if record.market == "产地"]
    records = dedupe_records(records + openclaw_records + market_json_records)
    records = backfill_yt1998_urls(records)

    source_parts: list[str] = []
    if source_path:
        source_parts.append(source_path.name)
    if openclaw_records:
        source_parts.append(openclaw_path.name)
    if market_json_records:
        source_parts.append(market_path.name)
    source_label = " + ".join(source_parts) if source_parts else "无输入文件"

    dashboard = build_dashboard(records, source_label, hotspot_path if hotspot_path.exists() else None)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {output_path} with {len(records)} records.")


if __name__ == "__main__":
    main()
