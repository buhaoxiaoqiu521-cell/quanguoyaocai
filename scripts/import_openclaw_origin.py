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
LOCATION_PREFIXES = sorted({full for full, _ in PROVINCES} | {alias for _, alias in PROVINCES}, key=len, reverse=True)

LOCATION_TOKEN_RE = re.compile(
    r"([一-龥]{1,12}?)(?:自治州|特别行政区|自治区|地区|药市|市场|口岸|办事处|省|市|县|区|旗|盟|州|镇|乡|村)"
)
FULL_LOCATION_RE = re.compile(
    rf"((?:{'|'.join(re.escape(name) for name in LOCATION_PREFIXES)})"
    r"(?:[一-龥]{1,12}?(?:自治州|特别行政区|自治区|地区|盟|州|市))?"
    r"(?:[一-龥]{1,12}?(?:县|区|旗|市))?"
    r"(?:[一-龥]{1,12}?(?:镇|乡|街道|村))?)"
)
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
PRICE_RANGE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:-|~|至|到)\s*(\d+(?:\.\d+)?)\s*元(?:(/单斤|/市斤|/斤|/公斤|/千克|/条|/株|/棵|/苗|每单斤|每市斤|每斤|每公斤|每千克|每条|每株|每棵|每苗))?(?:左右|上下|之间)?"
)
PRICE_SINGLE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*元(?:(/单斤|/市斤|/斤|/公斤|/千克|/条|/株|/棵|/苗|每单斤|每市斤|每斤|每公斤|每千克|每条|每株|每棵|每苗))?(?:左右|上下|之间)?"
)
HERB_RE = re.compile(r"品种：\s*([^\s]+)")
HERB_PREFIX_RE = re.compile(
    r"^([一-龥A-Za-z0-9·（）()\-]{2,24}?)(?=(?:近阶段|近期|近日|当前|目前|现阶段|现|货源|有商家|有客商|行情|价格|产地|市场|走动|走销|销售|采挖|上市|供应|外销|出售|交易|收购|购进|进入|持续|继续|受|随|因))"
)
PLANT_UNIT_CONTEXT_RE = re.compile(r"(每株|每棵|每苗|株价|棵价|苗价)")


def clean_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_price_unit(unit: str) -> str:
    text = clean_text(unit).lower()
    if not text:
        return "元/kg"
    if text in {"元/kg", "kg", "公斤", "千克", "元/公斤", "元/千克", "/公斤", "/千克", "每公斤", "每千克"}:
        return "元/kg"
    if text in {"单斤", "元/单斤", "/单斤", "每单斤"}:
        return "元/单斤"
    if text in {"市斤", "斤", "元/斤", "元/市斤", "/斤", "/市斤", "每斤", "每市斤"}:
        return "元/斤"
    if text in {"条", "元/条", "/条", "每条"}:
        return "元/条"
    if text in {"株", "棵", "苗", "元/株", "元/棵", "元/苗", "/株", "/棵", "/苗", "每株", "每棵", "每苗"}:
        return "元/株"
    return clean_text(unit) or "元/kg"


def infer_price_unit(text: str, fallback: str = "元/kg") -> str:
    value = clean_text(text)
    if re.search(r"(?:元|块)\s*(?:/|每)?\s*(?:株|棵|苗)", value) or PLANT_UNIT_CONTEXT_RE.search(value):
        return "元/株"
    if re.search(r"(?:元|块)\s*(?:/|每)?\s*条", value):
        return "元/条"
    if re.search(r"(?:元|块)\s*(?:/|每)?\s*单斤", value):
        return "元/单斤"
    if re.search(r"(?:元|块)\s*(?:/|每)?\s*(?:市斤|斤)", value):
        return "元/斤"
    if re.search(r"(?:元|块)\s*(?:/|每)?\s*(?:公斤|千克)", value):
        return "元/kg"
    return normalize_price_unit(fallback)


