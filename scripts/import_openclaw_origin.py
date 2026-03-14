#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


PROVINCES: list[tuple[str, str]] = [
    ("内蒙古自治区", "内蒙古"),
    ("广西壮族自治区", "广西"),
    ("宁夏回族自治区", "宁夏"),
    ("新疆维吾尔自治区", "新疆"),
    ("西藏自治区", "西藏"),
    ("香港特别行政区", "香港"),
    ("澳门特别行政区", "澳门"),
    ("黑龙江省", "黑龙江"),
    ("吉林省", "吉林"),
    ("辽宁省", "辽宁"),
    ("河北省", "河北"),
    ("山西省", "山西"),
    ("陕西省", "陕西"),
    ("甘肃省", "甘肃"),
    ("青海省", "青海"),
    ("山东省", "山东"),
    ("江苏省", "江苏"),
    ("安徽省", "安徽"),
    ("浙江省", "浙江"),
    ("江西省", "江西"),
    ("福建省", "福建"),
    ("河南省", "河南"),
    ("湖北省", "湖北"),
    ("湖南省", "湖南"),
    ("广东省", "广东"),
    ("海南省", "海南"),
    ("四川省", "四川"),
    ("贵州省", "贵州"),
    ("云南省", "云南"),
    ("台湾省", "台湾"),
    ("北京市", "北京"),
    ("天津市", "天津"),
    ("上海市", "上海"),
    ("重庆市", "重庆"),
    ("北京", "北京"),
    ("天津", "天津"),
    ("上海", "上海"),
    ("重庆", "重庆"),
    ("河北", "河北"),
    ("山西", "山西"),
    ("辽宁", "辽宁"),
    ("吉林", "吉林"),
    ("黑龙江", "黑龙江"),
    ("江苏", "江苏"),
    ("浙江", "浙江"),
    ("安徽", "安徽"),
    ("福建", "福建"),
    ("江西", "江西"),
    ("山东", "山东"),
    ("河南", "河南"),
    ("湖北", "湖北"),
    ("湖南", "湖南"),
    ("广东", "广东"),
    ("海南", "海南"),
    ("四川", "四川"),
    ("贵州", "贵州"),
    ("云南", "云南"),
    ("陕西", "陕西"),
    ("甘肃", "甘肃"),
    ("青海", "青海"),
    ("台湾", "台湾"),
    ("内蒙古", "内蒙古"),
    ("广西", "广西"),
    ("宁夏", "宁夏"),
    ("新疆", "新疆"),
    ("西藏", "西藏"),
]

LOCATION_TOKEN_RE = re.compile(
    r"([一-龥]{1,12}?)(?:自治州|特别行政区|自治区|地区|药市|市场|口岸|办事处|省|市|县|区|旗|盟|州|镇|乡|村)"
)
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
PRICE_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|~|至|到)\s*(\d+(?:\.\d+)?)\s*元(?:/公斤|/千克|每公斤|每千克|左右|上下|之间)?")
PRICE_SINGLE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*元(?:/公斤|/千克|每公斤|每千克|左右|上下|之间)?")
HERB_RE = re.compile(r"品种：\s*([^\s]+)")


def clean_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_name_date(path: Path) -> str:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    return match.group(1) if match else ""


def load_payload(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("origin_records"), list):
        return payload
    if not isinstance(payload.get("yt_items", []), list):
        return None
    if not isinstance(payload.get("zy_items", []), list):
        return None
    return payload


def find_latest_payload(workspace: Path) -> Path:
    candidates = list(workspace.glob("tmp_herb_*.json")) + list(workspace.glob("herb_market_brief_*.json"))
    usable: list[tuple[str, float, Path]] = []
    for path in candidates:
        payload = load_payload(path)
        if payload is None:
            continue
        usable.append((parse_name_date(path), path.stat().st_mtime, path))
    if not usable:
        raise SystemExit(f"No usable OpenClaw herb JSON found under {workspace}")
    usable.sort(key=lambda item: (item[0], item[1], item[2].name))
    return usable[-1][2]


def normalize_location(text: str) -> str:
    raw = clean_text(text)
    if not raw:
        return ""
    raw = re.split(r"[，。；：（(: ]", raw, maxsplit=1)[0]
    province = ""
    rest = raw
    for full, alias in PROVINCES:
        if rest.startswith(full):
            province = alias
            rest = rest[len(full):]
            break

    tokens = LOCATION_TOKEN_RE.findall(rest)
    chosen = ""
    for token in tokens:
        if token in {"口岸", "市场", "药市", "办事处"}:
            continue
        chosen = token
    if not chosen and tokens:
        chosen = tokens[-1]

    if not chosen:
        chosen = re.sub(r"(办事处|药市|市场|口岸|产地)$", "", rest)
        chosen = clean_text(chosen)[:6]

    chosen = clean_text(chosen)
    if province and chosen.startswith(province):
        return chosen
    return f"{province}{chosen}" if province else chosen


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


def extract_date_from_time_text(text: str, fallback: str) -> str:
    match = DATE_RE.search(clean_text(text))
    return match.group(1) if match else fallback


