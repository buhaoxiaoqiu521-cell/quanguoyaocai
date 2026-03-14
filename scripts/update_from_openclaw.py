#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="从 OpenClaw 抓取缓存更新网站产地行情数据")
    parser.add_argument(
        "--workspace",
        default="/Users/bohao/.openclaw/workspace",
        help="OpenClaw 工作目录",
    )
    parser.add_argument(
        "--input",
        default=None,
        help="指定单个 OpenClaw JSON 文件；不传则自动选择最新文件",
    )
    parser.add_argument(
        "--origin-output",
        default=str(root / "content" / "openclaw_origin.json"),
        help="网站侧产地行情缓存输出路径",
    )
    parser.add_argument(
        "--dashboard-output",
        default=str(root / "public" / "data" / "dashboard.json"),
        help="dashboard.json 输出路径",
    )
    parser.add_argument(
        "--hotspots",
        default=str(root / "content" / "hotspots.json"),
        help="行业热点 JSON 路径",
    )
    args = parser.parse_args()

    import_script = root / "scripts" / "import_openclaw_origin.py"
    build_script = root / "scripts" / "build_dashboard_data.py"

    import_cmd = [
        sys.executable,
        str(import_script),
        "--workspace",
        args.workspace,
        "--output",
        args.origin_output,
    ]
    if args.input:
        import_cmd.extend(["--input", args.input])
    run(import_cmd)

    build_cmd = [
        sys.executable,
        str(build_script),
        "--openclaw-origin",
        args.origin_output,
        "--hotspots",
        args.hotspots,
        "--output",
        args.dashboard_output,
    ]
    run(build_cmd)


if __name__ == "__main__":
    main()