def rewrite_price_label(price_label: str, unit: str, today_price: str = "") -> str:
    text = clean_text(price_label)
    unit_text = normalize_price_unit(unit)
    if text:
        numbers = re.findall(r"\d+(?:\.\d+)?", text)
        if len(numbers) >= 2 and any(sep in text for sep in ("-", "~", "至", "到", "～", "—", "－")):
            return f"{numbers[0]}-{numbers[1]} {unit_text}"
        if numbers:
            return f"{numbers[0]} {unit_text}"
    price = clean_text(today_price)
    return f"{price} {unit_text}" if price else ""


def seed_herb_candidate(text: str) -> str:
    value = clean_text(text)
    if not value:
        return ""
    match = HERB_PREFIX_RE.search(value)
    candidate = clean_text(match.group(1)) if match else ""
    if candidate and "籽" in candidate and 2 <= len(candidate) <= 18:
        return candidate
    return ""


def normalize_origin_herb(herb: str, summary: str, content: str) -> str:
    raw = clean_text(herb)
    if raw.endswith("籽"):
        return raw
    candidate = seed_herb_candidate(summary) or seed_herb_candidate(content)
    if candidate and (not raw or raw in candidate):
        return candidate
    return raw or candidate


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


def load_existing_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def normalize_location(text: str) -> str:
    raw = clean_text(text)
    if not raw:
        return ""
    full_match = FULL_LOCATION_RE.search(raw)
    if full_match:
        return clean_text(full_match.group(1))
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


def location_score(text: str) -> tuple[int, int, int]:
    value = clean_text(text)
    if not value:
        return (0, 0, 0)
    return (
        sum(value.count(token) for token in ("省", "市", "县", "区", "旗", "镇", "乡", "村", "自治州", "地区", "盟", "街道")),
        1 if any(value.startswith(name) for name in LOCATION_PREFIXES) else 0,
        len(value),
    )


def choose_best_location(*texts: Any) -> str:
    candidates: list[str] = []
    for raw in texts:
        normalized = normalize_location(raw)
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    if not candidates:
        return ""
    return max(candidates, key=location_score)


def extract_price(text: str) -> tuple[str, str]:
    value = clean_text(text)
    if not value:
        return ("", "")
    unit_hint = infer_price_unit(value, "")
    range_match = PRICE_RANGE_RE.search(value)
    if range_match:
        start, end, unit_token = range_match.groups()
        unit = normalize_price_unit(unit_token or unit_hint)
        return (start, f"{start}-{end} {unit}")
    single_match = PRICE_SINGLE_RE.search(value)
    if single_match:
        price, unit_token = single_match.groups()
        unit = normalize_price_unit(unit_token or unit_hint)
        return (price, f"{price} {unit}")
    return ("", "")


def rewrite_price_points(points: Any, preferred_unit: str) -> list[dict[str, str]]:
    if not isinstance(points, list):
        return []
    unit_text = normalize_price_unit(preferred_unit)
    if unit_text not in {"元/条", "元/株", "元/单斤"}:
        return [raw for raw in points if isinstance(raw, dict)]
    rewritten: list[dict[str, str]] = []
    for raw in points:
        if not isinstance(raw, dict):
            continue
        label = clean_text(raw.get("label") or raw.get("spec") or raw.get("name"))
        price = rewrite_price_label(raw.get("price", "") or raw.get("value", ""), unit_text)
        if not label or not price:
            continue
        rewritten.append({"label": label, "price": price})
    return rewritten


def point_unit(point: dict[str, Any]) -> str:
    text = clean_text(point.get("price") or point.get("value"))
    explicit = infer_price_unit(text, "")
    if explicit:
        return explicit
    return ""


def select_primary_unit(points: list[dict[str, str]], fallback: str = "元/kg") -> str:
    weighted: dict[str, int] = {}
    first_unit = ""
    for point in points:
        if not isinstance(point, dict):
            continue
        unit = point_unit(point)
        if not unit:
            continue
        if not first_unit:
            first_unit = unit
        label = clean_text(point.get("label"))
        weight = 1
        if "主流" in label:
            weight += 3
        if "整体" in label:
            weight += 2
        if "统货" in label:
            weight += 1
        weighted[unit] = weighted.get(unit, 0) + weight
    if weighted:
        return max(weighted.items(), key=lambda item: (item[1], 1 if item[0] == first_unit else 0))[0]
    return normalize_price_unit(fallback)


