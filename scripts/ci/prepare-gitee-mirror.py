#!/usr/bin/env python3
"""Prepare Gitee lightweight index files with ModelScope-first mirrors."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import urllib.parse
from typing import Any


MODELSCOPE_DATASET = "yourba/pystudio-termux-builds"
MODELSCOPE_REVISION = "master"
MODELSCOPE_RESOLVE_BASE = f"https://modelscope.cn/datasets/{MODELSCOPE_DATASET}/resolve/{MODELSCOPE_REVISION}/"
GITEE_MANIFEST_URL = "https://gitee.com/yourba/pystudio-termux-builds/raw/main/runtime-packages.json"
GITEE_STATUS_URL = "https://gitee.com/yourba/pystudio-termux-builds/raw/main/mirror-status.json"
GITHUB_MANIFEST_URL = "https://raw.githubusercontent.com/vg188/pystudio-termux-builds/main/runtime-packages.json"


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def modelscope_url(path: str) -> str:
    return urllib.parse.urljoin(MODELSCOPE_RESOLVE_BASE, urllib.parse.quote(path.strip("/"), safe="/"))


def github_repo_slug(repository_url: str) -> str:
    marker = "github.com/"
    if marker in repository_url:
        return repository_url.split(marker, 1)[1].strip("/")
    return repository_url.strip("/")


def bootstrap_modelscope_url(entry: dict[str, Any], arch: str, artifact: dict[str, Any]) -> str:
    release = entry.get("release", {})
    repository = github_repo_slug(str(release.get("repository", "")))
    tag = str(release.get("tag", ""))
    profile = str(entry.get("profile") or entry.get("id") or "bootstrap")
    file_name = str(artifact.get("fileName", ""))
    if not repository or not tag or not file_name:
        return ""
    return modelscope_url(f"bootstrap/{repository}/{tag}/{profile}/{arch}/{file_name}")


def mirror_priority(mirror: dict[str, Any]) -> int:
    try:
        return int(mirror.get("priority", 1000))
    except (TypeError, ValueError):
        return 1000


def is_modelscope(item: dict[str, Any]) -> bool:
    item_id = str(item.get("id", "")).lower()
    base_url = str(item.get("baseUrl") or item.get("indexUrl") or item.get("downloadUrl") or "").lower()
    return item_id.startswith("modelscope") or "modelscope.cn/" in base_url


def is_github(item: dict[str, Any]) -> bool:
    item_id = str(item.get("id", "")).lower()
    base_url = str(item.get("baseUrl") or item.get("indexUrl") or item.get("downloadUrl") or "").lower()
    return item_id.startswith("github") or "github.com/" in base_url


def prefer_cn_mirrors(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preferred: list[dict[str, Any]] = []
    for item in items:
        mirror = copy.deepcopy(item)
        if is_modelscope(mirror):
            mirror["priority"] = 1
            mirror["region"] = "CN"
            mirror["preferred"] = True
        elif is_github(mirror):
            mirror["priority"] = max(mirror_priority(mirror), 50)
            mirror["fallback"] = True
        else:
            mirror["priority"] = max(mirror_priority(mirror), 30)
        preferred.append(mirror)
    return sorted(preferred, key=lambda value: (mirror_priority(value), str(value.get("id", ""))))


def rewrite_repository_for_cn(repository: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(repository)
    mirrors = prefer_cn_mirrors(list(result.get("mirrors", [])))
    result["mirrors"] = mirrors

    modelscope_index_url = ""
    for mirror in mirrors:
        if is_modelscope(mirror) and mirror.get("indexUrl"):
            modelscope_index_url = str(mirror["indexUrl"])
            break
    if modelscope_index_url and isinstance(result.get("index"), dict):
        index = result["index"]
        current_download_url = str(index.get("downloadUrl", ""))
        if current_download_url and current_download_url != modelscope_index_url:
            index.setdefault("githubDownloadUrl", current_download_url)
        index["downloadUrl"] = modelscope_index_url

    pools = result.get("packagePools")
    if isinstance(pools, list):
        result["packagePools"] = prefer_cn_mirrors(pools)
    return result


def rewrite_bootstrap_artifact_for_cn(entry: dict[str, Any], arch: str, artifact: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(artifact)
    github_url = str(result.get("downloadUrl", ""))
    ms_url = bootstrap_modelscope_url(entry, arch, result)
    mirrors: list[dict[str, Any]] = []
    if ms_url:
        mirrors.append(
            {
                "id": "modelscope",
                "kind": "file-mirror",
                "downloadUrl": ms_url,
                "priority": 1,
                "region": "CN",
                "preferred": True,
            }
        )
    if github_url:
        mirrors.append(
            {
                "id": "github-release",
                "kind": "github-release-asset",
                "downloadUrl": github_url,
                "priority": 50,
                "fallback": True,
            }
        )
    if ms_url:
        result.setdefault("githubDownloadUrl", github_url)
        result["downloadUrl"] = ms_url
    if mirrors:
        result["mirrors"] = mirrors
    return result


def rewrite_entry_for_cn(entry: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(entry)
    if result.get("kind") != "bootstrap":
        return result
    artifacts_by_arch = result.get("artifacts")
    if not isinstance(artifacts_by_arch, dict):
        return result
    rewritten: dict[str, list[dict[str, Any]]] = {}
    for arch, artifacts in artifacts_by_arch.items():
        if not isinstance(artifacts, list):
            continue
        rewritten[arch] = [rewrite_bootstrap_artifact_for_cn(result, arch, artifact) for artifact in artifacts]
    result["artifacts"] = rewritten
    return result


def prepare_cn_runtime_manifest(manifest: dict[str, Any], modelscope_synced: bool) -> dict[str, Any]:
    result = copy.deepcopy(manifest)
    result["mirrorProfile"] = {
        "id": "gitee-cn-modelscope-first",
        "kind": "lightweight-index",
        "generatedAt": now_iso(),
        "sourceGeneratedAt": manifest.get("generatedAt", ""),
        "largeFileMirror": "modelscope",
        "fallbackMirror": "github",
        "modelscopeSyncedThisRun": modelscope_synced,
        "statusUrl": GITEE_STATUS_URL,
    }
    result["manifestMirrors"] = [
        {
            "id": "gitee",
            "kind": "manifest",
            "manifestUrl": GITEE_MANIFEST_URL,
            "priority": 1,
            "region": "CN",
        },
        {
            "id": "modelscope",
            "kind": "manifest",
            "manifestUrl": modelscope_url("runtime-packages.json"),
            "priority": 5,
            "region": "CN",
        },
        {
            "id": "github",
            "kind": "manifest",
            "manifestUrl": GITHUB_MANIFEST_URL,
            "priority": 50,
            "fallback": True,
        },
    ]
    package_management = result.setdefault("packageManagement", {})
    package_management["mirrorPolicy"] = (
        "Gitee manifest is the CN lightweight entry point; prefer ModelScope "
        "large-file mirrors and fall back to GitHub release assets."
    )

    repositories = result.get("repositories", {})
    if isinstance(repositories, dict):
        result["repositories"] = {
            repo_id: rewrite_repository_for_cn(repository)
            for repo_id, repository in repositories.items()
            if isinstance(repository, dict)
        }

    entries = result.get("entries", [])
    if isinstance(entries, list):
        result["entries"] = [rewrite_entry_for_cn(entry) for entry in entries if isinstance(entry, dict)]
    return result


def add_light_index_profile(index: dict[str, Any], *, source_name: str, runtime_manifest: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(index)
    result["mirrorProfile"] = {
        "id": "gitee-cn-light-index",
        "kind": "debug-index",
        "sourceFile": source_name,
        "generatedAt": now_iso(),
        "runtimeManifestGeneratedAt": runtime_manifest.get("generatedAt", ""),
        "downloadPolicy": "Use runtime-packages.json for ModelScope/GitHub mirror selection.",
    }
    return result


def collect_status(runtime_manifest: dict[str, Any], files: list[Path], modelscope_synced: bool) -> dict[str, Any]:
    repositories = runtime_manifest.get("repositories", {})
    repo_values = [repo for repo in repositories.values() if isinstance(repo, dict)] if isinstance(repositories, dict) else []
    modelscope_repo_mirrors = sum(
        1
        for repo in repo_values
        for mirror in repo.get("mirrors", [])
        if isinstance(mirror, dict) and is_modelscope(mirror)
    )
    modelscope_pools = sum(
        1
        for repo in repo_values
        for pool in repo.get("packagePools", [])
        if isinstance(pool, dict) and is_modelscope(pool)
    )
    bootstrap_mirrors = 0
    for entry in runtime_manifest.get("entries", []):
        if not isinstance(entry, dict) or entry.get("kind") != "bootstrap":
            continue
        for artifacts in (entry.get("artifacts") or {}).values():
            if isinstance(artifacts, list):
                bootstrap_mirrors += sum(1 for artifact in artifacts if isinstance(artifact, dict) and artifact.get("downloadUrl"))

    return {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "source": {
            "githubManifestUrl": GITHUB_MANIFEST_URL,
            "githubRepository": os.environ.get("GITHUB_REPOSITORY", "vg188/pystudio-termux-builds"),
            "githubCommit": os.environ.get("GITHUB_SHA", ""),
            "runtimeManifestGeneratedAt": runtime_manifest.get("generatedAt", ""),
            "schemaVersion": runtime_manifest.get("schemaVersion"),
        },
        "gitee": {
            "role": "lightweight-index",
            "manifestUrl": GITEE_MANIFEST_URL,
        },
        "modelscope": {
            "dataset": MODELSCOPE_DATASET,
            "revision": MODELSCOPE_REVISION,
            "resolveBase": MODELSCOPE_RESOLVE_BASE,
            "preferredInGiteeManifest": True,
            "syncedThisRun": modelscope_synced,
            "repositoryMirrors": modelscope_repo_mirrors,
            "packagePoolMirrors": modelscope_pools,
            "bootstrapArtifactMirrors": bootstrap_mirrors,
        },
        "files": [
            {
                "path": path.name,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in files
            if path.exists()
        ],
    }


def parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-manifest", default="runtime-packages.json")
    parser.add_argument("--package-assets", default="package-assets.json")
    parser.add_argument("--package-indexes", default="package-indexes.json")
    parser.add_argument("--output-dir", default="dist/gitee-mirror")
    parser.add_argument("--modelscope-synced", default=os.environ.get("SYNC_MODELSCOPE", "false"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    runtime_manifest = read_json(Path(args.runtime_manifest))
    modelscope_synced = parse_bool(str(args.modelscope_synced))

    cn_manifest = prepare_cn_runtime_manifest(runtime_manifest, modelscope_synced)
    runtime_output = output_dir / "runtime-packages.json"
    assets_output = output_dir / "package-assets.json"
    indexes_output = output_dir / "package-indexes.json"
    status_output = output_dir / "mirror-status.json"

    write_json(runtime_output, cn_manifest)
    write_json(
        assets_output,
        add_light_index_profile(read_json(Path(args.package_assets)), source_name="package-assets.json", runtime_manifest=runtime_manifest),
    )
    write_json(
        indexes_output,
        add_light_index_profile(read_json(Path(args.package_indexes)), source_name="package-indexes.json", runtime_manifest=runtime_manifest),
    )
    status = collect_status(cn_manifest, [runtime_output, assets_output, indexes_output], modelscope_synced)
    write_json(status_output, status)

    print(f"Wrote Gitee mirror files to {output_dir}")
    print(
        "ModelScope mirrors: "
        f"{status['modelscope']['repositoryMirrors']} repositories, "
        f"{status['modelscope']['packagePoolMirrors']} pools, "
        f"{status['modelscope']['bootstrapArtifactMirrors']} bootstrap artifacts."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
