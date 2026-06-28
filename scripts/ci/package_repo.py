from __future__ import annotations

import gzip
import hashlib
import json
import lzma
import re
import shutil
from pathlib import Path
from typing import Any

from component_index import (
    deb_command_names,
    deb_control_fields,
    dependency_names,
    find_debs,
    sha256_file,
)


ARCHES = ("aarch64", "arm", "i686", "x86_64")
PACKAGE_INDEX_FIELDS = (
    "Package",
    "Version",
    "Architecture",
    "Maintainer",
    "Installed-Size",
    "Depends",
    "Pre-Depends",
    "Recommends",
    "Conflicts",
    "Breaks",
    "Replaces",
    "Provides",
    "Description",
    "Homepage",
    "License",
    "Section",
    "Priority",
)


def sanitize_repo_part(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9+._-]+", "-", value).strip("-")
    return value or "unknown"


def pool_relative_path(package: str, deb_name: str) -> str:
    package_part = sanitize_repo_part(package)
    bucket = package_part[0].lower() if package_part else "x"
    return f"pool/main/{bucket}/{package_part}/{deb_name}"


def format_control_value(key: str, value: str) -> str:
    lines = str(value).splitlines() or [""]
    result = [f"{key}: {lines[0]}"]
    for line in lines[1:]:
        result.append(f" {line}")
    return "\n".join(result)


def package_index_stanza(fields: dict[str, str], extra: dict[str, str]) -> str:
    merged = dict(fields)
    merged.update(extra)

    ordered: list[str] = []
    seen: set[str] = set()
    for key in PACKAGE_INDEX_FIELDS:
        if key in merged:
            ordered.append(format_control_value(key, merged[key]))
            seen.add(key)
    for key in sorted(merged):
        if key not in seen:
            ordered.append(format_control_value(key, merged[key]))
    return "\n".join(ordered)


def write_compressed_indexes(packages_path: Path) -> None:
    data = packages_path.read_bytes()
    with gzip.open(packages_path.with_suffix(packages_path.suffix + ".gz"), "wb", compresslevel=9) as handle:
        handle.write(data)
    packages_path.with_suffix(packages_path.suffix + ".xz").write_bytes(lzma.compress(data, preset=9))


def digest_lines(root: Path, files: list[Path], algorithm: str) -> list[str]:
    lines: list[str] = []
    for path in files:
        data = path.read_bytes()
        digest = hashlib.new(algorithm, data).hexdigest()
        rel = path.relative_to(root).as_posix()
        lines.append(f" {digest} {len(data):16d} {rel}")
    return lines


def write_release_file(
    repo_dir: Path,
    *,
    distribution: str,
    component: str,
    arch: str,
    profile: str,
    source: str,
    version: str,
) -> None:
    index_dir = repo_dir / "dists" / distribution / component / f"binary-{arch}"
    index_files = [
        index_dir / "Packages",
        index_dir / "Packages.gz",
        index_dir / "Packages.xz",
    ]
    release_path = repo_dir / "dists" / distribution / "Release"
    release_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "Origin: PyStudio",
        "Label: PyStudio Runtime Packages",
        f"Suite: {distribution}",
        f"Codename: {distribution}",
        f"Version: {version}",
        f"Architectures: {arch}",
        f"Components: {component}",
        "Description: PyStudio app runtime package repository",
        f"PyStudio-Profile: {profile}",
        f"PyStudio-Source: {source}",
        "MD5Sum:",
        *digest_lines(repo_dir, index_files, "md5"),
        "SHA1:",
        *digest_lines(repo_dir, index_files, "sha1"),
        "SHA256:",
        *digest_lines(repo_dir, index_files, "sha256"),
        "",
    ]
    release_path.write_text("\n".join(lines), encoding="utf-8")


def build_package_repo(
    *,
    debs: list[Path],
    repo_dir: Path,
    profile: str,
    source: str,
    arch: str,
    artifact_prefix: str,
    version: str,
    distribution: str = "pystudio",
    component: str = "main",
) -> dict[str, Any]:
    if arch not in ARCHES:
        raise ValueError(f"unsupported architecture: {arch}")
    if not debs:
        raise ValueError("no .deb files provided")

    shutil.rmtree(repo_dir, ignore_errors=True)
    pool_root = repo_dir / "pool" / component
    index_dir = repo_dir / "dists" / distribution / component / f"binary-{arch}"
    pool_root.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)

    stanzas: list[str] = []
    packages: list[dict[str, Any]] = []
    for deb in sorted(debs, key=lambda item: item.name):
        fields = deb_control_fields(deb)
        package = fields.get("Package")
        deb_version = fields.get("Version")
        deb_arch = fields.get("Architecture", arch)
        if not package or not deb_version:
            raise ValueError(f"{deb} is missing Package or Version control field")

        rel_path = pool_relative_path(package, deb.name)
        target = repo_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(deb, target)

        sha256 = sha256_file(target)
        size = target.stat().st_size
        depends = fields.get("Depends", "")
        pre_depends = fields.get("Pre-Depends", "")
        commands = deb_command_names(deb)

        extra = {
            "Filename": rel_path,
            "Size": str(size),
            "SHA256": sha256,
            "PyStudio-Profile": profile,
            "PyStudio-Source": source,
        }
        if commands:
            extra["PyStudio-Commands"] = ", ".join(commands)

        stanzas.append(package_index_stanza(fields, extra))
        packages.append(
            {
                "package": package,
                "version": deb_version,
                "architecture": arch if deb_arch == "all" else deb_arch,
                "debArchitecture": deb_arch,
                "fileName": deb.name,
                "filename": rel_path,
                "size": size,
                "sha256": sha256,
                "depends": depends,
                "preDepends": pre_depends,
                "dependencyNames": dependency_names(",".join([pre_depends, depends])),
                "commands": commands,
            }
        )

    packages_path = index_dir / "Packages"
    packages_path.write_text("\n\n".join(stanzas) + "\n", encoding="utf-8")
    write_compressed_indexes(packages_path)
    write_release_file(
        repo_dir,
        distribution=distribution,
        component=component,
        arch=arch,
        profile=profile,
        source=source,
        version=version,
    )

    metadata = {
        "schemaVersion": 1,
        "kind": "apt-repository",
        "format": "apt-repo-v1",
        "profile": profile,
        "source": source,
        "architecture": arch,
        "artifactPrefix": artifact_prefix,
        "version": version,
        "distribution": distribution,
        "component": component,
        "binaryPath": f"dists/{distribution}/{component}/binary-{arch}",
        "indexPath": f"dists/{distribution}/{component}/binary-{arch}/Packages.xz",
        "packageCount": len(packages),
        "packages": packages,
    }
    (repo_dir / "repo-metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return metadata


def build_repo_from_path(
    *,
    input_path: Path,
    repo_dir: Path,
    profile: str,
    source: str,
    arch: str,
    artifact_prefix: str,
    version: str,
    distribution: str = "pystudio",
    component: str = "main",
) -> dict[str, Any]:
    debs = find_debs(input_path)
    if not debs:
        raise ValueError(f"no .deb files found in {input_path}")
    return build_package_repo(
        debs=debs,
        repo_dir=repo_dir,
        profile=profile,
        source=source,
        arch=arch,
        artifact_prefix=artifact_prefix,
        version=version,
        distribution=distribution,
        component=component,
    )
