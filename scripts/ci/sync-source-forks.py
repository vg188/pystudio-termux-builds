#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
SOURCES_DIR = ROOT / "sources"


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        values[key] = value
    return values


def api_request(token: str, method: str, url: str, payload: dict[str, str] | None = None) -> dict:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "pystudio-source-fork-sync",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


def branch_for_fork(token: str, fork_repo: str) -> str:
    repo = api_request(token, "GET", f"https://api.github.com/repos/{fork_repo}")
    return str(repo.get("default_branch") or "master")


def sync_fork(token: str, fork_repo: str, branch: str) -> tuple[str, str]:
    try:
        response = api_request(
            token,
            "POST",
            f"https://api.github.com/repos/{fork_repo}/merge-upstream",
            {"branch": branch},
        )
        return "synced", str(response.get("message", "sync requested"))
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        if exc.code == 409:
            return "conflict", message
        if exc.code == 422 and re.search(r"up.to.date|no commits", message, re.I):
            return "up-to-date", message
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync clean PyStudio source forks with upstream.")
    parser.add_argument("--sources-dir", type=Path, default=SOURCES_DIR)
    parser.add_argument("--token", default=os.environ.get("SOURCE_SYNC_TOKEN") or os.environ.get("GITHUB_TOKEN"))
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("SOURCE_SYNC_TOKEN is required")

    results: list[dict[str, str]] = []
    for source_file in sorted(args.sources_dir.glob("*.env")):
        env = parse_env_file(source_file)
        source_id = env.get("SOURCE_ID", source_file.stem)
        fork_repo = env.get("SOURCE_FORK_REPO", "")
        if not fork_repo:
            results.append({"source": source_id, "status": "skipped", "message": "SOURCE_FORK_REPO is not set"})
            continue

        branch = branch_for_fork(args.token, fork_repo)
        status, message = sync_fork(args.token, fork_repo, branch)
        results.append(
            {
                "source": source_id,
                "fork": fork_repo,
                "branch": branch,
                "status": status,
                "message": message,
            }
        )

    print(json.dumps(results, indent=2, ensure_ascii=False))
    conflicts = [item for item in results if item.get("status") == "conflict"]
    return 1 if conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
