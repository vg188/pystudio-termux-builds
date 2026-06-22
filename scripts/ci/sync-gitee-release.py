#!/usr/bin/env python3
"""Mirror runtime package assets to a single Gitee release."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


GITHUB_RELEASE_RE = re.compile(
    r"^https://github\.com/([^/]+)/([^/]+)/releases/download/([^/]+)/(.+)$"
)


def gitee_release_url(owner: str, repo: str, tag: str, filename: str) -> str:
    quoted_tag = urllib.parse.quote(tag, safe="")
    quoted_file = urllib.parse.quote(filename, safe="")
    return f"https://gitee.com/{owner}/{repo}/releases/download/{quoted_tag}/{quoted_file}"


def safe_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._+-]+", "_", value).strip("_")


def mirrored_filename(url: str) -> str:
    match = GITHUB_RELEASE_RE.match(url)
    if not match:
        raise ValueError(f"Unsupported runtime asset URL: {url}")
    _owner, repo, tag, asset = match.groups()
    asset_name = Path(urllib.parse.unquote(asset)).name
    return f"{safe_part(repo)}--{safe_part(tag)}--{asset_name}"


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
        rewritten = {}
        for key, value in node.items():
            if isinstance(value, str) and key.endswith("Url"):
                rewritten[key] = replacements.get(value, value)
            else:
                rewritten[key] = rewrite_urls(value, replacements)
        return rewritten
    if isinstance(node, list):
        return [rewrite_urls(item, replacements) for item in node]
    return node


def download_file(url: str, destination: Path, github_token: str | None) -> None:
    headers = {"User-Agent": "pystudio-gitee-sync"}
    if github_token and url.startswith("https://github.com/"):
        headers["Authorization"] = f"Bearer {github_token}"

    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)


def prepare(args: argparse.Namespace) -> None:
    manifest_path = Path(args.manifest)
    output_dir = Path(args.output_dir)
    files_dir = output_dir / "files"
    output_dir.mkdir(parents=True, exist_ok=True)
    files_dir.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_urls = sorted(set(iter_url_values(manifest)))
    replacements: dict[str, str] = {}
    planned_files: list[dict[str, str]] = []

    for url in source_urls:
        if not url.startswith("https://github.com/"):
            continue
        filename = mirrored_filename(url)
        destination = files_dir / filename
        print(f"Downloading {url} -> {filename}")
        download_file(url, destination, args.github_token)
        replacements[url] = gitee_release_url(args.gitee_owner, args.gitee_repo, args.gitee_tag, filename)
        planned_files.append({"sourceUrl": url, "filename": filename, "giteeUrl": replacements[url]})

    mirrored_manifest = rewrite_urls(manifest, replacements)
    manifest_output = files_dir / "runtime-packages.json"
    manifest_output.write_text(
        json.dumps(mirrored_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "asset-map.json").write_text(
        json.dumps(planned_files, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Prepared {len(planned_files)} mirrored assets.")
    print(f"Generated {manifest_output}")


def api_request(url: str, data: bytes | None, headers: dict[str, str]) -> Any:
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gitee API request failed: {exc.code} {detail}") from exc

    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def create_release(args: argparse.Namespace) -> dict[str, Any]:
    url = f"https://gitee.com/api/v5/repos/{args.gitee_owner}/{args.gitee_repo}/releases"
    form = urllib.parse.urlencode(
        {
            "access_token": args.gitee_token,
            "tag_name": args.gitee_tag,
            "target_commitish": args.target_commitish,
            "name": args.release_name,
            "body": args.release_body,
            "prerelease": "false",
        }
    ).encode("utf-8")
    return api_request(
        url,
        form,
        {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "pystudio-gitee-sync",
        },
    )


def upload_file(args: argparse.Namespace, release_id: str, file_path: Path) -> None:
    url = (
        f"https://gitee.com/api/v5/repos/{args.gitee_owner}/{args.gitee_repo}"
        f"/releases/{release_id}/attach_files"
    )
    subprocess.run(
        [
            "curl",
            "--fail",
            "--show-error",
            "--location",
            "--retry",
            "5",
            "--retry-all-errors",
            "--connect-timeout",
            "60",
            "--max-time",
            "3600",
            "-F",
            f"access_token={args.gitee_token}",
            "-F",
            f"file=@{file_path}",
            url,
        ],
        check=True,
    )


def publish(args: argparse.Namespace) -> None:
    files_dir = Path(args.files_dir)
    files = sorted(path for path in files_dir.iterdir() if path.is_file())
    if not files:
        raise RuntimeError(f"No files found in {files_dir}")

    release = create_release(args)
    release_id = str(release["id"])
    print(f"Created Gitee release {args.gitee_tag} with id {release_id}.")

    for file_path in files:
        print(f"Uploading {file_path.name}")
        upload_file(args, release_id, file_path)

    print(f"Uploaded {len(files)} files to Gitee release {args.gitee_tag}.")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--manifest", default="runtime-packages.json")
    prepare_parser.add_argument("--output-dir", default="gitee-sync")
    prepare_parser.add_argument("--gitee-owner", required=True)
    prepare_parser.add_argument("--gitee-repo", required=True)
    prepare_parser.add_argument("--gitee-tag", required=True)
    prepare_parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"))
    prepare_parser.set_defaults(func=prepare)

    publish_parser = subparsers.add_parser("publish")
    publish_parser.add_argument("--files-dir", default="gitee-sync/files")
    publish_parser.add_argument("--gitee-owner", required=True)
    publish_parser.add_argument("--gitee-repo", required=True)
    publish_parser.add_argument("--gitee-tag", required=True)
    publish_parser.add_argument("--gitee-token", required=True)
    publish_parser.add_argument("--target-commitish", default="main")
    publish_parser.add_argument("--release-name", required=True)
    publish_parser.add_argument("--release-body", default="")
    publish_parser.set_defaults(func=publish)

    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
