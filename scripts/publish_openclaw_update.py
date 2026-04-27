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
    parser = argparse.ArgumentParser(description="从 OpenClaw 更新产地行情并发布到 GitHub")
    parser.add_argument(
        "--workspace",
        default="/Users/bohao/.codex/automations/qgyc/workspace",
        help="Codex 自动化工作目录",
    )
    parser.add_argument(
        "--input",
        default=None,
        help="指定单个 OpenClaw JSON 文件；不传则自动选择最新文件",
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="git remote 名称",
    )
    parser.add_argument(
        "--branch",
        default="main",
        help="git 分支名称",
    )
    parser.add_argument(
        "--commit-message",
        default="更新产地与市场行情数据",
        help="git 提交信息",
    )
    parser.add_argument(
        "--target-date",
        default=None,
        help="市场行情目标日期；默认今天",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="只提交不推送",
    )
    args = parser.parse_args()

    market_fetcher = root / "scripts" / "fetch_market_updates.py"
    updater = root / "scripts" / "update_from_openclaw.py"
    tracked_files = [
        "content/openclaw_origin.json",
        "content/market_updates.json",
        "public/data/dashboard.json",
    ]

    market_cmd = [sys.executable, str(market_fetcher)]
    if args.target_date:
        market_cmd.extend(["--target-date", args.target_date])
    run(market_cmd, cwd=root)

    update_cmd = [
        sys.executable,
        str(updater),
        "--workspace",
        args.workspace,
    ]
    if args.input:
        update_cmd.extend(["--input", args.input])
    run(update_cmd, cwd=root)

    if not has_relevant_changes(root, tracked_files):
        print("No origin updates found. Nothing to commit.")
        return

    stage_and_publish(
        root=root,
        files=tracked_files,
        message=args.commit_message,
        remote=args.remote,
        branch=args.branch,
        push=not args.no_push,
    )
    print("Published OpenClaw origin update.")


if __name__ == "__main__":
    main()
