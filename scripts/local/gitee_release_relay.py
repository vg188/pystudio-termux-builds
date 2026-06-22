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


def format_bytes(value: float) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(value)
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{size:.0f} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PiB"


def format_speed(bytes_per_second: float) -> str:
    return f"{format_bytes(bytes_per_second)}/s"


def first_env_value(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def read_text_preview(path: Path, limit: int = 4000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... response truncated ..."


class TransferProgress:
    def __init__(
        self,
        action: str,
        name: str,
        total: int | None,
        initial: int = 0,
        interval: float = 0.5,
    ) -> None:
        self.action = action
        self.name = name
        self.total = total
        self.initial = initial
        self.current = initial
        self.interval = interval
        self.started_at = time.monotonic()
        self.last_render_at = 0.0
        self.last_line_length = 0
        self.is_tty = sys.stderr.isatty()
        self.render(force=True)

    def update(self, amount: int) -> None:
        self.current += amount
        now = time.monotonic()
        if now - self.last_render_at >= self.interval:
            self.render()

    def render(self, force: bool = False, done: bool = False) -> None:
        now = time.monotonic()
        if not force and not done and now - self.last_render_at < self.interval:
            return
        self.last_render_at = now
        elapsed = max(now - self.started_at, 0.001)
        transferred = max(self.current - self.initial, 0)
        speed = transferred / elapsed

        if self.total:
            percent = min(self.current / self.total * 100, 100.0)
            progress = f"{percent:6.2f}% {format_bytes(self.current)}/{format_bytes(self.total)}"
        else:
            progress = f"{format_bytes(self.current)}"

        line = f"{self.action}: {self.name} {progress} {format_speed(speed)}"
        if done:
            line += f" in {elapsed:.1f}s"

        if self.is_tty:
            padding = " " * max(0, self.last_line_length - len(line))
            print("\r" + line + padding, end="" if not done else "\n", file=sys.stderr, flush=True)
            self.last_line_length = len(line)
        else:
            print(line, file=sys.stderr, flush=True)

    def finish(self) -> None:
        self.render(force=True, done=True)


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
    progress_interval: float,
) -> None:
    if destination.exists() and not force:
        print(f"Download exists, skipping: {destination.name} ({format_bytes(destination.stat().st_size)})")
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
        progress: TransferProgress | None = None
        try:
            with urllib.request.urlopen(request, timeout=URL_TIMEOUT) as response:
                if resume_from > 0 and getattr(response, "status", 200) != 206:
                    print(f"Server ignored resume for {destination.name}; restarting download.")
                    partial.unlink(missing_ok=True)
                    resume_from = 0
                    mode = "wb"
                else:
                    mode = "ab" if resume_from > 0 else "wb"
                content_length = response.headers.get("Content-Length")
                remaining = int(content_length) if content_length and content_length.isdigit() else None
                total = resume_from + remaining if remaining is not None else None
                progress = TransferProgress(
                    "Downloading",
                    destination.name,
                    total=total,
                    initial=resume_from,
                    interval=progress_interval,
                )
                with partial.open(mode + "") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        progress.update(len(chunk))
            partial.replace(destination)
            if progress:
                progress.finish()
            print(f"Downloaded: {destination.name} ({format_bytes(destination.stat().st_size)})")
            return
        except Exception as exc:
            if progress:
                progress.finish()
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
        print(f"Remote asset exists, skipping: {file_path.name} ({format_bytes(file_path.stat().st_size)})")
        return

    file_size = file_path.stat().st_size
    response_dir = Path(args.cache_dir) / "upload-responses"
    response_dir.mkdir(parents=True, exist_ok=True)
    response_path = response_dir / f"{safe_part(file_path.name)}.response.txt"
    response_path.unlink(missing_ok=True)
    url = (
        f"https://gitee.com/api/v5/repos/{args.gitee_owner}/{args.gitee_repo}"
        f"/releases/{release_id}/attach_files"
    )
    command = [
        args.curl_path,
        "--fail-with-body",
        "--show-error",
        "--location",
        "--retry",
        str(args.upload_retries),
        "--connect-timeout",
        str(args.connect_timeout),
        "--max-time",
        str(args.upload_timeout),
        "--output",
        str(response_path),
        "--write-out",
        (
            f"\nUploaded: {file_path.name} ({format_bytes(file_size)}) "
            "in %{time_total}s, average upload speed %{speed_upload} B/s\n"
        ),
        "-F",
        f"access_token={token}",
        "-F",
        f"file=@{file_path.resolve()};filename={file_path.name}",
        url,
    ]
    print(f"Uploading: {file_path.name} ({format_bytes(file_size)})")
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        response_text = read_text_preview(response_path).strip()
        message = (
            f"Upload failed for {file_path.name} with curl exit code {result.returncode}. "
            f"Gitee response was saved to {response_path}."
        )
        if response_text:
            message += f"\nGitee response:\n{response_text}"
        else:
            message += "\nGitee did not return a response body."
        raise RuntimeError(message)
    existing_assets.add(file_path.name)


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

    gitee_token = args.gitee_token or first_env_value("gitee_yourba", "GITEE_YOURBA", "GITEE_TOKEN")
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
        download_asset(
            url,
            destination,
            github_token,
            args.download_retries,
            args.force_download,
            args.progress_interval,
        )
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
    parser.add_argument("--progress-interval", type=float, default=0.5)
    parser.add_argument("--connect-timeout", type=int, default=60)
    parser.add_argument("--upload-timeout", type=int, default=7200)
    parser.add_argument("--curl-path", default="curl")
    return parser.parse_args()


def main() -> int:
    try:
        run(parse_args())
        return 0
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
