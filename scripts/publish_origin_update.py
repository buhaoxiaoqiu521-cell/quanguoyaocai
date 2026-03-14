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
    parser = argparse.ArgumentParser(description="发布产地行情更新到 GitHub")
    parser.add_argument("--workspace", default="/Users/bohao/.openclaw/workspace", help="OpenClaw 工作目录")
    parser.add_argument("--input", default=None, help="指定单个 OpenClaw JSON 文件；不传则自动选择最新文件")
    parser.add_argument("--remote", default="origin", help="git remote 名称")
    parser.add_argument("--branch", default="main", help="git 分支名称")
    parser.add_argument("--commit-message", default="更新产地行情数据", help="git 提交信息")
    parser.add_argument("--no-push", action="store_true", help="只提交不推送")
    args = parser.parse_args()

    updater = root / "scripts" / "update_from_openclaw.py"
    origin_file = "content/openclaw_origin.json"
    tracked_files = [origin_file, "public/data/dashboard.json"]

    update_cmd = [
        sys.executable,
        str(updater),
        "--workspace",
        args.workspace,
    ]
    if args.input:
        update_cmd.extend(["--input", args.input])
    run(update_cmd, cwd=root)

    if not has_relevant_changes(root, [origin_file]):
        print("No origin changes found. Nothing to publish.")
        return

    stage_and_publish(
        root=root,
        files=tracked_files,
        message=args.commit_message,
        remote=args.remote,
        branch=args.branch,
        push=not args.no_push,
    )
    print("Published origin update.")


if __name__ == "__main__":
    main()
