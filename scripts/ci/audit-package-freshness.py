#!/usr/bin/env python3
"""Audit published package repositories against current source adapters.

The audit compares every apt-repository entry in runtime-packages.json with:

- the current source fork HEAD from sources/*.env;
- the current source-adapter patch series hash;
- the PyStudio Android package name from the manifest.

Older releases may not contain sourceMetadata/provenance. Those are reported as
unknown instead of stale, because they cannot prove which patch set was used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("work/package-freshness")
GITHUB_API = "https://api.github.com"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def sha256_patch_set(repo_root: Path, patch_set: str) -> str:
    if not patch_set or patch_set == "none":
        return ""
    patch_root = repo_root / "patches" / "source-adapters" / patch_set
    series = patch_root / "series"
    if not series.exists():
        return ""

    digest = hashlib.sha256()
    for raw_line in series.read_text(encoding="utf-8").splitlines():
        entry = raw_line.split("#", 1)[0].strip()
        if not entry:
            continue
        patch_path = patch_root / entry
        digest.update(entry.encode("utf-8") + b"\0")
        digest.update(patch_path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def git_last_commit_date(repo_root: Path, path: Path) -> str:
    proc = subprocess.run(
        ["git", "log", "-1", "--format=%cI", "--", str(path)],
        cwd=repo_root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def source_adapters(repo_root: Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for env_path in sorted((repo_root / "sources").glob("*.env")):
        values = parse_env_file(env_path)
        source_id = values.get("SOURCE_ID") or env_path.stem
        source_repo = values.get("SOURCE_REPO") or values.get("SOURCE_UPSTREAM_REPO") or ""
        patch_set = values.get("SOURCE_PATCH_SET", "")
        patch_root = repo_root / "patches" / "source-adapters" / patch_set
        result[source_id] = {
            "sourceId": source_id,
            "sourceName": values.get("SOURCE_NAME", source_id),
            "sourceRepo": source_repo,
            "patchSet": patch_set,
            "patchHash": sha256_patch_set(repo_root, patch_set),
            "patchUpdatedAt": git_last_commit_date(repo_root, patch_root),
            "envFile": str(env_path),
        }
    return result


def git_ls_remote_head(repo: str, retries: int = 3) -> str:
    if not repo:
        return ""
    for attempt in range(1, retries + 1):
        proc = subprocess.run(
            ["git", "ls-remote", repo, "HEAD"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.split()[0]
        if attempt < retries:
            time.sleep(attempt * 2)
    return ""


def normalize_repo_url(url: str) -> str:
    value = url.strip()
    value = re.sub(r"\.git$", "", value)
    value = value.rstrip("/")
    return value.lower()


def github_slug_from_repo_url(url: str) -> str:
    value = url.strip()
    if not value:
        return ""
    match = re.match(r"https://github\.com/([^/]+/[^/.]+)(?:\.git)?/?$", value)
    if match:
        return match.group(1)
    match = re.match(r"git@github\.com:([^/]+/[^/.]+)(?:\.git)?$", value)
    if match:
        return match.group(1)
    match = re.match(r"([^/]+/[^/]+)$", value)
    if match and "://" not in value:
        return match.group(1).removesuffix(".git")
    return ""


def parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def is_after(newer: str, older: str) -> bool:
    newer_time = parse_time(newer)
    older_time = parse_time(older)
    return bool(newer_time and older_time and newer_time > older_time)


def fetch_json(url: str, token: str = "", retries: int = 3) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "pystudio-package-freshness-audit",
    }
    if token and "github.com/" in url:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8")
            parsed: Any = json.loads(raw)
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            if not isinstance(parsed, dict):
                raise RuntimeError("metadata JSON root is not an object")
            return parsed
        except (OSError, urllib.error.URLError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = str(exc)
            if attempt < retries:
                time.sleep(attempt * 2)
    raise RuntimeError(last_error or f"failed to fetch {url}")


def fetch_json_list(url: str, token: str = "", retries: int = 3) -> list[dict[str, Any]]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "pystudio-package-freshness-audit",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8")
            parsed: Any = json.loads(raw)
            if not isinstance(parsed, list):
                raise RuntimeError("metadata JSON root is not a list")
            return [item for item in parsed if isinstance(item, dict)]
        except (OSError, urllib.error.URLError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = str(exc)
            if attempt < retries:
                time.sleep(attempt * 2)
    raise RuntimeError(last_error or f"failed to fetch {url}")


def github_api_json(path: str, token: str = "") -> dict[str, Any]:
    return fetch_json(f"{GITHUB_API}{path}", token=token)


def github_api_json_list(path: str, token: str = "") -> list[dict[str, Any]]:
    return fetch_json_list(f"{GITHUB_API}{path}", token=token)


def github_release_info(
    repository_url: str,
    tag: str,
    token: str,
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    slug = github_slug_from_repo_url(repository_url)
    if not slug or not tag:
        return {}
    cache_key = f"{slug}@{tag}"
    if cache_key not in cache:
        try:
            info = github_api_json(f"/repos/{slug}/releases/tags/{tag}", token=token)
        except RuntimeError as exc:
            info = {"error": str(exc)}
        cache[cache_key] = info
    return cache[cache_key]


def github_commit_date(repo_url: str, commit: str, token: str) -> str:
    slug = github_slug_from_repo_url(repo_url)
    if not slug or not commit:
        return ""
    try:
        info = github_api_json(f"/repos/{slug}/commits/{commit}", token=token)
    except RuntimeError:
        return ""
    commit_info = info.get("commit")
    if not isinstance(commit_info, dict):
        return ""
    committer = commit_info.get("committer")
    if not isinstance(committer, dict):
        return ""
    return str(committer.get("date") or "")


def metadata_source(metadata: dict[str, Any]) -> dict[str, Any]:
    source_metadata = metadata.get("sourceMetadata")
    if isinstance(source_metadata, dict):
        return source_metadata

    packages = metadata.get("packages")
    if isinstance(packages, list):
        for package in packages:
            if isinstance(package, dict) and isinstance(package.get("provenance"), dict):
                return package["provenance"]
    return {}


def repository_items(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    repositories = manifest.get("repositories", {})
    if not isinstance(repositories, dict):
        return []
    return [{**repo, "scope": "manifest"} for repo in repositories.values() if isinstance(repo, dict)]


def batch_items(batch_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    batches = batch_manifest.get("batches", [])
    if not isinstance(batches, list):
        return []
    return [batch for batch in batches if isinstance(batch, dict)]


def release_repository_slugs(manifest: dict[str, Any], extra: list[str]) -> list[str]:
    slugs: set[str] = set()
    for repo in repository_items(manifest):
        release = repo.get("release") or {}
        if isinstance(release, dict):
            slug = github_slug_from_repo_url(str(release.get("repository") or ""))
            if slug:
                slugs.add(slug)
    for value in extra:
        slug = github_slug_from_repo_url(value)
        if slug:
            slugs.add(slug)
    return sorted(slugs)


def discover_release_repositories(slugs: list[str], token: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for slug in slugs:
        page = 1
        while True:
            try:
                releases = github_api_json_list(f"/repos/{slug}/releases?per_page=100&page={page}", token=token)
            except RuntimeError:
                break
            if not releases:
                break
            for release in releases:
                tag = str(release.get("tag_name") or "")
                assets = release.get("assets")
                if not tag or not isinstance(assets, list):
                    continue
                for asset in assets:
                    if not isinstance(asset, dict):
                        continue
                    name = str(asset.get("name") or "")
                    download_url = str(asset.get("browser_download_url") or asset.get("url") or "")
                    if not name.endswith(".json") or not download_url:
                        continue
                    items.append(
                        {
                            "id": f"release:{slug}:{tag}:{name}",
                            "scope": "release",
                            "release": {
                                "repository": f"https://github.com/{slug}",
                                "tag": tag,
                                "publishedAt": release.get("published_at") or "",
                                "createdAt": release.get("created_at") or "",
                            },
                            "metadata": {
                                "downloadUrl": download_url,
                            },
                        }
                    )
            page += 1
    return items


def enrich_repo_from_metadata(repo: dict[str, Any], metadata: dict[str, Any]) -> None:
    if not repo.get("profile"):
        repo["profile"] = metadata.get("profile", "")
    if not repo.get("sourceAdapter"):
        repo["sourceAdapter"] = metadata.get("source", "")
    if not repo.get("architecture"):
        repo["architecture"] = metadata.get("architecture", "")
    if not repo.get("version"):
        repo["version"] = metadata.get("version", "")
    if not repo.get("artifactPrefix"):
        repo["artifactPrefix"] = metadata.get("artifactPrefix", "")


def merge_repository_scopes(repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for repo in repos:
        metadata_url = str(((repo.get("metadata") or {}).get("downloadUrl")) or "")
        if not metadata_url:
            metadata_url = str(repo.get("id") or "")
        existing = merged.get(metadata_url)
        if not existing:
            copied = dict(repo)
            copied["scopes"] = [repo.get("scope", "")]
            merged[metadata_url] = copied
            continue
        scope = repo.get("scope", "")
        if scope and scope not in existing["scopes"]:
            existing["scopes"].append(scope)
        if scope == "manifest":
            for key, value in repo.items():
                if key not in {"scope", "scopes"} and value:
                    existing[key] = value
    return list(merged.values())


def audit_repository(
    repo: dict[str, Any],
    metadata_cache: dict[str, dict[str, Any]],
    release_cache: dict[str, dict[str, Any]],
    adapters: dict[str, dict[str, str]],
    heads: dict[str, str],
    head_dates: dict[str, str],
    package_name: str,
    token: str,
) -> dict[str, Any]:
    metadata_url = str(((repo.get("metadata") or {}).get("downloadUrl")) or "")
    source_adapter = str(repo.get("sourceAdapter") or repo.get("source") or "")
    adapter = adapters.get(source_adapter, {})

    item: dict[str, Any] = {
        "repositoryId": repo.get("id", ""),
        "profile": repo.get("profile", ""),
        "sourceAdapter": source_adapter,
        "architecture": repo.get("architecture", ""),
        "version": repo.get("version", ""),
        "release": repo.get("release", {}),
        "metadataUrl": metadata_url,
        "scopes": repo.get("scopes") or [repo.get("scope", "")],
        "status": "unknown",
        "issues": [],
    }

    if not metadata_url:
        item["issues"].append("missing-metadata-url")
        item["status"] = "unknown"
        return item

    try:
        if metadata_url not in metadata_cache:
            metadata_cache[metadata_url] = fetch_json(metadata_url, token=token)
        metadata = metadata_cache[metadata_url]
        enrich_repo_from_metadata(repo, metadata)
        item["profile"] = repo.get("profile", "")
        item["sourceAdapter"] = repo.get("sourceAdapter") or repo.get("source") or ""
        source_adapter = str(item["sourceAdapter"] or "")
        adapter = adapters.get(source_adapter, {})
        item["architecture"] = repo.get("architecture", "")
        item["version"] = repo.get("version", "")
    except RuntimeError as exc:
        item["issues"].append("metadata-fetch-failed")
        item["status"] = "unknown"
        item["error"] = str(exc)
        return item

    release = repo.get("release") or {}
    if isinstance(release, dict):
        release_info = github_release_info(str(release.get("repository") or ""), str(release.get("tag") or ""), token, release_cache)
        release_published_at = str(
            release.get("publishedAt")
            or release_info.get("published_at")
            or release_info.get("created_at")
            or ""
        )
        if release_published_at:
            item["releasePublishedAt"] = release_published_at

    item["packageCount"] = metadata.get("packageCount") or len(metadata.get("packages", []) or [])
    source_metadata = metadata_source(metadata)
    item["sourceMetadata"] = source_metadata

    if not source_metadata:
        item["issues"].append("missing-source-metadata")
        release_published_at = str(item.get("releasePublishedAt") or "")
        patch_updated_at = adapter.get("patchUpdatedAt", "")
        current_head_date = head_dates.get(source_adapter, "")
        if patch_updated_at and is_after(patch_updated_at, release_published_at):
            item["issues"].append("patch-set-newer-than-release")
        if current_head_date and is_after(current_head_date, release_published_at):
            item["issues"].append("source-head-newer-than-release")
        item["status"] = "suspect" if len(item["issues"]) > 1 else "unknown"
        return item

    expected_patch_hash = adapter.get("patchHash", "")
    expected_patch_set = adapter.get("patchSet", "")
    current_head = heads.get(source_adapter, "")
    source_repo = str(source_metadata.get("sourceRepository") or "")
    expected_repo = adapter.get("sourceRepo", "")

    item["expected"] = {
        "sourceCommit": current_head,
        "sourceRepository": expected_repo,
        "patchSet": expected_patch_set,
        "patchHash": expected_patch_hash,
        "patchUpdatedAt": adapter.get("patchUpdatedAt", ""),
        "sourceHeadDate": head_dates.get(source_adapter, ""),
        "pystudioPackageName": package_name,
    }

    if expected_repo and source_repo and normalize_repo_url(source_repo) != normalize_repo_url(expected_repo):
        item["issues"].append("source-repository-mismatch")
    if current_head and source_metadata.get("sourceCommit") != current_head:
        item["issues"].append("source-commit-outdated")
    if expected_patch_set and source_metadata.get("patchSet") != expected_patch_set:
        item["issues"].append("patch-set-mismatch")
    if expected_patch_hash and source_metadata.get("patchHash") != expected_patch_hash:
        item["issues"].append("patch-hash-outdated")
    if package_name and source_metadata.get("pystudioPackageName") != package_name:
        item["issues"].append("pystudio-package-name-mismatch")

    item["status"] = "current" if not item["issues"] else "stale"
    return item


def audit_batch(
    batch: dict[str, Any],
    adapters: dict[str, dict[str, str]],
    heads: dict[str, str],
) -> dict[str, Any]:
    source_adapter = str(batch.get("source") or "")
    adapter = adapters.get(source_adapter, {})
    source_metadata = batch.get("sourceMetadata")
    if not isinstance(source_metadata, dict):
        source_metadata = {}

    item: dict[str, Any] = {
        "id": batch.get("id", ""),
        "profile": batch.get("profile", ""),
        "sourceAdapter": source_adapter,
        "version": batch.get("version", ""),
        "release": batch.get("release", {}),
        "architectures": batch.get("architectures", []),
        "summary": batch.get("summary", {}),
        "sourceMetadata": source_metadata,
        "status": "unknown",
        "issues": [],
    }

    if not source_metadata or not any(source_metadata.values()):
        item["issues"].append("missing-source-metadata")
        return item

    expected_repo = adapter.get("sourceRepo", "")
    source_repo = str(source_metadata.get("sourceRepository") or "")
    expected_head = heads.get(source_adapter, "")
    expected_patch_set = adapter.get("patchSet", "")
    expected_patch_hash = adapter.get("patchHash", "")

    item["expected"] = {
        "sourceCommit": expected_head,
        "sourceRepository": expected_repo,
        "patchSet": expected_patch_set,
        "patchHash": expected_patch_hash,
    }

    if expected_repo and source_repo and normalize_repo_url(source_repo) != normalize_repo_url(expected_repo):
        item["issues"].append("source-repository-mismatch")
    if expected_head and source_metadata.get("sourceCommit") != expected_head:
        item["issues"].append("source-commit-outdated")
    if expected_patch_set and source_metadata.get("patchSet") != expected_patch_set:
        item["issues"].append("patch-set-mismatch")
    if expected_patch_hash and source_metadata.get("patchHash") != expected_patch_hash:
        item["issues"].append("patch-hash-outdated")

    item["status"] = "current" if not item["issues"] else "stale"
    return item


def markdown_report(data: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# PyStudio Package Freshness Audit")
    lines.append("")
    lines.append(f"Generated: `{data['generatedAt']}`")
    lines.append(f"Manifest: `{data['manifest'].get('path', '')}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    for key, value in data["summary"].items():
        lines.append(f"- `{key}`: {value}")
    lines.append("")

    batch_audit = data.get("buildBatches", {})
    batch_results = batch_audit.get("batches", []) if isinstance(batch_audit, dict) else []
    if batch_results:
        lines.append("## Build Batch Freshness")
        lines.append("")
        lines.append("| Batch | Packages | Status | Issues | Release |")
        lines.append("| --- | --- | --- | --- | --- |")
        for item in batch_results:
            summary = item.get("summary") or {}
            release = item.get("release") or {}
            lines.append(
                "| {batch} | {packages} | {status} | {issues} | {tag} |".format(
                    batch=item.get("id", ""),
                    packages=summary.get("packageVersions", ""),
                    status=item.get("status", ""),
                    issues=", ".join(item.get("issues", [])),
                    tag=release.get("tag", ""),
                )
            )
        lines.append("")

    stale = [item for item in data["repositories"] if item["status"] == "stale"]
    suspect = [item for item in data["repositories"] if item["status"] == "suspect"]
    unknown = [item for item in data["repositories"] if item["status"] == "unknown"]

    if stale:
        lines.append("## Needs Rebuild")
        lines.append("")
        lines.append("| Profile | Arch | Version | Issues | Release | Scope |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for item in stale:
            release = item.get("release") or {}
            release_tag = release.get("tag", "")
            lines.append(
                "| {profile} | {arch} | {version} | {issues} | {tag} | {scope} |".format(
                    profile=item.get("profile", ""),
                    arch=item.get("architecture", ""),
                    version=item.get("version", ""),
                    issues=", ".join(item.get("issues", [])),
                    tag=release_tag,
                    scope=", ".join(item.get("scopes", [])),
                )
            )
        lines.append("")

    if suspect:
        lines.append("## Likely Needs Rebuild")
        lines.append("")
        lines.append("| Profile | Arch | Version | Issues | Release | Scope |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for item in suspect:
            release = item.get("release") or {}
            release_tag = release.get("tag", "")
            lines.append(
                "| {profile} | {arch} | {version} | {issues} | {tag} | {scope} |".format(
                    profile=item.get("profile", ""),
                    arch=item.get("architecture", ""),
                    version=item.get("version", ""),
                    issues=", ".join(item.get("issues", [])),
                    tag=release_tag,
                    scope=", ".join(item.get("scopes", [])),
                )
            )
        lines.append("")

    if unknown:
        lines.append("## Cannot Prove Freshness")
        lines.append("")
        lines.append("| Profile | Arch | Version | Issues | Release | Scope |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for item in unknown:
            release = item.get("release") or {}
            release_tag = release.get("tag", "")
            lines.append(
                "| {profile} | {arch} | {version} | {issues} | {tag} | {scope} |".format(
                    profile=item.get("profile", ""),
                    arch=item.get("architecture", ""),
                    version=item.get("version", ""),
                    issues=", ".join(item.get("issues", [])),
                    tag=release_tag,
                    scope=", ".join(item.get("scopes", [])),
                )
            )
        lines.append("")

    lines.append("## Current Source Baseline")
    lines.append("")
    lines.append("| Source | HEAD | Patch set | Patch hash |")
    lines.append("| --- | --- | --- | --- |")
    for source_id, source in sorted(data["sources"].items()):
        lines.append(
            f"| {source_id} | {source.get('currentHead', '')} | {source.get('patchSet', '')} | {source.get('patchHash', '')} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit package release metadata freshness.")
    parser.add_argument("--manifest", default="runtime-packages.json")
    parser.add_argument("--batch-manifest", default="package-build-batches.json")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument(
        "--include-release-repo",
        action="append",
        default=[],
        help="Also discover apt-repository metadata JSON assets from this GitHub repo or URL.",
    )
    parser.add_argument(
        "--include-manifest-release-repos",
        action="store_true",
        help="Discover additional release metadata from every GitHub repo referenced by the manifest.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path.cwd()
    manifest_path = Path(args.manifest)
    manifest = read_json(manifest_path)
    batch_manifest_path = Path(args.batch_manifest)
    batch_manifest = read_json(batch_manifest_path) if batch_manifest_path.exists() else {}
    package_name = str(manifest.get("packageName", ""))

    adapters = source_adapters(repo_root)
    heads = {source_id: git_ls_remote_head(source["sourceRepo"]) for source_id, source in adapters.items()}
    head_dates = {
        source_id: github_commit_date(source["sourceRepo"], heads.get(source_id, ""), args.github_token)
        for source_id, source in adapters.items()
    }
    sources = {
        source_id: {
            **source,
            "currentHead": heads.get(source_id, ""),
            "currentHeadDate": head_dates.get(source_id, ""),
        }
        for source_id, source in adapters.items()
    }

    repos = repository_items(manifest)
    discovered_repos: list[dict[str, Any]] = []
    discovered_slugs: list[str] = []
    if args.include_manifest_release_repos or args.include_release_repo:
        discovered_slugs = release_repository_slugs(
            manifest,
            [*args.include_release_repo, "vg188/pystudio-termux-builds"],
        )
        discovered_repos = discover_release_repositories(discovered_slugs, args.github_token)
        repos = merge_repository_scopes([*repos, *discovered_repos])

    metadata_cache: dict[str, dict[str, Any]] = {}
    release_cache: dict[str, dict[str, Any]] = {}
    results = [
        audit_repository(repo, metadata_cache, release_cache, adapters, heads, head_dates, package_name, args.github_token)
        for repo in repos
    ]
    batch_results = [audit_batch(batch, adapters, heads) for batch in batch_items(batch_manifest)]
    summary = Counter(item["status"] for item in results)
    batch_summary = Counter(item["status"] for item in batch_results)
    issue_counts: Counter[str] = Counter()
    for item in results:
        issue_counts.update(item.get("issues", []))
    batch_issue_counts: Counter[str] = Counter()
    for item in batch_results:
        batch_issue_counts.update(item.get("issues", []))

    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "manifest": {
            "path": str(manifest_path),
            "schemaVersion": manifest.get("schemaVersion"),
            "generatedAt": manifest.get("generatedAt"),
        },
        "batchManifest": {
            "path": str(batch_manifest_path) if batch_manifest else "",
            "schemaVersion": batch_manifest.get("schemaVersion"),
            "generatedAt": batch_manifest.get("generatedAt"),
        },
        "discovery": {
            "releaseRepositories": discovered_slugs,
            "releaseMetadataAssets": len(discovered_repos),
        },
        "summary": {
            "repositories": len(results),
            "current": summary.get("current", 0),
            "stale": summary.get("stale", 0),
            "suspect": summary.get("suspect", 0),
            "unknown": summary.get("unknown", 0),
            "issues": dict(sorted(issue_counts.items())),
        },
        "sources": sources,
        "repositories": results,
        "buildBatches": {
            "summary": {
                "batches": len(batch_results),
                "current": batch_summary.get("current", 0),
                "stale": batch_summary.get("stale", 0),
                "unknown": batch_summary.get("unknown", 0),
                "issues": dict(sorted(batch_issue_counts.items())),
            },
            "batches": batch_results,
        },
    }

    output_dir = Path(args.output_dir)
    json_path = output_dir / "package-freshness-audit.json"
    md_path = output_dir / "package-freshness-audit.md"
    write_json(json_path, report)
    md_path.write_text(markdown_report(report), encoding="utf-8")

    print(f"Wrote freshness audit JSON: {json_path}")
    print(f"Wrote freshness audit report: {md_path}")
    print(
        "Summary: "
        f"{report['summary']['current']} current, "
        f"{report['summary']['stale']} stale, "
        f"{report['summary']['suspect']} suspect, "
        f"{report['summary']['unknown']} unknown "
        f"across {report['summary']['repositories']} repositories."
    )
    if batch_results:
        batch_report = report["buildBatches"]["summary"]
        print(
            "Build batches: "
            f"{batch_report['current']} current, "
            f"{batch_report['stale']} stale, "
            f"{batch_report['unknown']} unknown "
            f"across {batch_report['batches']} batches."
        )
    if issue_counts:
        print("Issues:")
        for issue, count in sorted(issue_counts.items()):
            print(f"  {issue}: {count}")
    if batch_issue_counts:
        print("Batch issues:")
        for issue, count in sorted(batch_issue_counts.items()):
            print(f"  {issue}: {count}")
    return 0 if not summary.get("stale") and not summary.get("suspect") and not batch_summary.get("stale") else 1


if __name__ == "__main__":
    raise SystemExit(main())
