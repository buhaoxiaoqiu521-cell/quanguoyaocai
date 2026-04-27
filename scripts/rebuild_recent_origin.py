#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


def run_json(cmd: list[str], cwd: Path) -> dict:
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def dedupe(records: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str, str, str]] = set()
    merged: list[dict] = []
    for raw in records:
        item = {
            "date": str(raw.get("date", "")).strip(),
            "herb": str(raw.get("herb", "")).strip(),
            "spec": str(raw.get("spec", "")).strip(),
            "unit": str(raw.get("unit", "")).strip(),
            "market": str(raw.get("market", "")).strip(),
            "location": str(raw.get("location", "")).strip(),
            "today_price": str(raw.get("today_price", "")).strip(),
            "yesterday_price": str(raw.get("yesterday_price", "")).strip(),
            "delta_amount": str(raw.get("delta_amount", "")).strip(),
            "delta_rate": str(raw.get("delta_rate", "")).strip(),
            "source": str(raw.get("source", "")).strip(),
            "url": str(raw.get("url", "")).strip(),
            "summary": str(raw.get("summary", "")).strip(),
            "content_full": str(raw.get("content_full", "")).strip(),
            "price_label": str(raw.get("price_label", "")).strip(),
            "price_points": raw.get("price_points") if isinstance(raw.get("price_points"), list) else [],
        }
        if not item["date"] or not item["herb"] or not item["summary"]:
            continue
        key = (item["date"], item["herb"], item["location"], item["source"], item["summary"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    merged.sort(key=lambda item: (item["date"], item["herb"], item["location"]), reverse=True)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="重抓近 N 日产地行情并生成网站产地 JSON")
    parser.add_argument("--days", type=int, default=5, help="抓取近几日，默认 5")
    parser.add_argument("--end-date", default=datetime.now().strftime("%Y-%m-%d"), help="结束日期，默认今天")
    parser.add_argument("--workspace", default="/Users/bohao/.codex/automations/qgyc/workspace", help="Codex 自动化工作目录")
    parser.add_argument("--output", default="content/openclaw_origin.json", help="输出路径")
    parser.add_argument("--yt-pages", type=int, default=4, help="药通网分页深度")
    parser.add_argument("--zy-pages", type=int, default=28, help="天地网分页深度")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    root = Path(__file__).resolve().parents[1]
    output_path = Path(args.output).expanduser().resolve()
    brief_script = workspace / "herb_market_brief.py"
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()

    all_records: list[dict] = []
    fetched_dates: list[str] = []
    for offset in range(args.days):
        day = end_date - timedelta(days=offset)
        day_text = day.strftime("%Y-%m-%d")
        payload = run_json(
            [
                sys.executable,
                str(brief_script),
                "--date",
                day_text,
                "--yt-pages",
                str(args.yt_pages),
                "--zy-pages",
                str(args.zy_pages),
                "--json",
            ],
            cwd=workspace,
        )
        fetched_dates.append(day_text)
        if isinstance(payload.get("origin_records"), list):
            all_records.extend(item for item in payload["origin_records"] if isinstance(item, dict))

    merged = dedupe(all_records)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output_path),
                "days": args.days,
                "dates": fetched_dates,
                "records": len(merged),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
