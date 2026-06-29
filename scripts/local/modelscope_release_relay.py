#!/usr/bin/env python3
"""Mirror PyStudio flat package repositories to ModelScope.

GitHub Releases remain the authority and store `Packages.xz` plus `.deb` files.
This relay downloads those flat assets, uploads them to ModelScope with the same
filenames, and then uploads the schema-5 runtime manifest for lightweight
discovery.
"""

from __future__ import annotations

import argparse
import getpass
import json
import lzma
import os
import subprocess
import sys
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


def modelscope_repo_path_from_base_url(base_url: str, resolve_base: str) -> str:
    if not base_url.startswith(resolve_base):
        raise RuntimeError(f"ModelScope baseUrl is not under expected resolve base: {base_url}")
    path = urllib.parse.unquote(base_url[len(resolve_base) :])
    return path.strip("/")


def parse_flat_index_packages(index_path: Path) -> list[dict[str, str]]:
    text = lzma.decompress(index_path.read_bytes()).decode("utf-8", errors="replace")
    packages: list[dict[str, str]] = []
    seen: set[str] = set()
    for stanza in [part.strip() for part in text.split("\n\n") if part.strip()]:
        fields: dict[str, str] = {}
        current = ""
        for line in stanza.splitlines():
            if line.startswith(" ") and current:
                fields[current] += "\n" + line.strip()
                continue
            key, sep, value = line.partition(":")
            if sep:
                current = key
                fields[key] = value.strip()
        filename = fields.get("Filename", "")
        name = Path(filename).name
        if name and name not in seen:
            seen.add(name)
            packages.append({"filename": filename, "name": name, "architecture": fields.get("Architecture", "")})
    return packages


def package_pool_for_arch(pools: list[dict[str, Any]], arch: str, kind: str) -> dict[str, Any] | None:
    wanted = [arch]
    if arch != "all":
        wanted.append("all")
    sorted_pools = sorted(pools, key=lambda item: int(item.get("priority", 1000)))
    for wanted_arch in wanted:
        for pool in sorted_pools:
            if pool.get("kind") == kind and pool.get("architecture") == wanted_arch and pool.get("baseUrl"):
                return pool
    return None


def collect_flat_repositories(args: argparse.Namespace, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    repositories: list[dict[str, Any]] = []
    for repository in manifest.get("repositories", {}).values():
        github_mirror: dict[str, Any] | None = None
        base_url = ""
        for mirror in repository.get("mirrors", []):
            if mirror.get("id") == "github-release-flat" and mirror.get("kind") == "flat-release-repo":
                github_mirror = mirror
            if mirror.get("id") == "modelscope" and mirror.get("kind") == "flat-package-repo":
                base_url = str(mirror.get("baseUrl", ""))
        if not github_mirror or not base_url:
            continue
        index_url = str(github_mirror.get("indexUrl", ""))
        if args.include and args.include not in repository.get("id", "") and args.include not in index_url:
            continue
        repositories.append(
            {
                "repositoryId": repository["id"],
                "githubBaseUrl": str(github_mirror["baseUrl"]),
                "indexUrl": index_url,
                "indexName": Path(urllib.parse.urlparse(index_url).path).name,
                "basePath": modelscope_repo_path_from_base_url(base_url, args.resolve_base),
                "githubPackagePools": [
                    pool for pool in repository.get("packagePools", []) if pool.get("kind") == "flat-release-pool"
                ],
                "modelscopePackagePools": [
                    pool for pool in repository.get("packagePools", []) if pool.get("kind") == "flat-package-pool"
                ],
            }
        )
    if args.max_repositories:
        repositories = repositories[: args.max_repositories]
    return repositories


def upload_flat_repository(args: argparse.Namespace, token: str, repository: dict[str, Any], github_token: str) -> int:
    cache_dir = Path(args.cache_dir)
    repo_cache = cache_dir / "flat" / safe_part(str(repository["repositoryId"]))
    index_path = repo_cache / str(repository["indexName"])
    download_asset(
        str(repository["indexUrl"]),
        index_path,
        github_token,
        args.download_retries,
        args.force_download,
        args.progress_interval,
    )

    uploaded = 0
    upload_file(args, token, index_path, f"{repository['basePath'].rstrip('/')}/{index_path.name}", args.force_upload)
    uploaded += 1

    github_pools = list(repository.get("githubPackagePools", []))
    modelscope_pools = list(repository.get("modelscopePackagePools", []))
    for package in parse_flat_index_packages(index_path):
        filename = package["filename"]
        deb_name = package["name"]
        arch = package["architecture"] or "all"
        github_pool = package_pool_for_arch(github_pools, arch, "flat-release-pool")
        modelscope_pool = package_pool_for_arch(modelscope_pools, arch, "flat-package-pool")
        if github_pool and modelscope_pool:
            source_url = urllib.parse.urljoin(str(github_pool["baseUrl"]), deb_name)
            target_base = modelscope_repo_path_from_base_url(str(modelscope_pool["baseUrl"]), args.resolve_base)
            path_in_repo = f"{target_base.rstrip('/')}/{deb_name}"
        else:
            source_url = urllib.parse.urljoin(str(repository["githubBaseUrl"]), filename)
            path_in_repo = f"{repository['basePath'].rstrip('/')}/{deb_name}"

        deb_path = repo_cache / deb_name
        download_asset(
            source_url,
            deb_path,
            github_token,
            args.download_retries,
            args.force_download,
            args.progress_interval,
        )
        upload_file(args, token, deb_path, path_in_repo, args.force_upload)
        uploaded += 1
    return uploaded


def run(args: argparse.Namespace) -> None:
    github_token = args.github_token or first_env_value("GITHUB_TOKEN", "git_token_vg188")
    token = args.modelscope_token or modelscope_token_from_env()
    if not token and not args.dry_run:
        token = getpass.getpass("ModelScope token: ")

    manifest_path = Path(args.manifest)
    manifest = read_manifest(manifest_path)
    repositories = collect_flat_repositories(args, manifest)

    if args.dry_run:
        print(f"Dry run: {len(repositories)} package repositories would be mirrored to {args.repo_id}.")
        for repository in repositories:
            print(f"{repository['indexUrl']} -> {repository['basePath']}/")
        print(f"{manifest_path} -> {args.output_manifest_name}")
        return

    if args.create_repo:
        create_or_reuse_dataset(args, token)

    total_files = 0
    for repository in repositories:
        total_files += upload_flat_repository(args, token, repository, github_token)

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
