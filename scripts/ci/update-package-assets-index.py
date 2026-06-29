#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import lzma
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


ARCHITECTURES = ["aarch64", "arm", "i686", "x86_64"]
RETRIES = 5
PACKAGE_METADATA_KEYS = [
    "fileName",
    "package",
    "version",
    "architecture",
    "sourceFileName",
    "installedSize",
    "size",
    "sha256",
    "depends",
    "preDepends",
    "provides",
    "conflicts",
    "replaces",
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
    pools = [pool for pool in repository.get("packagePools", []) if pool.get("architecture") == pool_arch]
    if pools:
        return [
            {
                "source": "package-pool",
                "mirrorId": pool.get("id", ""),
                "kind": pool.get("kind", ""),
                "architecture": pool_arch,
                "url": join_url(str(pool.get("baseUrl", "")), file_name),
                "release": pool.get("release", {}),
                "priority": pool.get("priority"),
                "region": pool.get("region", ""),
            }
            for pool in pools
        ]

    locations: list[dict[str, Any]] = []
    for mirror in repository.get("mirrors", []):
        base_url = str(mirror.get("baseUrl", ""))
        if not base_url:
            continue
        locations.append(
            {
                "source": "index-release",
                "mirrorId": mirror.get("id", ""),
                "kind": mirror.get("kind", ""),
                "architecture": repository.get("architecture", ""),
                "url": join_url(base_url, file_name),
                "release": repository.get("release", {}),
                "priority": mirror.get("priority"),
                "region": mirror.get("region", ""),
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


def base_package_record(file_name: str, package: dict[str, str]) -> dict[str, Any]:
    return {
        "fileName": file_name,
        "package": package.get("Package", ""),
        "version": package.get("Version", ""),
        "architecture": package.get("Architecture", ""),
        "sourceFileName": Path(package.get("Filename", "")).name,
        "installedSize": package.get("Installed-Size", ""),
        "size": package.get("Size", ""),
        "sha256": package.get("SHA256", ""),
        "depends": package.get("Depends", ""),
        "preDepends": package.get("Pre-Depends", ""),
        "provides": package.get("Provides", ""),
        "conflicts": package.get("Conflicts", ""),
        "replaces": package.get("Replaces", ""),
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


def package_record_from_existing(record: dict[str, Any]) -> dict[str, Any]:
    result = {key: record.get(key, "") for key in PACKAGE_METADATA_KEYS}
    result["locations"] = []
    result["usedBy"] = []
    return result


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
    source_name = str(package_records[file_name].get("sourceFileName", file_name))
    package_fields = {
        "Architecture": package_arch,
        "Filename": source_name,
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
        append_unique(entry_records[entry_id]["packageFiles"], file_name)


def build_index(manifest: dict[str, Any], token: str, existing_index: dict[str, Any] | None = None) -> dict[str, Any]:
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
            "packageFiles": [],
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
            "architecture": repository.get("architecture", ""),
            "release": repository.get("release", {}),
            "index": repository.get("index", {}),
            "metadata": repository.get("metadata", {}),
            "packagePools": repository.get("packagePools", []),
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
            record = package_records.setdefault(file_name, base_package_record(file_name, package))
            for location in mirror_locations(repository, package, file_name):
                append_location_unique(record["locations"], location)
            used_by = {
                "entryId": entry_id,
                "repositoryId": repository_id,
                "architecture": repository.get("architecture", ""),
            }
            append_unique(record["usedBy"], used_by)
            if entry_id in entry_records:
                append_unique(entry_records[entry_id]["packageFiles"], file_name)

    for repository in repository_records.values():
        repository["packageFiles"] = sorted(set(repository["packageFiles"]))
    for entry in entry_records.values():
        entry["packageFiles"] = sorted(entry["packageFiles"])

    return {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "sourceManifest": {
            "file": "runtime-packages.json",
            "schemaVersion": manifest.get("schemaVersion"),
            "generatedAt": manifest.get("generatedAt", ""),
        },
        "summary": {
            "entries": len(entry_records),
            "repositories": len(repository_records),
            "uniquePackageFiles": len(package_records),
            "packageFileUses": sum(len(record["usedBy"]) for record in package_records.values()),
            "reusedRepositoryIndexes": reused_repositories,
            "downloadedRepositoryIndexes": downloaded_repositories,
        },
        "entries": dict(sorted(entry_records.items())),
        "repositories": dict(sorted(repository_records.items())),
        "packages": dict(sorted(package_records.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a maintainer index for PyStudio package asset URLs.")
    parser.add_argument("--manifest", type=Path, default=Path("runtime-packages.json"))
    parser.add_argument("--output", type=Path, default=Path("package-assets-index.json"))
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--no-reuse", action="store_true", help="Ignore an existing output file and rebuild every index.")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    existing_index = None
    if args.output.exists() and not args.no_reuse:
        existing_index = json.loads(args.output.read_text(encoding="utf-8"))
    index = build_index(manifest, args.github_token, existing_index)
    args.output.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "Wrote "
        f"{args.output} with {index['summary']['uniquePackageFiles']} unique package files "
        f"across {index['summary']['repositories']} repositories."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
