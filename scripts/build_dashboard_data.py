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
    price_label: str = ""


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
        url=clean_text(record["来源链接"]),
        summary=clean_text(record["备注"]),
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
    return {
        "date": item.date,
        "herb": item.herb,
        "spec": item.spec or "待补规格",
        "location": item.location or "待补产区",
        "market": item.market or "产地",
        "price": item.price_label or format_price(item.today_price, item.unit),
        "price_value": today_num,
        "unit": item.unit or "元/kg",
        "delta_amount": format_number(parse_number(item.delta_amount)),
        "delta_rate": format_number(parse_number(item.delta_rate)),
        "tag": detect_tag(item.summary, item.delta_amount),
        "summary": item.summary,
        "source": item.source or "待补来源",
        "url": item.url,
    }


def build_hotspot_items(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Hotspot file must be a JSON array.")

    items: list[dict[str, Any]] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        items.append(
            {
                "date": clean_text(raw.get("date")),
                "title": clean_text(raw.get("title")),
                "kind": clean_text(raw.get("kind")) or "行业热点",
                "summary": clean_text(raw.get("summary")),
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
                spec=clean_text(raw.get("spec")) or "产地快讯",
                unit=clean_text(raw.get("unit")) or "元/kg",
                market=clean_text(raw.get("market")) or "产地",
                location=clean_text(raw.get("location")),
                today_price=clean_text(raw.get("today_price")),
                yesterday_price=clean_text(raw.get("yesterday_price")),
                delta_amount=clean_text(raw.get("delta_amount")),
                delta_rate=clean_text(raw.get("delta_rate")),
                source=clean_text(raw.get("source")),
                url=clean_text(raw.get("url")),
                summary=clean_text(raw.get("summary")),
                price_label=clean_text(raw.get("price_label")),
            )
        )
    return records


def dedupe_records(records: list[WorkbookRecord]) -> list[WorkbookRecord]:
    seen: set[tuple[str, str, str, str, str, str]] = set()
    output: list[WorkbookRecord] = []
    for record in records:
        key = (
            clean_text(record.date),
            clean_text(record.market),
            clean_text(record.herb),
            clean_text(record.location),
            clean_text(record.source),
            clean_text(record.summary),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    return output


def build_dashboard(records: list[WorkbookRecord], source_label: str, hotspot_path: Path | None) -> dict[str, Any]:
    records = sorted(records, key=item_sort_key, reverse=True)
    latest_date = records[0].date if records else ""
    dates = sorted({record.date for record in records if record.date}, reverse=True)
    sources = Counter(record.source for record in records if record.source)
    herbs = Counter(record.herb for record in records if record.herb)
    origin_records = [record for record in records if record.market == "产地"]
    market_records = [record for record in records if record.market != "产地"]
    origin_sources = Counter(record.source for record in origin_records if record.source)
    origin_items = [to_origin_item(record) for record in origin_records]
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
            "eyebrow": "产地行情 / 天天行情 / 行业热点",
            "title": "先把真实记录摊开，再做判断与趋势。",
            "lead": "首页围绕中药材真实记录来搭建：产地行情完整铺开，天天行情优先补齐亳州、安国、玉林，行业热点单独维护，不和报价信息混在一起。",
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
            "title": "天天行情",
            "targets": MARKET_TARGETS,
            "total": len(market_items),
            "covered_count": sum(1 for group in market_groups if group["name"] in MARKET_TARGETS and group["count"] > 0),
            "extra_market_count": sum(1 for group in market_groups if group["name"] not in MARKET_TARGETS and group["count"] > 0),
            "groups": market_groups,
            "empty_text": "当前市场行情记录还不完整，后续会继续补齐药通网天天行情。",
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
            "right": "站点结构已兼容后续继续补药通网天天行情与行业热点。",
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
    records = dedupe_records(records + openclaw_records + market_json_records)

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
