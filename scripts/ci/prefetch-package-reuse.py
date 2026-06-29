#!/usr/bin/env python3
"""Prefetch PyStudio package repository snapshots for GitHub CI reuse."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request
from typing import Any

from component_index import deb_control_fields, decompress_member, read_ar_members, safe_extract_tar


DEFAULT_MANIFEST_URL = "https://raw.githubusercontent.com/vg188/pystudio-termux-builds/main/runtime-packages.json"


def fetch_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(url: str, destination: Path, expected_sha256: str = "") -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and (not expected_sha256 or sha256_file(destination) == expected_sha256):
        print(f"Using cached snapshot: {destination.name}")
        return

    tmp = destination.with_suffix(destination.suffix + ".part")
    with urllib.request.urlopen(url, timeout=300) as response, tmp.open("wb") as handle:
        total = int(response.headers.get("Content-Length", "0") or "0")
        done = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 / total
                print(f"Downloading {destination.name}: {pct:5.1f}% ({done}/{total} bytes)")
    if expected_sha256:
        actual = sha256_file(tmp)
        if actual != expected_sha256:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"sha256 mismatch for {destination.name}: {actual} != {expected_sha256}")
    tmp.replace(destination)


def repository_refs(entry: dict[str, Any], arch: str) -> list[str]:
    refs = entry.get("repositoryRefs", {}).get(arch)
    if isinstance(refs, str):
        return [refs]
    if isinstance(refs, list):
        return [str(ref) for ref in refs if str(ref)]
    return []


def github_snapshot_url(repository: dict[str, Any]) -> str:
    snapshot = repository.get("snapshot", {})
    url = str(snapshot.get("downloadUrl", ""))
    if "github.com/" in url:
        return url
    for mirror in repository.get("mirrors", []):
        if mirror.get("id") == "github-snapshot":
            return str(mirror.get("downloadUrl", ""))
    return url


def data_member_name(path: Path) -> str:
    for name, _payload in read_ar_members(path):
        if name.startswith("data.tar"):
            return name
    raise RuntimeError(f"{path} has no data.tar member")


def extract_deb_data_to_docker_data(deb: Path, docker_data_dir: Path) -> None:
    root = docker_data_dir.resolve()
    for name, payload in read_ar_members(deb):
        if not name.startswith("data.tar"):
            continue
        data = decompress_member(name, payload)
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            with tarfile.open(tmp_path, mode="r:*") as archive:
                for member in archive.getmembers():
                    normalized = member.name.lstrip("./")
                    if not normalized:
                        continue
                    target = (docker_data_dir / normalized).resolve()
                    if os.path.commonpath([root, target]) != str(root):
                        raise RuntimeError(f"unsafe deb data member path: {member.name}")
                archive.extractall(docker_data_dir)
        finally:
            tmp_path.unlink(missing_ok=True)
        return
    raise RuntimeError(f"{deb} has no {data_member_name(deb)} member")


def prefetch_repository(
    *,
    repository: dict[str, Any],
    output_dir: Path,
    docker_data_dir: Path,
    cache_dir: Path,
) -> set[str]:
    snapshot = repository.get("snapshot", {})
    url = github_snapshot_url(repository)
    if not url:
        raise RuntimeError(f"repository {repository.get('id')} has no GitHub snapshot URL")
    file_name = str(snapshot.get("fileName") or Path(url).name)
    archive_path = cache_dir / file_name
    expected_sha256 = str(snapshot.get("sha256", ""))
    print(f"Prefetching {repository.get('id')} from GitHub Releases")
    download_file(url, archive_path, expected_sha256)

    repo_dir = cache_dir / file_name.removesuffix(".tar.gz")
    if not (repo_dir / "pool" / "main").exists():
        shutil.rmtree(repo_dir, ignore_errors=True)
        safe_extract_tar(archive_path, repo_dir)

    marker_dir = docker_data_dir / "data" / ".built-packages"
    marker_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    reused: set[str] = set()
    for deb in sorted((repo_dir / "pool" / "main").rglob("*.deb")):
        fields = deb_control_fields(deb)
        package = fields.get("Package", "")
        version = fields.get("Version", "")
        if not package or not version:
            continue
        target = output_dir / deb.name
        if not target.exists():
            shutil.copy2(deb, target)
        (marker_dir / package).write_text(version + "\n", encoding="utf-8")
        extract_deb_data_to_docker_data(deb, docker_data_dir)
        reused.add(package)
    print(f"Reused {len(reused)} packages from {repository.get('id')}")
    return reused


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-url", default=DEFAULT_MANIFEST_URL)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--package-set", action="append", default=[])
    parser.add_argument("--requested-package", action="append", default=[])
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--docker-data-dir", required=True, type=Path)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--missing-packages-file", required=True, type=Path)
    args = parser.parse_args()

    requested = [str(item).strip() for item in args.requested_package if str(item).strip()]
    package_sets = [str(item).strip() for item in args.package_set if str(item).strip()]
    reused: set[str] = set()

    if package_sets:
        manifest = fetch_json(args.manifest_url)
        entries = {str(entry.get("id")): entry for entry in manifest.get("entries", [])}
        repositories = manifest.get("repositories", {})
        for package_set in package_sets:
            entry = entries.get(package_set)
            if not entry:
                print(f"Reuse package set not found in manifest: {package_set}")
                continue
            refs = repository_refs(entry, args.arch)
            if not refs:
                print(f"Reuse package set has no repository for {args.arch}: {package_set}")
                continue
            for repo_id in refs:
                repository = repositories.get(repo_id)
                if not repository:
                    print(f"Repository ref not found in manifest: {repo_id}")
                    continue
                reused.update(
                    prefetch_repository(
                        repository=repository,
                        output_dir=args.output_dir,
                        docker_data_dir=args.docker_data_dir,
                        cache_dir=args.cache_dir,
                    )
                )

    missing = [package for package in requested if package not in reused]
    args.missing_packages_file.parent.mkdir(parents=True, exist_ok=True)
    args.missing_packages_file.write_text("\n".join(missing) + ("\n" if missing else ""), encoding="utf-8")
    print(f"Requested packages: {', '.join(requested) if requested else '(none)'}")
    print(f"Reused requested packages: {', '.join([p for p in requested if p in reused]) or '(none)'}")
    print(f"Packages left for source build: {', '.join(missing) or '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