def extract_herb_from_text(text: str) -> str:
    match = HERB_RE.search(clean_text(text))
    return clean_text(match.group(1)) if match else ""


def build_yt_url(acid: str) -> str:
    acid_text = clean_text(acid)
    return f"https://www.yt1998.com/marketInfo--{acid_text}.html" if acid_text else ""


def is_origin_like(title: str, source_text: str) -> bool:
    raw = f"{clean_text(title)} {clean_text(source_text)}"
    if "药市" in raw:
        return False
    if "市场" in raw and "产地" not in raw:
        return False
    return True


def normalize_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    if isinstance(payload.get("origin_records"), list):
        records = [item for item in payload["origin_records"] if isinstance(item, dict)]
        deduped: list[dict[str, str]] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for raw in records:
            item = {
                "date": clean_text(raw.get("date")),
                "herb": clean_text(raw.get("herb")),
                "spec": clean_text(raw.get("spec")) or "产地快讯",
                "unit": clean_text(raw.get("unit")) or "元/kg",
                "market": clean_text(raw.get("market")) or "产地",
                "location": clean_text(raw.get("location")),
                "today_price": clean_text(raw.get("today_price")),
                "yesterday_price": clean_text(raw.get("yesterday_price")),
                "delta_amount": clean_text(raw.get("delta_amount")),
                "delta_rate": clean_text(raw.get("delta_rate")),
                "source": clean_text(raw.get("source")),
                "url": clean_text(raw.get("url")),
                "summary": clean_text(raw.get("summary")),
                "price_label": clean_text(raw.get("price_label")),
            }
            if not item["date"] or not item["herb"] or not item["summary"]:
                continue
            key = (item["date"], item["herb"], item["location"], item["source"], item["summary"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        deduped.sort(key=lambda item: (item["date"], item["herb"], item["location"]), reverse=True)
        return deduped

    report_date = clean_text(payload.get("date"))
    records: list[dict[str, str]] = []

    for item in payload.get("yt_items", []):
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get("title"))
        source_text = clean_text(item.get("source"))
        if not is_origin_like(title, source_text):
            continue
        today_price, price_label = extract_price(item.get("desc"))
        records.append(
            {
                "date": clean_text(item.get("dtm")).split(" ")[0] or report_date,
                "herb": clean_text(item.get("variety")) or extract_herb_from_text(title),
                "spec": "产地快讯",
                "unit": "元/kg",
                "market": "产地",
                "location": normalize_location(source_text or title),
                "today_price": today_price,
                "yesterday_price": "",
                "delta_amount": "",
                "delta_rate": "",
                "source": "药通网",
                "url": build_yt_url(item.get("acid", "")),
                "summary": clean_text(item.get("desc")),
                "price_label": price_label,
            }
        )

    for item in payload.get("zy_items", []):
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get("title"))
        if not is_origin_like(title, title):
            continue
        today_price, price_label = extract_price(item.get("summary"))
        records.append(
            {
                "date": extract_date_from_time_text(item.get("time_text", ""), report_date),
                "herb": extract_herb_from_text(item.get("time_text", "")),
                "spec": "产地快讯",
                "unit": "元/kg",
                "market": "产地",
                "location": normalize_location(title),
                "today_price": today_price,
                "yesterday_price": "",
                "delta_amount": "",
                "delta_rate": "",
                "source": "中药材天地网",
                "url": clean_text(item.get("url")),
                "summary": clean_text(item.get("summary")),
                "price_label": price_label,
            }
        )

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for item in records:
        if not item["date"] or not item["herb"] or not item["summary"]:
            continue
        key = (item["date"], item["herb"], item["location"], item["source"], item["summary"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    deduped.sort(key=lambda item: (item["date"], item["herb"], item["location"]), reverse=True)
    return deduped


def main() -> None:
    parser = argparse.ArgumentParser(description="把 OpenClaw 的中药材抓取 JSON 转成网站可用的产地行情 JSON")
    parser.add_argument(
        "--workspace",
        default="/Users/bohao/.openclaw/workspace",
        help="OpenClaw 工作目录，默认读取 herb_market_brief_*.json / tmp_herb_*.json",
    )
    parser.add_argument(
        "--input",
        default=None,
        help="指定单个 OpenClaw JSON 文件；不传则自动选择最新可用文件",
    )
    parser.add_argument(
        "--output",
        default="content/openclaw_origin.json",
        help="输出给网站使用的产地行情 JSON 文件",
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    input_path = Path(args.input).expanduser().resolve() if args.input else find_latest_payload(workspace)
    payload = load_payload(input_path)
    if payload is None:
        raise SystemExit(f"OpenClaw JSON is not usable: {input_path}")

    records = normalize_payload(payload)
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "input": str(input_path),
        "output": str(output_path),
        "date": clean_text(payload.get("date")),
        "records": len(records),
        "yt_items": len(payload.get("yt_items", [])),
        "zy_items": len(payload.get("zy_items", [])),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
