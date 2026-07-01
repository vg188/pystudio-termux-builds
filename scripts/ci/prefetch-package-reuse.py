#!/usr/bin/env python3
"""Prefetch PyStudio flat package assets for GitHub CI reuse."""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import os
import re
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


def load_build_metadata(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def package_recipe_dir(source_root: Path | None, package: str) -> Path | None:
    if not source_root:
        return None
    for parent in ("packages", "root-packages", "x11-packages", "tur", "disabled-packages"):
        candidate = source_root / parent / package
        if candidate.is_dir():
            return candidate
    return None


def recipe_dir_from_fields(source_root: Path | None, fields: dict[str, str]) -> Path | None:
    if not source_root:
        return None
    recipe_path = fields.get("PyStudio-Recipe-Path", "").strip()
    if recipe_path:
        candidate = (source_root / recipe_path).resolve()
        try:
            candidate.relative_to(source_root.resolve())
        except ValueError:
            return None
        if candidate.is_dir():
            return candidate
    return package_recipe_dir(source_root, fields.get("Package", ""))


def shell_assignment_value(path: Path, name: str) -> str:
    if not path.exists():
        return ""
    pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(name)}=(?P<value>.+?)\s*$")
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.match(raw_line)
        if not match:
            continue
        value = match.group("value").split("#", 1)[0].strip()
        if not value or value.startswith("(") or "$" in value or "`" in value:
            return ""
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            return value[1:-1]
        return value
    return ""


def recipe_debian_version(recipe_dir: Path) -> str:
    build_sh = recipe_dir / "build.sh"
    version = shell_assignment_value(build_sh, "TERMUX_PKG_VERSION")
    if not version:
        return ""
    revision = shell_assignment_value(build_sh, "TERMUX_PKG_REVISION")
    if revision and revision != "0":
        return f"{version}-{revision}"
    return version


