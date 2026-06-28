#!/usr/bin/env python3
"""Mirror runtime package assets to a public ModelScope dataset repository.

This tool is intended to run on a developer PC. It reuses the local asset
cache used by the Gitee relay, uploads selected files to ModelScope, then
generates a manifest whose app-facing package URLs point at ModelScope.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from gitee_release_relay import (
    download_asset,
    first_env_value,
    format_bytes,
    gitee_release_url,
    mirrored_filename,
    read_manifest,
    rewrite_urls,
    safe_part,
    source_urls_from_manifest,
)


DEFAULT_INCLUDE = (
    r"("
    r"-component-[^/]+\.deb|"
    r"bootstrap[^/]*\.tar\.xz)$"
)
DEFAULT_REPO_ID = "yourba/pystudio-termux-builds"
DEFAULT_ENDPOINT = "https://modelscope.cn"


def windows_user_env(name: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _value_type = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    return str(value)


def modelscope_token_from_env() -> str:
    return (
        first_env_value("modelscope_yourba", "MODELSCOPE_YOURBA", "MODELSCOPE_TOKEN")
        or windows_user_env("modelscope_yourba")
        or windows_user_env("MODELSCOPE_YOURBA")
        or windows_user_env("MODELSCOPE_TOKEN")
    )


def modelscope_file_url(
    repo_id: str,
    path_in_repo: str,
    revision: str,
    endpoint: str,
) -> str:
    owner, dataset = repo_id.split("/", 1)
    query = urllib.parse.urlencode({"Revision": revision, "FilePath": path_in_repo})
    return f"{endpoint.rstrip('/')}/api/v1/datasets/{owner}/{dataset}/repo?{query}"


def remote_file_exists(url: str) -> bool:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "pystudio-modelscope-relay"})
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return 200 <= response.status < 400
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return False
            if attempt == 3:
                raise
        except urllib.error.URLError:
            if attempt == 3:
                raise
        time.sleep(attempt * 2)


def run_modelscope_command(command: list[str], token: str) -> None:
    redacted = ["<token>" if part == token else part for part in command]
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            "ModelScope command failed with exit code "
            f"{result.returncode}: {' '.join(redacted)}"
        )


def create_or_reuse_dataset(args: argparse.Namespace, token: str) -> None:
    command = [
        args.modelscope_path,
        "create",
        args.repo_id,
        "--repo_type",
        "dataset",
        "--visibility",
        "public",
        "--exist_ok",
        "--token",
        token,
        "--endpoint",
        args.endpoint,
    ]
    run_modelscope_command(command, token)


def upload_asset(
    args: argparse.Namespace,
    token: str,
    local_file: Path,
    path_in_repo: str,
    force: bool,
) -> None:
    size = local_file.stat().st_size
    url = modelscope_file_url(args.repo_id, path_in_repo, args.revision, args.endpoint)
    if not force and remote_file_exists(url):
        print(f"Remote asset exists, skipping: {path_in_repo} ({format_bytes(size)})")
        return

    print(f"Uploading to ModelScope: {path_in_repo} ({format_bytes(size)})")
    started = time.monotonic()
    command = [
        args.modelscope_path,
        "upload",
        args.repo_id,
        str(local_file.resolve()),
        path_in_repo,
        "--repo-type",
        "dataset",
        "--token",
        token,
        "--endpoint",
        args.endpoint,
        "--commit-message",
        f"upload {local_file.name}",
    ]
    for attempt in range(1, args.upload_retries + 1):
        try:
            run_modelscope_command(command, token)
            break
        except RuntimeError as exc:
            if not force and remote_file_exists(url):
                print(f"Remote asset exists after upload failure, continuing: {path_in_repo}")
                break
            if attempt == args.upload_retries:
                raise
            delay = min(60, attempt * 10)
            print(f"Warning: upload attempt {attempt} failed for {path_in_repo}: {exc}")
            print(f"Retrying ModelScope upload in {delay}s...")
            time.sleep(delay)
    elapsed = max(time.monotonic() - started, 0.001)
    print(
        f"Uploaded to ModelScope: {path_in_repo} "
        f"({format_bytes(size)} in {elapsed:.1f}s, {format_bytes(size / elapsed)}/s)"
    )


def collect_urls(args: argparse.Namespace, manifest: dict[str, Any]) -> list[str]:
    include = args.include or DEFAULT_INCLUDE
    urls = source_urls_from_manifest(manifest, include)
    if args.max_assets:
        urls = urls[: args.max_assets]
    if not urls:
        raise RuntimeError("No matching GitHub release URLs found in manifest.")
    return urls


def run(args: argparse.Namespace) -> None:
    github_token = args.github_token or first_env_value("GITHUB_TOKEN", "git_token_vg188")
    token = args.modelscope_token or modelscope_token_from_env()
    if not token and not args.dry_run:
        token = getpass.getpass("ModelScope token: ")

    manifest = read_manifest(Path(args.manifest))
    urls = collect_urls(args, manifest)

    cache_dir = Path(args.cache_dir)
    asset_dir = cache_dir / "assets"
    manifest_dir = cache_dir / "manifest"
    asset_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    replacements: dict[str, str] = {}
    upload_plan: list[tuple[Path, str]] = []
    for url in urls:
        filename = mirrored_filename(url)
        destination = asset_dir / filename
        path_in_repo = f"{args.assets_prefix.strip('/')}/{filename}"
        modelscope_url = modelscope_file_url(
            args.repo_id,
            path_in_repo,
            args.revision,
            args.endpoint,
        )
        replacements[url] = modelscope_url
        if (
            args.skip_existing_remote
            and not args.force_upload
            and remote_file_exists(modelscope_url)
        ):
            print(f"Remote asset exists, skipping download: {path_in_repo}")
            continue

        if not args.no_download:
            download_asset(
                url,
                destination,
                github_token,
                args.download_retries,
                args.force_download,
                args.progress_interval,
            )
        if not destination.exists():
            raise RuntimeError(f"Local asset is missing: {destination}")

        upload_plan.append((destination, path_in_repo))

    mirrored_manifest = rewrite_urls(manifest, replacements)
    manifest_bytes = (json.dumps(mirrored_manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    manifest_path = manifest_dir / args.output_manifest_name

    if args.dry_run:
        print(
            f"Dry run: {len(upload_plan)} assets plus one manifest would be "
            f"uploaded to ModelScope dataset {args.repo_id}."
        )
        print(f"Manifest would be written: {manifest_path} ({format_bytes(len(manifest_bytes))})")
        for local_file, path_in_repo in upload_plan:
            url = modelscope_file_url(args.repo_id, path_in_repo, args.revision, args.endpoint)
            print(f"{local_file} -> {url}")
        manifest_url = modelscope_file_url(
            args.repo_id,
            args.output_manifest_name,
            args.revision,
            args.endpoint,
        )
        print(f"{manifest_path} -> {manifest_url}")
        return

    manifest_path.write_bytes(manifest_bytes)
    upload_plan.append((manifest_path, args.output_manifest_name))

    if args.create_repo:
        create_or_reuse_dataset(args, token)

    for local_file, path_in_repo in upload_plan:
        force = args.force_upload or path_in_repo == args.output_manifest_name
        upload_asset(args, token, local_file, path_in_repo, force)

    print("ModelScope manifest URL:")
    print(modelscope_file_url(args.repo_id, args.output_manifest_name, args.revision, args.endpoint))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="runtime-packages.json")
    parser.add_argument("--cache-dir", default="work/gitee-relay")
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--revision", default="master")
    parser.add_argument("--assets-prefix", default="assets")
    parser.add_argument("--output-manifest-name", default="runtime-packages-modelscope.json")
    parser.add_argument("--include", default=DEFAULT_INCLUDE, help="Regex filter for source URLs.")
    parser.add_argument("--max-assets", type=int, default=0, help="Limit assets for a smoke test.")
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--force-upload", action="store_true")
    parser.add_argument("--skip-existing-remote", action="store_true")
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--create-repo", action="store_true", default=True)
    parser.add_argument("--no-create-repo", action="store_false", dest="create_repo")
    parser.add_argument("--download-retries", type=int, default=5)
    parser.add_argument("--upload-retries", type=int, default=5)
    parser.add_argument("--progress-interval", type=float, default=0.5)
    parser.add_argument("--modelscope-token", default="")
    parser.add_argument("--github-token", default="")
    parser.add_argument("--modelscope-path", default="modelscope")
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