def extract_date_from_time_text(text: str, fallback: str) -> str:
    match = DATE_RE.search(clean_text(text))
    return match.group(1) if match else fallback


def normalize_published_at(value: str, fallback_date: str) -> str:
    text = clean_text(value)
    if not text:
        return f"{clean_text(fallback_date)} 00:00:00" if clean_text(fallback_date) else ""
    if " " in text:
        return text
    if DATE_RE.fullmatch(text):
        return f"{text} 00:00:00"
    return text


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
            detail_text = clean_text(raw.get("content_full") or raw.get("summary"))
            summary = clean_text(raw.get("summary")) or detail_text
            herb = normalize_origin_herb(raw.get("herb"), summary, detail_text)
            unit = infer_price_unit(detail_text, clean_text(raw.get("unit")) or clean_text(raw.get("price_label")) or "元/kg")
            price_points = rewrite_price_points(raw.get("price_points"), unit)
            unit = select_primary_unit(price_points, unit)
            location = choose_best_location(raw.get("location"), summary, detail_text)
            item = {
                "date": clean_text(raw.get("date")),
                "herb": herb,
                "spec": clean_text(raw.get("spec")) or "产地快讯",
                "unit": unit,
                "market": clean_text(raw.get("market")) or "产地",
                "location": location,
                "today_price": clean_text(raw.get("today_price")),
                "yesterday_price": clean_text(raw.get("yesterday_price")),
                "delta_amount": clean_text(raw.get("delta_amount")),
                "delta_rate": clean_text(raw.get("delta_rate")),
                "source": clean_text(raw.get("source")),
                "url": clean_text(raw.get("url")),
                "summary": summary,
                "published_at": normalize_published_at(raw.get("published_at", ""), raw.get("date", "")),
                "content_full": detail_text,
                "price_label": rewrite_price_label(raw.get("price_label", ""), unit, raw.get("today_price", "")),
                "price_points": price_points,
            }
            if not item["date"] or not item["herb"] or not item["summary"]:
                continue
            key = (item["date"], item["herb"], item["location"], item["source"], item["summary"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        deduped.sort(
            key=lambda item: (
                normalize_published_at(item.get("published_at", ""), item.get("date", "")),
                item["date"],
                item["herb"],
                item["location"],
            ),
            reverse=True,
        )
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
        detail_text = clean_text(item.get("content_full") or item.get("desc"))
        today_price, price_label = extract_price(item.get("desc"))
        unit = infer_price_unit(detail_text, price_label)
        price_points = rewrite_price_points(item.get("price_points"), unit)
        unit = select_primary_unit(price_points, unit)
        location = choose_best_location(source_text, title, clean_text(item.get("summary")), detail_text)
        records.append(
            {
                "date": clean_text(item.get("dtm")).split(" ")[0] or report_date,
                "herb": normalize_origin_herb(clean_text(item.get("variety")) or extract_herb_from_text(title), clean_text(item.get("summary") or detail_text), detail_text),
                "spec": "产地快讯",
                "unit": unit,
                "market": "产地",
                "location": location,
                "today_price": today_price,
                "yesterday_price": "",
                "delta_amount": "",
                "delta_rate": "",
                "source": "药通网",
                "url": build_yt_url(item.get("acid", "")),
                "summary": clean_text(item.get("summary") or detail_text),
                "published_at": normalize_published_at(item.get("dtm", ""), clean_text(item.get("dtm")).split(" ")[0] or report_date),
                "content_full": detail_text,
                "price_label": rewrite_price_label(price_label, unit, today_price),
                "price_points": price_points,
            }
        )

    for item in payload.get("zy_items", []):
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get("title"))
        if not is_origin_like(title, title):
            continue
        detail_text = clean_text(item.get("detail") or item.get("content_full") or item.get("summary"))
        today_price, price_label = extract_price(detail_text)
        unit = infer_price_unit(detail_text, price_label)
        price_points = rewrite_price_points(item.get("price_points"), unit)
        unit = select_primary_unit(price_points, unit)
        location = choose_best_location(title, clean_text(item.get("summary")), detail_text)
        records.append(
            {
                "date": extract_date_from_time_text(item.get("time_text", ""), report_date),
                "herb": normalize_origin_herb(extract_herb_from_text(item.get("time_text", "")), clean_text(item.get("summary") or detail_text), detail_text),
                "spec": "产地快讯",
                "unit": unit,
                "market": "产地",
                "location": location,
                "today_price": today_price,
                "yesterday_price": "",
                "delta_amount": "",
                "delta_rate": "",
                "source": "中药材天地网",
                "url": clean_text(item.get("url")),
                "summary": clean_text(item.get("summary") or detail_text),
                "published_at": normalize_published_at(
                    item.get("published_date", "") or extract_date_from_time_text(item.get("time_text", ""), report_date),
                    extract_date_from_time_text(item.get("time_text", ""), report_date),
                ),
                "content_full": detail_text,
                "price_label": rewrite_price_label(price_label, unit, today_price),
                "price_points": price_points,
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

    deduped.sort(
        key=lambda item: (
            normalize_published_at(item.get("published_at", ""), item.get("date", "")),
            item["date"],
            item["herb"],
            item["location"],
        ),
        reverse=True,
    )
    return deduped


def merge_records(new_records: list[dict[str, Any]], existing_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: dict[tuple[str, str, str, str], int] = {}
    for item in new_records + existing_records:
        record = {
            "date": clean_text(item.get("date")),
            "herb": clean_text(item.get("herb")),
            "spec": clean_text(item.get("spec")) or "产地快讯",
            "unit": clean_text(item.get("unit")) or "元/kg",
            "market": clean_text(item.get("market")) or "产地",
            "location": clean_text(item.get("location")),
            "today_price": clean_text(item.get("today_price")),
            "yesterday_price": clean_text(item.get("yesterday_price")),
            "delta_amount": clean_text(item.get("delta_amount")),
            "delta_rate": clean_text(item.get("delta_rate")),
            "source": clean_text(item.get("source")),
            "url": clean_text(item.get("url")),
            "summary": clean_text(item.get("summary")),
            "published_at": normalize_published_at(item.get("published_at", ""), item.get("date", "")),
            "content_full": clean_text(item.get("content_full")),
            "price_label": clean_text(item.get("price_label")),
            "price_points": item.get("price_points") if isinstance(item.get("price_points"), list) else [],
        }
        if not record["date"] or not record["herb"] or not record["summary"]:
            continue
        key = (record["date"], record["herb"], record["source"], record["summary"])
        if key in seen:
            current = merged[seen[key]]
            current["location"] = choose_best_location(
                current.get("location", ""),
                record.get("location", ""),
                current.get("summary", ""),
                current.get("content_full", ""),
                record.get("summary", ""),
                record.get("content_full", ""),
            )
            if not current.get("url") and record.get("url"):
                current["url"] = record["url"]
            if not current.get("published_at") and record.get("published_at"):
                current["published_at"] = record["published_at"]
            if not current.get("price_label") and record.get("price_label"):
                current["price_label"] = record["price_label"]
            if not current.get("price_points") and record.get("price_points"):
                current["price_points"] = record["price_points"]
            if current.get("unit") == "元/kg" and record.get("unit") and record.get("unit") != "元/kg":
                current["unit"] = record["unit"]
            continue
        seen[key] = len(merged)
        merged.append(record)
    merged.sort(
        key=lambda item: (
            normalize_published_at(item.get("published_at", ""), item.get("date", "")),
            item["date"],
            item["herb"],
            item["location"],
        ),
        reverse=True,
    )
    return merged


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
    parser.add_argument(
        "--replace-output",
        action="store_true",
        help="覆盖输出文件，不保留已有产地历史记录",
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    input_path = Path(args.input).expanduser().resolve() if args.input else find_latest_payload(workspace)
    payload = load_payload(input_path)
    if payload is None:
        raise SystemExit(f"OpenClaw JSON is not usable: {input_path}")

    output_path = Path(args.output).expanduser().resolve()
    records = normalize_payload(payload)
    existing_records = [] if args.replace_output else load_existing_records(output_path)
    records = merge_records(records, existing_records)
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
