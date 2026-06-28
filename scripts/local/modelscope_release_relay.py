#!/usr/bin/env python3
"""Mirror PyStudio apt-style package repositories to ModelScope.

The GitHub release remains the authority and stores compact repository
snapshots. This relay downloads those snapshots, expands them into a
Termux-style `dists/` + `pool/` tree, uploads that tree to ModelScope, and then
uploads the same schema-5 runtime manifest for lightweight discovery.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from transfer_utils import (
    download_asset,
    first_env_value,
    format_bytes,
    read_manifest,
    safe_part,
)


DEFAULT_REPO_ID = "yourba/pystudio-termux-builds"
DEFAULT_ENDPOINT = "https://modelscope.cn"
DEFAULT_REVISION = "master"
DEFAULT_RESOLVE_BASE = f"https://modelscope.cn/datasets/{DEFAULT_REPO_ID}/resolve/{DEFAULT_REVISION}/"


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


def modelscope_file_url(repo_id: str, path_in_repo: str, revision: str, endpoint: str) -> str:
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
    return False


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


def upload_file(args: argparse.Namespace, token: str, local_file: Path, path_in_repo: str, force: bool) -> None:
    size = local_file.stat().st_size
    url = modelscope_file_url(args.repo_id, path_in_repo, args.revision, args.endpoint)
    if not force and remote_file_exists(url):
        print(f"Remote file exists, skipping: {path_in_repo} ({format_bytes(size)})")
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
        f"upload {path_in_repo}",
    ]
    for attempt in range(1, args.upload_retries + 1):
        try:
            run_modelscope_command(command, token)
            break
        except RuntimeError as exc:
            if not force and remote_file_exists(url):
                print(f"Remote file exists after upload failure, continuing: {path_in_repo}")
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


def safe_extract_tar(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive_path, mode="r:*") as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if os.path.commonpath([root, target]) != str(root):
                raise RuntimeError(f"unsafe tar member path: {member.name}")
        archive.extractall(destination)


def modelscope_repo_path_from_base_url(base_url: str, resolve_base: str) -> str:
    if not base_url.startswith(resolve_base):
        raise RuntimeError(f"ModelScope baseUrl is not under expected resolve base: {base_url}")
    path = urllib.parse.unquote(base_url[len(resolve_base) :])
    return path.strip("/")


def collect_repository_snapshots(args: argparse.Namespace, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for repository in manifest.get("repositories", {}).values():
        snapshot = repository.get("snapshot", {})
        download_url = str(snapshot.get("downloadUrl", ""))
        if not download_url:
            continue
        if args.include and args.include not in repository.get("id", "") and args.include not in download_url:
            continue
        base_url = ""
        for mirror in repository.get("mirrors", []):
            if mirror.get("id") == "modelscope" and mirror.get("kind") == "full-repo":
                base_url = str(mirror.get("baseUrl", ""))
                break
        if not base_url:
            continue
        snapshots.append(
            {
                "repositoryId": repository["id"],
                "downloadUrl": download_url,
                "fileName": snapshot.get("fileName") or Path(urllib.parse.urlparse(download_url).path).name,
                "basePath": modelscope_repo_path_from_base_url(base_url, args.resolve_base),
            }
        )
    if args.max_repositories:
        snapshots = snapshots[: args.max_repositories]
    return snapshots


def upload_snapshot_contents(args: argparse.Namespace, token: str, snapshot: dict[str, Any], github_token: str) -> int:
    cache_dir = Path(args.cache_dir)
    archive_path = cache_dir / "snapshots" / safe_part(str(snapshot["repositoryId"])) / str(snapshot["fileName"])
    extract_dir = cache_dir / "extracted" / safe_part(str(snapshot["repositoryId"]))

    download_asset(
        str(snapshot["downloadUrl"]),
        archive_path,
        github_token,
        args.download_retries,
        args.force_download,
        args.progress_interval,
    )
    if args.force_extract and extract_dir.exists():
        import shutil

        shutil.rmtree(extract_dir)
    if not extract_dir.exists():
        safe_extract_tar(archive_path, extract_dir)

    uploaded = 0
    for local_file in sorted(path for path in extract_dir.rglob("*") if path.is_file()):
        rel = local_file.relative_to(extract_dir).as_posix()
        path_in_repo = f"{snapshot['basePath'].rstrip('/')}/{rel}"
        upload_file(args, token, local_file, path_in_repo, args.force_upload)
        uploaded += 1
    return uploaded


def run(args: argparse.Namespace) -> None:
    github_token = args.github_token or first_env_value("GITHUB_TOKEN", "git_token_vg188")
    token = args.modelscope_token or modelscope_token_from_env()
    if not token and not args.dry_run:
        token = getpass.getpass("ModelScope token: ")

    manifest_path = Path(args.manifest)
    manifest = read_manifest(manifest_path)
    snapshots = collect_repository_snapshots(args, manifest)

    if args.dry_run:
        print(f"Dry run: {len(snapshots)} package repositories would be mirrored to {args.repo_id}.")
        for snapshot in snapshots:
            print(f"{snapshot['downloadUrl']} -> {snapshot['basePath']}/")
        print(f"{manifest_path} -> {args.output_manifest_name}")
        return

    if args.create_repo:
        create_or_reuse_dataset(args, token)

    total_files = 0
    for snapshot in snapshots:
        total_files += upload_snapshot_contents(args, token, snapshot, github_token)

    upload_file(args, token, manifest_path, args.output_manifest_name, force=True)
    print(f"Uploaded {total_files} package repository files to ModelScope.")
    print("ModelScope manifest URL:")
    print(modelscope_file_url(args.repo_id, args.output_manifest_name, args.revision, args.endpoint))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="runtime-packages.json")
    parser.add_argument("--cache-dir", default="work/modelscope-relay")
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--resolve-base", default=DEFAULT_RESOLVE_BASE)
    parser.add_argument("--output-manifest-name", default="runtime-packages.json")
    parser.add_argument("--include", default="", help="Optional repository id or URL substring filter.")
    parser.add_argument("--max-repositories", type=int, default=0, help="Limit repositories for a smoke test.")
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--force-extract", action="store_true")
    parser.add_argument("--force-upload", action="store_true")
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
