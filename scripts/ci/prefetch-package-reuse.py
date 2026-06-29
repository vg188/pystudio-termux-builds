#!/usr/bin/env python3
"""Prefetch PyStudio flat package assets for GitHub CI reuse."""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.parse
import urllib.request
from typing import Any

from component_index import deb_control_fields, decompress_member, dependency_names, read_ar_members


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
        print(f"Using cached package asset: {destination.name}")
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


def flat_release_mirror(repository: dict[str, Any]) -> dict[str, Any] | None:
    mirrors = sorted(repository.get("mirrors", []), key=lambda item: int(item.get("priority", 1000)))
    for mirror in mirrors:
        if mirror.get("kind") == "flat-release-repo" and mirror.get("baseUrl") and mirror.get("indexUrl"):
            return mirror
    return None


def parse_packages_index(data: bytes) -> dict[str, dict[str, str]]:
    text = lzma.decompress(data).decode("utf-8", errors="replace")
    packages: dict[str, dict[str, str]] = {}
    for stanza in re_split_stanzas(text):
        fields: dict[str, str] = {}
        current = ""
        for line in stanza.splitlines():
            if not line:
                continue
            if line[0].isspace() and current:
                fields[current] += "\n" + line.strip()
                continue
            key, sep, value = line.partition(":")
            if sep:
                current = key
                fields[key] = value.strip()
        package = fields.get("Package", "")
        if package:
            packages[package] = fields
    return packages


def re_split_stanzas(text: str) -> list[str]:
    return [part.strip() for part in text.split("\n\n") if part.strip()]


def resolve_packages(index: dict[str, dict[str, str]], requested: list[str]) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()

    def visit(package: str) -> None:
        if package in seen or package not in index:
            return
        seen.add(package)
        fields = index[package]
        for dependency in dependency_names(",".join([fields.get("Pre-Depends", ""), fields.get("Depends", "")])):
            visit(dependency)
        resolved.append(package)

    for package in requested:
        visit(package)
    return resolved


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
    requested_packages: list[str],
    output_dir: Path,
    docker_data_dir: Path,
    cache_dir: Path,
) -> set[str]:
    mirror = flat_release_mirror(repository)
    if not mirror:
        print(f"Repository has no flat GitHub Release mirror, skipping: {repository.get('id')}")
        return set()

    index_name = Path(urllib.parse.urlparse(str(mirror["indexUrl"])).path).name
    index_path = cache_dir / index_name
    print(f"Prefetching index for {repository.get('id')} from GitHub Releases")
    download_file(str(mirror["indexUrl"]), index_path, str(repository.get("index", {}).get("sha256", "")))
    index = parse_packages_index(index_path.read_bytes())
    package_order = resolve_packages(index, requested_packages)
    if not package_order:
        print(f"No requested packages found in {repository.get('id')}")
        return set()

    marker_dir = docker_data_dir / "data" / ".built-packages"
    marker_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    reused: set[str] = set()
    for package in package_order:
        fields = index[package]
        filename = fields.get("Filename", "")
        if not filename:
            continue
        deb_url = urllib.parse.urljoin(str(mirror["baseUrl"]), filename)
        deb_path = cache_dir / Path(filename).name
        download_file(deb_url, deb_path, fields.get("SHA256", ""))
        if fields.get("Size", "").isdigit() and deb_path.stat().st_size != int(fields["Size"]):
            raise RuntimeError(f"size mismatch for {deb_path.name}")

        deb = deb_path
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
                        requested_packages=requested,
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
