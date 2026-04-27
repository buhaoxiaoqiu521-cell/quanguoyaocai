#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import time
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


def has_staged_changes(root: Path, files: list[str]) -> bool:
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", *files],
        cwd=str(root),
        text=True,
    )
    if result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(result.returncode, result.args)
    return result.returncode == 1


def has_pending_local_commits(root: Path, remote: str, branch: str) -> bool:
    result = run(["git", "rev-list", "--left-right", "--count", f"{branch}...{remote}/{branch}"], cwd=root, capture=True)
    ahead, _behind = (int(part) for part in result.stdout.strip().split())
    return ahead > 0


def stage_and_publish(root: Path, files: list[str], message: str, remote: str, branch: str, push: bool) -> None:
    run(["git", "add", "--", *files], cwd=root)
    if has_staged_changes(root, files):
        run(["git", "commit", "-m", message], cwd=root)
    if push:
        push_with_retry(root, remote, branch)


def push_with_retry(root: Path, remote: str, branch: str) -> None:
    attempts = [
        ["git", "push", remote, branch],
        ["git", "-c", "http.version=HTTP/1.1", "push", remote, branch],
        [
            "git",
            "-c",
            "http.version=HTTP/1.1",
            "-c",
            "http.lowSpeedTime=90",
            "-c",
            "http.lowSpeedLimit=1",
            "push",
            remote,
            branch,
        ],
    ]
    last_error: subprocess.CalledProcessError | None = None
    for index, cmd in enumerate(attempts, start=1):
        try:
            run(cmd, cwd=root)
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            if index < len(attempts):
                time.sleep(10)
    if last_error is not None:
        raise last_error


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
    tracked_files = [
        market_file,
        "public/data/dashboard.json",
        "public/data/origin-search-index.json",
        "public/data/market-search-index.json",
        "public/data/hotspot-search-index.json",
        "public/data/unit-audit.json",
    ]

    market_cmd = [sys.executable, str(market_fetcher)]
    if args.target_date:
        market_cmd.extend(["--target-date", args.target_date])
    run(market_cmd, cwd=root)

    content_changed = has_relevant_changes(root, [market_file])
    pending_push = has_pending_local_commits(root, args.remote, args.branch)

    if not content_changed and not pending_push:
        print("No market changes found. Nothing to publish.")
        return

    if content_changed:
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
    if content_changed:
        print("Published market update.")
    else:
        print("Pushed pending market update.")


if __name__ == "__main__":
    main()
