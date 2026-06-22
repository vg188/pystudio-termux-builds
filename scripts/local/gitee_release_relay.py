#!/usr/bin/env python3
"""Mirror runtime package assets through the local machine to Gitee.

This tool is intended to run on a developer PC. It downloads GitHub release
assets listed in runtime-packages.json into a local cache, uploads them to one
Gitee release, then updates runtime-packages.json in the Gitee repository.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


GITHUB_RELEASE_RE = re.compile(
    r"^https://github\.com/([^/]+)/([^/]+)/releases/download/([^/]+)/(.+)$"
)
URL_TIMEOUT = 120
USER_AGENT = "pystudio-local-gitee-relay"


def safe_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._+-]+", "_", value).strip("_")


def mirrored_filename(url: str) -> str:
    match = GITHUB_RELEASE_RE.match(url)
    if not match:
        raise ValueError(f"Unsupported runtime asset URL: {url}")
    _owner, repo, tag, asset = match.groups()
    asset_name = Path(urllib.parse.unquote(asset)).name
    return f"{safe_part(repo)}--{safe_part(tag)}--{asset_name}"


def gitee_release_url(owner: str, repo: str, tag: str, filename: str) -> str:
    quoted_tag = urllib.parse.quote(tag, safe="")
    quoted_file = urllib.parse.quote(filename, safe="")
    return f"https://gitee.com/{owner}/{repo}/releases/download/{quoted_tag}/{quoted_file}"


def iter_url_values(node: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str) and key.endswith("Url"):
                urls.append(value)
            else:
                urls.extend(iter_url_values(value))
    elif isinstance(node, list):
        for item in node:
            urls.extend(iter_url_values(item))
    return urls


def rewrite_urls(node: Any, replacements: dict[str, str]) -> Any:
    if isinstance(node, dict):
        rewritten: dict[str, Any] = {}
        for key, value in node.items():
            if isinstance(value, str) and key.endswith("Url"):
                rewritten[key] = replacements.get(value, value)
            else:
                rewritten[key] = rewrite_urls(value, replacements)
        return rewritten
    if isinstance(node, list):
        return [rewrite_urls(item, replacements) for item in node]
    return node


def http_json(
    method: str,
    url: str,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    form: dict[str, str] | None = None,
) -> Any:
    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=URL_TIMEOUT) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: HTTP {exc.code}: {detail}") from exc

    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def read_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def source_urls_from_manifest(manifest: dict[str, Any], include_pattern: str | None) -> list[str]:
    urls = sorted(set(iter_url_values(manifest)))
    urls = [url for url in urls if url.startswith("https://github.com/")]
    if include_pattern:
        regex = re.compile(include_pattern)
        urls = [url for url in urls if regex.search(url)]
    return urls


def download_asset(
    url: str,
    destination: Path,
    github_token: str | None,
    retries: int,
    force: bool,
) -> None:
    if destination.exists() and not force:
        print(f"Download exists, skipping: {destination.name}")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    resume_from = partial.stat().st_size if partial.exists() and not force else 0
    if force and partial.exists():
        partial.unlink()
        resume_from = 0

    for attempt in range(1, retries + 1):
        headers = {"User-Agent": USER_AGENT}
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"
        if resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"

        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=URL_TIMEOUT) as response:
                if resume_from > 0 and getattr(response, "status", 200) != 206:
                    print(f"Server ignored resume for {destination.name}; restarting download.")
                    partial.unlink(missing_ok=True)
                    resume_from = 0
                    mode = "wb"
                else:
                    mode = "ab" if resume_from > 0 else "wb"
                with partial.open(mode + "") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
            partial.replace(destination)
            print(f"Downloaded: {destination.name}")
            return
        except Exception as exc:
            if attempt >= retries:
                raise
            wait = min(60, 5 * attempt)
            print(f"Download failed ({attempt}/{retries}) for {destination.name}: {exc}; retrying in {wait}s")
            time.sleep(wait)
            resume_from = partial.stat().st_size if partial.exists() else 0


def find_release(owner: str, repo: str, token: str, tag: str) -> dict[str, Any] | None:
    for page in range(1, 11):
        url = (
            f"https://gitee.com/api/v5/repos/{owner}/{repo}/releases"
            f"?access_token={urllib.parse.quote(token)}&per_page=100&page={page}"
        )
        releases = http_json("GET", url)
        if not releases:
            return None
        for release in releases:
            if release.get("tag_name") == tag:
                return release
    return None


def create_or_reuse_release(args: argparse.Namespace, token: str) -> dict[str, Any]:
    existing = find_release(args.gitee_owner, args.gitee_repo, token, args.gitee_tag)
    if existing:
        print(f"Reusing Gitee release {args.gitee_tag} with id {existing['id']}.")
        return existing

    form = {
        "access_token": token,
        "tag_name": args.gitee_tag,
        "target_commitish": args.gitee_branch,
        "name": args.release_name or f"PyStudio runtime packages {args.gitee_tag}",
        "body": args.release_body,
        "prerelease": "false",
    }
    url = f"https://gitee.com/api/v5/repos/{args.gitee_owner}/{args.gitee_repo}/releases"
    release = http_json("POST", url, form=form)
    print(f"Created Gitee release {args.gitee_tag} with id {release['id']}.")
    return release


def release_asset_names(release: dict[str, Any]) -> set[str]:
    return {
        asset["name"]
        for asset in release.get("assets", [])
    }


def upload_asset(
    args: argparse.Namespace,
    token: str,
    release_id: str,
    file_path: Path,
    existing_assets: set[str],
) -> None:
    if file_path.name in existing_assets and not args.force_upload:
        print(f"Remote asset exists, skipping: {file_path.name}")
        return

    url = (
        f"https://gitee.com/api/v5/repos/{args.gitee_owner}/{args.gitee_repo}"
        f"/releases/{release_id}/attach_files"
    )
    command = [
        args.curl_path,
        "--fail",
        "--show-error",
        "--location",
        "--retry",
        str(args.upload_retries),
        "--retry-all-errors",
        "--connect-timeout",
        str(args.connect_timeout),
        "--max-time",
        str(args.upload_timeout),
        "-F",
        f"access_token={token}",
        "-F",
        f"file=@{file_path.resolve()};filename={file_path.name}",
        url,
    ]
    print(f"Uploading: {file_path.name}")
    subprocess.run(command, check=True)


def update_gitee_file(
    owner: str,
    repo: str,
    token: str,
    branch: str,
    path: str,
    content: bytes,
    message: str,
) -> None:
    encoded_path = urllib.parse.quote(path, safe="/")
    get_url = (
        f"https://gitee.com/api/v5/repos/{owner}/{repo}/contents/{encoded_path}"
        f"?access_token={urllib.parse.quote(token)}&ref={urllib.parse.quote(branch)}"
    )
    sha = None
    try:
        current = http_json("GET", get_url)
        sha = current.get("sha")
    except RuntimeError as exc:
        if "HTTP 404" not in str(exc):
            raise

    payload = {
        "access_token": token,
        "content": base64.b64encode(content).decode("ascii"),
        "message": message,
        "branch": branch,
    }
    method = "PUT" if sha else "POST"
    if sha:
        payload["sha"] = sha
    update_url = f"https://gitee.com/api/v5/repos/{owner}/{repo}/contents/{encoded_path}"
    http_json(method, update_url, form=payload)
    print(f"Updated Gitee file: {path}")


def default_tag() -> str:
    return "pystudio-runtime-packages-local-" + datetime.now().strftime("%Y%m%d-%H%M%S")


def run(args: argparse.Namespace) -> None:
    github_token = args.github_token or os.environ.get("GITHUB_TOKEN")

    manifest = read_manifest(Path(args.manifest))
    urls = source_urls_from_manifest(manifest, args.include)
    if args.max_assets:
        urls = urls[: args.max_assets]
    if not urls:
        raise RuntimeError("No GitHub release URLs found in manifest.")
    if args.dry_run:
        print(f"Dry run: {len(urls)} assets would be mirrored to {args.gitee_owner}/{args.gitee_repo}.")
        print(f"Gitee tag: {args.gitee_tag}")
        for url in urls:
            filename = mirrored_filename(url)
            print(f"{url} -> {gitee_release_url(args.gitee_owner, args.gitee_repo, args.gitee_tag, filename)}")
        return

    gitee_token = args.gitee_token or os.environ.get("GITEE_TOKEN")
    if not gitee_token:
        gitee_token = getpass.getpass("Gitee token: ")

    cache_dir = Path(args.cache_dir)
    asset_dir = cache_dir / "assets"
    manifest_dir = cache_dir / "manifest"
    asset_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    replacements: dict[str, str] = {}
    local_files: list[Path] = []
    for url in urls:
        filename = mirrored_filename(url)
        destination = asset_dir / filename
        download_asset(url, destination, github_token, args.download_retries, args.force_download)
        replacements[url] = gitee_release_url(args.gitee_owner, args.gitee_repo, args.gitee_tag, filename)
        local_files.append(destination)

    mirrored_manifest = rewrite_urls(manifest, replacements)
    manifest_bytes = (json.dumps(mirrored_manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    manifest_path = manifest_dir / "runtime-packages.json"
    manifest_path.write_bytes(manifest_bytes)
    print(f"Generated local Gitee manifest: {manifest_path}")

    release = create_or_reuse_release(args, gitee_token)
    release_id = str(release["id"])
    existing_assets = release_asset_names(release)
    for local_file in local_files:
        upload_asset(args, gitee_token, release_id, local_file, existing_assets)

    upload_asset(args, gitee_token, release_id, manifest_path, existing_assets)
    update_gitee_file(
        args.gitee_owner,
        args.gitee_repo,
        gitee_token,
        args.gitee_branch,
        "runtime-packages.json",
        manifest_bytes,
        "chore: update runtime package mirror links",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="runtime-packages.json")
    parser.add_argument("--cache-dir", default="work/gitee-relay")
    parser.add_argument("--gitee-owner", default="yourba")
    parser.add_argument("--gitee-repo", default="pystudio-termux-builds")
    parser.add_argument("--gitee-branch", default="main")
    parser.add_argument("--gitee-tag", default=default_tag())
    parser.add_argument("--release-name", default="")
    parser.add_argument("--release-body", default="Mirrored through local PyStudio relay.")
    parser.add_argument("--gitee-token", default="")
    parser.add_argument("--github-token", default="")
    parser.add_argument("--include", default="", help="Optional regex filter for source URLs.")
    parser.add_argument("--max-assets", type=int, default=0, help="Limit assets for a smoke test.")
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--force-upload", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--download-retries", type=int, default=5)
    parser.add_argument("--upload-retries", type=int, default=8)
    parser.add_argument("--connect-timeout", type=int, default=60)
    parser.add_argument("--upload-timeout", type=int, default=7200)
    parser.add_argument("--curl-path", default="curl")
    return parser.parse_args()


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    sys.exit(main())
