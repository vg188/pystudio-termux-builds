#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import lzma
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


ARCHITECTURES = ["aarch64", "arm", "i686", "x86_64"]
RETRIES = 5
ASSET_PACKAGE_KEYS = [
    "fileName",
    "package",
    "version",
    "architecture",
    "size",
    "sha256",
]
PACKAGE_CACHE_KEYS = [
    *ASSET_PACKAGE_KEYS,
    "debArchitecture",
    "depends",
    "preDepends",
    "dependencyNames",
    "commands",
    "profile",
    "source",
    "sourceRepository",
    "sourceCommit",
    "patchSet",
    "patchHash",
    "treeDiffHash",
    "recipePath",
    "recipeHash",
]


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def release_asset_name(file_name: str) -> str:
    return Path(file_name).name.replace(":", ".")


def headers(token: str) -> dict[str, str]:
    result = {
        "Accept": "application/octet-stream",
        "User-Agent": "pystudio-package-assets-index",
    }
    if token:
        result["Authorization"] = f"Bearer {token}"
        result["X-GitHub-Api-Version"] = "2022-11-28"
    return result


def download_bytes(url: str, token: str) -> bytes:
    request = urllib.request.Request(url, headers=headers(token))
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return response.read()
        except (urllib.error.HTTPError, urllib.error.URLError):
            if attempt == RETRIES:
                raise
            time.sleep(attempt * 3)
    raise RuntimeError(f"could not download {url}")


def decode_index(data: bytes) -> str:
    try:
        return lzma.decompress(data).decode("utf-8", errors="replace")
    except lzma.LZMAError:
        return data.decode("utf-8", errors="replace")


def parse_packages_index(text: str) -> list[dict[str, str]]:
    packages: list[dict[str, str]] = []
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
        if fields.get("Package") and fields.get("Filename"):
            packages.append(fields)
    return packages


def join_url(base_url: str, file_name: str) -> str:
    return urllib.parse.urljoin(base_url, urllib.parse.quote(file_name, safe=""))


def repository_index_url(repository: dict[str, Any]) -> str:
    index = repository.get("index", {})
    if index.get("downloadUrl"):
        return str(index["downloadUrl"])
    for mirror in repository.get("mirrors", []):
        if mirror.get("indexUrl"):
            return str(mirror["indexUrl"])
    raise RuntimeError(f"repository {repository.get('id')} has no index URL")


def mirror_locations(
    repository: dict[str, Any],
    package: dict[str, str],
    file_name: str,
) -> list[dict[str, Any]]:
    package_arch = package.get("Architecture") or repository.get("architecture", "")
    pool_arch = "all" if package_arch == "all" else str(repository.get("architecture", ""))
    pools = [
        pool
        for pool in repository.get("packagePools", [])
        if pool.get("kind") == "flat-release-pool" and pool.get("architecture") == pool_arch
    ]
    if pools:
        return [
            {
                "source": "package-pool",
                "architecture": pool_arch,
                "url": join_url(str(pool.get("baseUrl", "")), file_name),
                "release": pool.get("release", {}),
            }
            for pool in pools
        ]

    locations: list[dict[str, Any]] = []
    for mirror in repository.get("mirrors", []):
        if mirror.get("kind") != "flat-release-repo":
            continue
        base_url = str(mirror.get("baseUrl", ""))
        if not base_url:
            continue
        locations.append(
            {
                "source": "index-release",
                "architecture": repository.get("architecture", ""),
                "url": join_url(base_url, file_name),
                "release": repository.get("release", {}),
            }
        )
    return locations


