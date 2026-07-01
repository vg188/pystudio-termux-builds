#!/usr/bin/env python3
"""Update lightweight files in a Gitee repository through the contents API."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


API_BASE = "https://gitee.com/api/v5"
USER_AGENT = "pystudio-gitee-light-index"


def first_env_value(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def encode_path(path: str) -> str:
    return urllib.parse.quote(path.strip("/"), safe="/")


def api_url(owner: str, repo: str, path: str, query: dict[str, str] | None = None) -> str:
    base = f"{API_BASE}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/contents/{encode_path(path)}"
    if query:
        return base + "?" + urllib.parse.urlencode(query)
    return base


def request_json(
    *,
    method: str,
    owner: str,
    repo: str,
    path: str,
    token: str,
    branch: str,
    payload: dict[str, str] | None = None,
    retries: int = 5,
    timeout: int = 60,
) -> dict[str, Any] | None:
    query = {"access_token": token}
    if method == "GET":
        query["ref"] = branch
    url = api_url(owner, repo, path, query if method == "GET" else None)
    data = None
    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if payload is not None:
        form = {"access_token": token, **payload}
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                if not body:
                    return None
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 404 and method == "GET":
                return None
            if exc.code in {429, 500, 502, 503, 504} and attempt < retries:
                delay = min(120, attempt * 15)
                print(f"Warning: Gitee {method} {path} failed with HTTP {exc.code}; retrying in {delay}s.")
                time.sleep(delay)
                continue
            raise RuntimeError(f"Gitee {method} {path} failed with HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            if attempt < retries:
                delay = min(120, attempt * 15)
                print(f"Warning: Gitee {method} {path} failed: {exc}; retrying in {delay}s.")
                time.sleep(delay)
                continue
            raise RuntimeError(f"Gitee {method} {path} failed: {exc}") from exc
    return None


def decode_remote_content(remote: dict[str, Any] | None) -> bytes | None:
    if not remote:
        return None
    content = str(remote.get("content", ""))
    if not content:
        return None
    return base64.b64decode("".join(content.split()))


def update_file(
    *,
    owner: str,
    repo: str,
    branch: str,
    token: str,
    local_path: Path,
    remote_path: str,
    message: str,
    retries: int,
    timeout: int,
) -> str:
    local_bytes = local_path.read_bytes()
    print(f"Gitee check: {remote_path} ({local_path.stat().st_size} bytes)", flush=True)
    remote = request_json(
        method="GET",
        owner=owner,
        repo=repo,
        path=remote_path,
        token=token,
        branch=branch,
        retries=retries,
        timeout=timeout,
    )
    remote_bytes = decode_remote_content(remote)
    if remote_bytes == local_bytes:
        print(f"Gitee unchanged: {remote_path} ({local_path.stat().st_size} bytes)", flush=True)
        return "unchanged"

    payload = {
        "branch": branch,
        "message": message,
        "content": base64.b64encode(local_bytes).decode("ascii"),
    }
    method = "POST"
    if remote:
        sha = str(remote.get("sha", ""))
        if sha:
            payload["sha"] = sha
        method = "PUT"

    print(f"Gitee {method}: {remote_path} ({local_path.stat().st_size} bytes)", flush=True)
    request_json(
        method=method,
        owner=owner,
        repo=repo,
        path=remote_path,
        token=token,
        branch=branch,
        payload=payload,
        retries=retries,
        timeout=timeout,
    )
    print(f"Gitee updated: {remote_path} ({local_path.stat().st_size} bytes)", flush=True)
    return "updated"


def parse_file_mapping(value: str) -> tuple[Path, str]:
    local, sep, remote = value.partition("=")
    if not sep or not local or not remote:
        raise argparse.ArgumentTypeError("--file must use LOCAL=REMOTE")
    return Path(local), remote.strip("/")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default=os.environ.get("GITEE_OWNER", "yourba"))
    parser.add_argument("--repo", default=os.environ.get("GITEE_REPO", "pystudio-termux-builds"))
    parser.add_argument("--branch", default=os.environ.get("GITEE_BRANCH", "main"))
    parser.add_argument("--token", default=first_env_value("GITEE_TOKEN", "gitee_yourba", "GITEE_YOURBA"))
    parser.add_argument("--message", default="chore: update runtime package mirror index")
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    parser.add_argument("--file", action="append", type=parse_file_mapping, required=True, help="LOCAL=REMOTE")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.token:
        print("GITEE_TOKEN is not configured; skipping Gitee file updates.")
        return 0

    updated = 0
    unchanged = 0
    for local_path, remote_path in args.file:
        if not local_path.exists():
            raise RuntimeError(f"local file does not exist: {local_path}")
        result = update_file(
            owner=args.owner,
            repo=args.repo,
            branch=args.branch,
            token=args.token,
            local_path=local_path,
            remote_path=remote_path,
            message=args.message,
            retries=args.retries,
            timeout=args.timeout,
        )
        updated += int(result == "updated")
        unchanged += int(result == "unchanged")
    print(f"Gitee file update complete: {updated} updated, {unchanged} unchanged.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
