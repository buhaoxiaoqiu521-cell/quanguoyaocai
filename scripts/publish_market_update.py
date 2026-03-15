#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        check=True,
        text=True,
        capture_output=capture,
    )


def has_relevant_changes(root: Path, files: list[str]) -> bool:
    result = run(["git", "status", "--short", "--", *files], cwd=root, capture=True)
    return bool(result.stdout.strip())


def stage_and_publish(root: Path, files: list[str], message: str, remote: str, branch: str, push: bool) -> None:
    run(["git", "add", "--", *files], cwd=root)
    run(["git", "commit", "-m", message], cwd=root)
    if push:
        run(["git", "push", remote, branch], cwd=root)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="发布市场行情更新到 GitHub")
    parser.add_argument("--target-date", default=None, help="市场行情目标日期；默认今天")
    parser.add_argument("--remote", default="origin", help="git remote 名称")
    parser.add_argument("--branch", default="main", help="git 分支名称")
    parser.add_argument("--commit-message", default="更新市场行情数据", help="git 提交信息")
    parser.add_argument("--no-push", action="store_true", help="只提交不推送")
    args = parser.parse_args()

    market_fetcher = root / "scripts" / "fetch_market_updates.py"
    build_script = root / "scripts" / "build_dashboard_data.py"
    market_file = "content/market_updates.json"
    tracked_files = [market_file, "public/data/dashboard.json"]

    market_cmd = [sys.executable, str(market_fetcher)]
    if args.target_date:
        market_cmd.extend(["--target-date", args.target_date])
    run(market_cmd, cwd=root)

    if not has_relevant_changes(root, [market_file]):
        print("No market changes found. Nothing to publish.")
        return

    build_cmd = [
        sys.executable,
        str(build_script),
        "--exclude-workbook-origin",
        "--exclude-workbook-market",
    ]
    run(build_cmd, cwd=root)

    stage_and_publish(
        root=root,
        files=tracked_files,
        message=args.commit_message,
        remote=args.remote,
        branch=args.branch,
        push=not args.no_push,
    )
    print("Published market update.")


if __name__ == "__main__":
    main()