def entry_repository_map(manifest: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for entry in manifest.get("entries", []):
        entry_id = str(entry.get("id", ""))
        for repository_id in (entry.get("repositoryRefs") or {}).values():
            mapping[str(repository_id)] = entry_id
    return mapping


def base_package_record(file_name: str, package: dict[str, str], repository: dict[str, Any]) -> dict[str, Any]:
    deb_architecture = package.get("Architecture", "")
    architecture = str(repository.get("architecture", ""))
    if deb_architecture and deb_architecture != "all":
        architecture = deb_architecture
    depends = package.get("Depends", "")
    pre_depends = package.get("Pre-Depends", "")
    return {
        "fileName": file_name,
        "package": package.get("Package", ""),
        "version": package.get("Version", ""),
        "architecture": architecture,
        "debArchitecture": deb_architecture,
        "size": package.get("Size", ""),
        "sha256": package.get("SHA256", ""),
        "depends": depends,
        "preDepends": pre_depends,
        "dependencyNames": dependency_names(",".join([pre_depends, depends])),
        "commands": command_names(package.get("PyStudio-Commands", "")),
        "profile": package.get("PyStudio-Profile", repository.get("profile", "")),
        "source": package.get("PyStudio-Source", repository.get("sourceAdapter", "")),
        "sourceRepository": package.get("PyStudio-Source-Repository", ""),
        "sourceCommit": package.get("PyStudio-Source-Commit", ""),
        "patchSet": package.get("PyStudio-Patch-Set", ""),
        "patchHash": package.get("PyStudio-Patch-Hash", ""),
        "treeDiffHash": package.get("PyStudio-Tree-Diff-Hash", ""),
        "recipePath": package.get("PyStudio-Recipe-Path", ""),
        "recipeHash": package.get("PyStudio-Recipe-Hash", ""),
        "locations": [],
        "usedBy": [],
    }


def append_unique(items: list[Any], value: Any) -> None:
    if value not in items:
        items.append(value)


def append_location_unique(items: list[dict[str, Any]], location: dict[str, Any]) -> None:
    url = location.get("url")
    if not any(item.get("url") == url for item in items):
        items.append(location)


def dependency_names(value: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for group in value.split(","):
        for alternative in group.split("|"):
            match = re.match(r"\s*([A-Za-z0-9+.-]+)", alternative)
            if not match:
                continue
            name = match.group(1)
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def package_record_from_existing(record: dict[str, Any]) -> dict[str, Any]:
    result = {key: record.get(key, "") for key in PACKAGE_CACHE_KEYS}
    result["dependencyNames"] = list(record.get("dependencyNames", []))
    result["commands"] = list(record.get("commands", []))
    result["locations"] = []
    result["usedBy"] = []
    return result


def command_names(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def compact_package_record(record: dict[str, Any]) -> dict[str, Any]:
    required_keys = (
        "fileName",
        "package",
        "version",
        "architecture",
        "debArchitecture",
        "size",
        "sha256",
    )
    optional_keys = (
        "depends",
        "preDepends",
        "dependencyNames",
        "commands",
        "profile",
        "source",
        "sourceRepository",
        "sourceCommit",
        "patchSet",
        "patchHash",
        "treeDiffHash",
        "recipePath",
        "recipeHash",
    )
    compact = {key: record.get(key, "") for key in required_keys}
    for key in optional_keys:
        value = record.get(key)
        if value:
            compact[key] = value

    github = record.get("github", {})
    compact_github = {key: value for key, value in github.items() if value}
    if compact_github:
        compact["github"] = compact_github
    return compact


def single_or_list(values: set[str]) -> str | list[str]:
    cleaned = sorted(value for value in values if value)
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    return cleaned


def batch_key(repository: dict[str, Any]) -> tuple[str, str, str, str, str]:
    release = repository.get("release", {})
    return (
        str(release.get("repository", "")),
        str(release.get("tag", "")),
        str(repository.get("profile", "")),
        str(repository.get("sourceAdapter", "")),
        str(repository.get("version", "")),
    )


def build_batch_manifest(
    *,
    generated_at: str,
    source_manifest: dict[str, Any],
    package_records: dict[str, dict[str, Any]],
    repository_records: dict[str, dict[str, Any]],
    entry_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    batches: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}

    for repository_id, repository in sorted(repository_records.items()):
        release_repository, release_tag, profile, source, version = batch_key(repository)
        key = (release_repository, release_tag, profile, source, version)
        batch_id_parts = [profile, source, version or release_tag]
        batch = batches.setdefault(
            key,
            {
                "id": ":".join(part for part in batch_id_parts if part),
                "profile": profile,
                "source": source,
                "version": version,
                "release": {
                    "repository": release_repository,
                    "tag": release_tag,
                },
                "architectures": set(),
                "entries": {},
                "repositories": {},
                "packageFiles": set(),
                "packageRecords": {},
                "sourceRepositories": set(),
                "sourceCommits": set(),
                "patchSets": set(),
                "patchHashes": set(),
                "treeDiffHashes": set(),
            },
        )

        architecture = str(repository.get("architecture", ""))
        if architecture:
            batch["architectures"].add(architecture)
            batch["repositories"][architecture] = repository_id

        entry_id = str(repository.get("entryId", ""))
        if entry_id and entry_id in entry_records:
            entry = entry_records[entry_id]
            batch["entries"][entry_id] = {
                "id": entry_id,
                "group": entry.get("group", ""),
                "title": entry.get("title", ""),
            }

        for file_name in repository.get("packageFiles", []):
            record = package_records.get(file_name, {})
            package_name = str(record.get("package", ""))
            package_version = str(record.get("version", ""))
            if not package_name:
                continue
            package_key = (package_name, package_version)
            package_summary = batch["packageRecords"].setdefault(
                package_key,
                {
                    "name": package_name,
                    "versions": set(),
                    "architectures": set(),
                    "files": set(),
                },
            )
            if package_version:
                package_summary["versions"].add(package_version)
            if architecture:
                package_summary["architectures"].add(architecture)
            package_summary["files"].add(file_name)
            batch["packageFiles"].add(file_name)

            for source_key, batch_key_name in (
                ("sourceRepository", "sourceRepositories"),
                ("sourceCommit", "sourceCommits"),
                ("patchSet", "patchSets"),
                ("patchHash", "patchHashes"),
                ("treeDiffHash", "treeDiffHashes"),
            ):
                value = str(record.get(source_key, ""))
                if value:
                    batch[batch_key_name].add(value)

    normalized_batches: list[dict[str, Any]] = []
    for batch in batches.values():
        package_summaries = []
        for package in batch.pop("packageRecords").values():
            package_summaries.append(
                {
                    "name": package["name"],
                    "versions": sorted(package["versions"]),
                    "architectures": sorted(package["architectures"]),
                    "fileCount": len(package["files"]),
                }
            )

        package_files = batch.pop("packageFiles")
        source_repositories = batch.pop("sourceRepositories")
        source_commits = batch.pop("sourceCommits")
        patch_sets = batch.pop("patchSets")
        patch_hashes = batch.pop("patchHashes")
        tree_diff_hashes = batch.pop("treeDiffHashes")

        normalized_batches.append(
            {
                **batch,
                "architectures": sorted(batch["architectures"]),
                "entries": [batch["entries"][key] for key in sorted(batch["entries"])],
                "repositories": dict(sorted(batch["repositories"].items())),
                "summary": {
                    "packageNames": len({package["name"] for package in package_summaries}),
                    "packageVersions": len(package_summaries),
                    "packageFiles": len(package_files),
                },
                "sourceMetadata": {
                    "sourceRepository": single_or_list(source_repositories),
                    "sourceCommit": single_or_list(source_commits),
                    "patchSet": single_or_list(patch_sets),
                    "patchHash": single_or_list(patch_hashes),
                    "treeDiffHash": single_or_list(tree_diff_hashes),
                },
                "packages": sorted(package_summaries, key=lambda item: (item["name"], item["versions"])),
            }
        )

    normalized_batches.sort(
        key=lambda item: (
            str(item.get("profile", "")),
            str(item.get("source", "")),
            str((item.get("release") or {}).get("tag", "")),
        )
    )

    return {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "sourceManifest": source_manifest,
        "summary": {
            "batches": len(normalized_batches),
            "entries": len(entry_records),
            "repositories": len(repository_records),
            "uniquePackageFiles": len(package_records),
        },
        "batches": normalized_batches,
    }


def repository_index_unchanged(repository: dict[str, Any], old_repository: dict[str, Any] | None) -> bool:
    if not old_repository:
        return False
    index = repository.get("index", {})
    old_index = old_repository.get("index", {})
    sha256 = index.get("sha256")
    old_sha256 = old_index.get("sha256")
    if sha256 and old_sha256:
        return sha256 == old_sha256
    return (
        index.get("downloadUrl") == old_index.get("downloadUrl")
        and index.get("size") == old_index.get("size")
        and index.get("fileName") == old_index.get("fileName")
    )


def merge_package_use(
    package_records: dict[str, dict[str, Any]],
    entry_records: dict[str, dict[str, Any]],
    repository_id: str,
    repository: dict[str, Any],
    entry_id: str,
    record: dict[str, Any],
) -> None:
    file_name = str(record["fileName"])
    package_records.setdefault(file_name, package_record_from_existing(record))
    package_arch = str(package_records[file_name].get("architecture", ""))
    package_fields = {
        "Architecture": package_arch,
        "Filename": file_name,
    }
    for location in mirror_locations(repository, package_fields, file_name):
        append_location_unique(package_records[file_name]["locations"], location)
    used_by = {
        "entryId": entry_id,
        "repositoryId": repository_id,
        "architecture": repository.get("architecture", ""),
    }
    append_unique(package_records[file_name]["usedBy"], used_by)
    if entry_id in entry_records:
        entry_records[entry_id]["packageUseCount"] = int(entry_records[entry_id].get("packageUseCount", 0)) + 1


def build_indexes(manifest: dict[str, Any], token: str, existing_index: dict[str, Any] | None = None) -> dict[str, Any]:
    repositories = manifest.get("repositories", {})
    repo_to_entry = entry_repository_map(manifest)
    entries_by_id = {str(entry.get("id", "")): entry for entry in manifest.get("entries", [])}
    old_repositories = (existing_index or {}).get("repositories", {})
    old_packages = (existing_index or {}).get("packages", {})

    package_records: dict[str, dict[str, Any]] = {}
    repository_records: dict[str, dict[str, Any]] = {}
    entry_records: dict[str, dict[str, Any]] = {}
    reused_repositories = 0
    downloaded_repositories = 0

    for entry_id, entry in entries_by_id.items():
        entry_records[entry_id] = {
            "id": entry_id,
            "kind": entry.get("kind", ""),
            "group": entry.get("group", ""),
            "title": entry.get("title", ""),
            "release": entry.get("release", {}),
            "availableArchitectures": entry.get("availableArchitectures", []),
            "repositoryRefs": entry.get("repositoryRefs", {}),
            "packageUseCount": 0,
        }

    for repository_id in sorted(repositories):
        repository = repositories[repository_id]
        entry_id = repo_to_entry.get(repository_id, "")
        old_repository = old_repositories.get(repository_id)
        package_files: list[str] = []

        repository_records[repository_id] = {
            "id": repository_id,
            "entryId": entry_id,
            "profile": repository.get("profile", ""),
            "sourceAdapter": repository.get("sourceAdapter", ""),
            "architecture": repository.get("architecture", ""),
            "version": repository.get("version", ""),
            "release": repository.get("release", {}),
            "index": repository.get("index", {}),
            "packageCount": 0,
            "packageFiles": package_files,
        }

        if repository_index_unchanged(repository, old_repository) and all(
            file_name in old_packages for file_name in old_repository.get("packageFiles", [])
        ):
            reused_repositories += 1
            repository_records[repository_id]["packageCount"] = old_repository.get(
                "packageCount",
                len(old_repository.get("packageFiles", [])),
            )
            for file_name in old_repository.get("packageFiles", []):
                package_files.append(file_name)
                merge_package_use(
                    package_records,
                    entry_records,
                    repository_id,
                    repository,
                    entry_id,
                    old_packages[file_name],
                )
            continue

        downloaded_repositories += 1
        index_url = repository_index_url(repository)
        packages = parse_packages_index(decode_index(download_bytes(index_url, token)))
        repository_records[repository_id]["packageCount"] = len(packages)
        for package in packages:
            file_name = release_asset_name(package.get("Filename", ""))
            if not file_name.endswith(".deb"):
                continue
            package_files.append(file_name)
            record = package_records.setdefault(file_name, base_package_record(file_name, package, repository))
            for location in mirror_locations(repository, package, file_name):
                append_location_unique(record["locations"], location)
            used_by = {
                "entryId": entry_id,
                "repositoryId": repository_id,
                "architecture": repository.get("architecture", ""),
            }
            append_unique(record["usedBy"], used_by)
            if entry_id in entry_records:
                entry_records[entry_id]["packageUseCount"] = int(entry_records[entry_id].get("packageUseCount", 0)) + 1

    for repository in repository_records.values():
        repository["packageFiles"] = sorted(set(repository["packageFiles"]))

    generated_at = now_iso()
    source_manifest = {
        "file": "runtime-packages.json",
        "schemaVersion": manifest.get("schemaVersion"),
        "generatedAt": manifest.get("generatedAt", ""),
    }
    asset_packages: dict[str, dict[str, Any]] = {}
    for file_name, record in sorted(package_records.items()):
        asset_packages[file_name] = {
            key: record.get(key, "")
            for key in ASSET_PACKAGE_KEYS
        }
        asset_packages[file_name]["locations"] = record.get("locations", [])

    index_packages: list[dict[str, Any]] = []
    cache_packages: dict[str, dict[str, Any]] = {}
    for file_name, record in sorted(package_records.items()):
        github_location = next(
            (location for location in record.get("locations", []) if "github.com" in str(location.get("url", ""))),
            {},
        )
        github_release = github_location.get("release", {})
        index_packages.append(
            compact_package_record(
                {
                    **record,
                    "github": {
                        "repository": github_release.get("repository", ""),
                        "tag": github_release.get("tag", ""),
                        "assetName": record.get("fileName", file_name),
                        "url": github_location.get("url", ""),
                    },
                }
            )
        )
        cache_packages[file_name] = {
            key: record.get(key, "")
            for key in PACKAGE_CACHE_KEYS
        }
        cache_packages[file_name]["dependencyNames"] = record.get("dependencyNames", [])
        cache_packages[file_name]["commands"] = record.get("commands", [])

    return {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "sourceManifest": source_manifest,
        "assets": {
            "schemaVersion": 1,
            "generatedAt": generated_at,
            "sourceManifest": source_manifest,
            "summary": {
                "uniquePackageFiles": len(package_records),
                "githubLocations": sum(len(record["locations"]) for record in package_records.values()),
            },
            "packages": asset_packages,
        },
        "indexes": {
            "schemaVersion": 2,
            "generatedAt": generated_at,
            "sourceManifest": source_manifest,
            "summary": {
                "uniquePackageFiles": len(package_records),
                "architectures": sorted(
                    {
                        str(record.get("architecture", ""))
                        for record in package_records.values()
                        if record.get("architecture")
                    }
                ),
            },
            "packages": index_packages,
        },
        "cache": {
            "schemaVersion": 1,
            "generatedAt": generated_at,
            "sourceManifest": source_manifest,
            "summary": {
                "entries": len(entry_records),
                "repositories": len(repository_records),
                "uniquePackageFiles": len(package_records),
                "packageFileUses": sum(len(record["usedBy"]) for record in package_records.values()),
                "reusedRepositoryIndexes": reused_repositories,
                "downloadedRepositoryIndexes": downloaded_repositories,
            },
            "repositories": dict(sorted(repository_records.items())),
            "packages": cache_packages,
        },
        "batches": build_batch_manifest(
            generated_at=generated_at,
            source_manifest=source_manifest,
            package_records=package_records,
            repository_records=repository_records,
            entry_records=entry_records,
        ),
    }


def load_existing_indexes(
    assets_output: Path,
    indexes_output: Path,
    cache_output: Path,
    legacy_output: Path,
    *,
    no_reuse: bool,
) -> dict[str, Any] | None:
    if no_reuse:
        return None
    if cache_output.exists():
        cache = json.loads(cache_output.read_text(encoding="utf-8"))
        packages = cache.get("packages", {})
        if isinstance(packages, dict):
            return {
                "packages": packages,
                "repositories": cache.get("repositories", {}),
            }
    if assets_output.exists() and indexes_output.exists():
        assets = json.loads(assets_output.read_text(encoding="utf-8"))
        indexes = json.loads(indexes_output.read_text(encoding="utf-8"))
        packages = indexes.get("packages") or assets.get("packages", {})
        repositories = indexes.get("repositories", {})
        if indexes.get("schemaVersion") == 2 and isinstance(packages, dict) and repositories:
            return {
                "packages": packages,
                "repositories": repositories,
            }
    if legacy_output.exists():
        legacy = json.loads(legacy_output.read_text(encoding="utf-8"))
        packages = legacy.get("packages", {})
        repositories = legacy.get("repositories", {})
        if isinstance(packages, dict) and repositories:
            return {
                "packages": packages,
                "repositories": repositories,
            }
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a maintainer index for PyStudio package asset URLs.")
    parser.add_argument("--manifest", type=Path, default=Path("runtime-packages.json"))
    parser.add_argument("--assets-output", type=Path, default=Path("package-assets.json"))
    parser.add_argument("--indexes-output", type=Path, default=Path("package-indexes.json"))
    parser.add_argument("--cache-output", type=Path, default=Path("package-index-cache.json"))
    parser.add_argument("--batches-output", type=Path, default=Path("package-build-batches.json"))
    parser.add_argument("--legacy-output", type=Path, default=Path("package-assets-index.json"))
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--no-reuse", action="store_true", help="Ignore existing index files and rebuild every index.")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    existing_index = load_existing_indexes(
        args.assets_output,
        args.indexes_output,
        args.cache_output,
        args.legacy_output,
        no_reuse=args.no_reuse,
    )
    indexes = build_indexes(manifest, args.github_token, existing_index)
    args.assets_output.write_text(json.dumps(indexes["assets"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.indexes_output.write_text(json.dumps(indexes["indexes"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.cache_output.write_text(json.dumps(indexes["cache"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.batches_output.write_text(json.dumps(indexes["batches"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "Wrote "
        f"{args.assets_output} with {indexes['assets']['summary']['uniquePackageFiles']} unique package files "
        f"and {args.indexes_output} with {indexes['indexes']['summary']['uniquePackageFiles']} package records "
        f"plus {args.batches_output} with {indexes['batches']['summary']['batches']} build batches "
        f"using {args.cache_output} "
        f"({indexes['cache']['summary']['reusedRepositoryIndexes']} reused, "
        f"{indexes['cache']['summary']['downloadedRepositoryIndexes']} downloaded)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