def directory_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(child for child in path.rglob("*") if child.is_file()):
        rel = item.relative_to(path).as_posix()
        digest.update(rel.encode("utf-8") + b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
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


def package_pool_url(repository: dict[str, Any], fields: dict[str, str], fallback_mirror: dict[str, Any]) -> str:
    filename = fields.get("Filename", "")
    deb_name = Path(filename).name
    deb_arch = fields.get("Architecture", str(repository.get("architecture", "")))
    wanted = [deb_arch]
    if deb_arch != "all":
        wanted.append("all")
    pools = sorted(repository.get("packagePools", []), key=lambda item: int(item.get("priority", 1000)))
    for arch in wanted:
        for pool in pools:
            if pool.get("kind") == "flat-release-pool" and pool.get("architecture") == arch and pool.get("baseUrl"):
                return urllib.parse.urljoin(str(pool["baseUrl"]), deb_name)
    return urllib.parse.urljoin(str(fallback_mirror["baseUrl"]), filename)


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
    failed: set[str] = set()

    def visit(package: str) -> bool:
        if package in failed:
            return False
        if package in seen:
            return True
        if package not in index:
            failed.add(package)
            return False
        seen.add(package)
        fields = index[package]
        dependencies_ok = True
        for dependency in dependency_names(",".join([fields.get("Pre-Depends", ""), fields.get("Depends", "")])):
            if not visit(dependency):
                dependencies_ok = False
        if not dependencies_ok:
            failed.add(package)
            return False
        resolved.append(package)
        return True

    for package in requested:
        visit(package)
    return resolved


def freshness_problem(
    fields: dict[str, str],
    *,
    target_arch: str,
    source_root: Path | None,
    build_metadata: dict[str, Any],
) -> str:
    package_arch = fields.get("Architecture", "")
    if package_arch and package_arch not in {target_arch, "all"}:
        return f"architecture mismatch ({package_arch} != {target_arch})"

    if not build_metadata:
        return ""

    expected_patch_set = str(build_metadata.get("patchSet", "") or "")
    expected_patch_hash = str(build_metadata.get("patchHash", "") or "")
    actual_patch_set = fields.get("PyStudio-Patch-Set", "")
    actual_patch_hash = fields.get("PyStudio-Patch-Hash", "")
    if expected_patch_set and actual_patch_set != expected_patch_set:
        return f"patch set mismatch ({actual_patch_set or 'missing'} != {expected_patch_set})"
    if expected_patch_hash and actual_patch_hash != expected_patch_hash:
        return "patch hash mismatch"

    recipe_dir = recipe_dir_from_fields(source_root, fields)
    actual_version = fields.get("Version", "")
    if recipe_dir:
        expected_version = recipe_debian_version(recipe_dir)
        if not expected_version:
            return "current recipe version unavailable"
        if actual_version != expected_version:
            return f"version mismatch ({actual_version or 'missing'} != {expected_version})"

    expected_recipe_hash = directory_sha256(recipe_dir) if recipe_dir else ""
    actual_recipe_hash = fields.get("PyStudio-Recipe-Hash", "")
    if expected_recipe_hash:
        if not actual_recipe_hash:
            return "missing recipe hash"
        if actual_recipe_hash != expected_recipe_hash:
            return "recipe hash mismatch"

    expected_source_commit = str(build_metadata.get("sourceCommit", "") or "")
    actual_source_commit = fields.get("PyStudio-Source-Commit", "")
    if expected_source_commit and not expected_recipe_hash and actual_source_commit != expected_source_commit:
        return f"source commit mismatch ({actual_source_commit or 'missing'} != {expected_source_commit})"

    return ""


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
    source_root: Path | None,
    build_metadata: dict[str, Any],
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
    fresh_index: dict[str, dict[str, str]] = {}
    for package, fields in index.items():
        problem = freshness_problem(
            fields,
            target_arch=str(repository.get("architecture", "")),
            source_root=source_root,
            build_metadata=build_metadata,
        )
        if problem:
            print(f"Skipping stale reusable package {package} from {repository.get('id')}: {problem}")
            continue
        fresh_index[package] = fields
    index = fresh_index
    package_order = resolve_packages(index, requested_packages)
    if not package_order:
        print(f"No requested packages found in {repository.get('id')}")
        return set()

    marker_dir = docker_data_dir / "data" / ".built-packages"
    marker_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    reused: set[str] = set()
    for package in package_order:
        index_fields = index[package]
        filename = index_fields.get("Filename", "")
        if not filename:
            continue
        deb_url = package_pool_url(repository, index_fields, mirror)
        deb_path = cache_dir / Path(filename).name
        download_file(deb_url, deb_path, index_fields.get("SHA256", ""))
        if index_fields.get("Size", "").isdigit() and deb_path.stat().st_size != int(index_fields["Size"]):
            raise RuntimeError(f"size mismatch for {deb_path.name}")

        deb = deb_path
        fields = deb_control_fields(deb)
        package = fields.get("Package", "")
        version = fields.get("Version", "")
        if not package or not version:
            continue
        if package != index_fields.get("Package", ""):
            raise RuntimeError(f"package mismatch for {deb.name}: {package} != {index_fields.get('Package', '')}")
        if version != index_fields.get("Version", ""):
            raise RuntimeError(f"version mismatch for {deb.name}: {version} != {index_fields.get('Version', '')}")
        deb_arch = fields.get("Architecture", "")
        index_arch = index_fields.get("Architecture", "")
        if deb_arch != index_arch:
            raise RuntimeError(f"architecture mismatch for {deb.name}: {deb_arch} != {index_arch}")
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
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--build-metadata", type=Path)
    args = parser.parse_args()

    requested = [str(item).strip() for item in args.requested_package if str(item).strip()]
    package_sets = [str(item).strip() for item in args.package_set if str(item).strip()]
    build_metadata = load_build_metadata(args.build_metadata)
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
                        source_root=args.source_root,
                        build_metadata=build_metadata,
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
