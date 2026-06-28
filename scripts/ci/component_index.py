from __future__ import annotations

import gzip
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import re
import shutil
import tarfile
import urllib.parse
from typing import Any


def read_ar_members(path: Path) -> list[tuple[str, bytes]]:
    data = path.read_bytes()
    if not data.startswith(b"!<arch>\n"):
        raise ValueError(f"{path} is not a Debian ar archive")

    members: list[tuple[str, bytes]] = []
    offset = 8
    while offset + 60 <= len(data):
        header = data[offset : offset + 60]
        offset += 60
        name = header[:16].decode("utf-8", errors="replace").strip()
        size = int(header[48:58].decode("ascii").strip())
        payload = data[offset : offset + size]
        offset += size + (size % 2)
        if name.endswith("/"):
            name = name[:-1]
        members.append((name, payload))
    return members


def decompress_member(name: str, payload: bytes) -> bytes:
    if name.endswith(".xz"):
        return lzma.decompress(payload)
    if name.endswith(".gz"):
        return gzip.decompress(payload)
    if name.endswith(".tar"):
        return payload
    raise ValueError(f"unsupported tar member compression: {name}")


def parse_control(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    current = ""
    for line in text.splitlines():
        if not line:
            continue
        if line[0].isspace() and current:
            fields[current] += "\n" + line.strip()
            continue
        key, sep, value = line.partition(":")
        if sep:
            current = key
            fields[key] = value.strip()
    return fields


def deb_control_fields(path: Path) -> dict[str, str]:
    for name, payload in read_ar_members(path):
        if not name.startswith("control.tar"):
            continue
        data = decompress_member(name, payload)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
            control = archive.extractfile("./control") or archive.extractfile("control")
            if control is None:
                raise ValueError(f"{path} has no control file")
            return parse_control(control.read().decode("utf-8", errors="replace"))
    raise ValueError(f"{path} has no control.tar member")


def deb_command_names(path: Path) -> list[str]:
    commands: list[str] = []
    seen: set[str] = set()
    for name, payload in read_ar_members(path):
        if not name.startswith("data.tar"):
            continue
        data = decompress_member(name, payload)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
            for member in archive.getmembers():
                normalized = member.name.lstrip("./")
                if "/bin/" not in normalized:
                    continue
                if not (member.isfile() and member.mode & 0o111) and not member.issym():
                    continue
                command = Path(normalized).name
                if command and command not in seen:
                    seen.add(command)
                    commands.append(command)
        return commands
    return commands


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def component_id(package: str, version: str, architecture: str) -> str:
    quoted_version = urllib.parse.quote(version, safe="")
    return f"deb:{architecture}:{package}:{quoted_version}"


def component_asset_name(artifact_prefix: str, arch: str, deb_name: str) -> str:
    return f"{artifact_prefix}-component-{arch}-{deb_name}"


def build_component_index(
    *,
    debs: list[Path],
    components_dir: Path,
    artifact_prefix: str,
    profile: str,
    source: str,
    arch: str,
) -> dict[str, Any]:
    components_dir.mkdir(parents=True, exist_ok=True)
    packages: list[dict[str, Any]] = []

    for deb in sorted(debs, key=lambda item: item.name):
        fields = deb_control_fields(deb)
        package = fields.get("Package")
        version = fields.get("Version")
        deb_architecture = fields.get("Architecture", arch)
        architecture = arch if deb_architecture == "all" else deb_architecture
        if not package or not version:
            raise ValueError(f"{deb} is missing Package or Version control field")

        asset_name = component_asset_name(artifact_prefix, arch, deb.name)
        component_path = components_dir / asset_name
        shutil.copy2(deb, component_path)
        depends = fields.get("Depends", "")
        pre_depends = fields.get("Pre-Depends", "")

        packages.append(
            {
                "id": component_id(package, version, architecture),
                "package": package,
                "version": version,
                "architecture": architecture,
                "debArchitecture": deb_architecture,
                "sourceProfile": profile,
                "source": source,
                "fileName": deb.name,
                "assetName": asset_name,
                "size": component_path.stat().st_size,
                "sha256": sha256_file(component_path),
                "depends": depends,
                "preDepends": pre_depends,
                "dependencyNames": dependency_names(",".join([pre_depends, depends])),
                "commands": deb_command_names(deb),
            }
        )

    return {
        "schemaVersion": 1,
        "profile": profile,
        "source": source,
        "architecture": arch,
        "artifactPrefix": artifact_prefix,
        "packages": packages,
    }


def write_component_index(index: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def find_debs(path: Path) -> list[Path]:
    if path.is_file() and path.name.endswith(".deb"):
        return [path]
    return sorted(path.rglob("*.deb"))


def safe_extract_tar(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive_path, mode="r:*") as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if os.path.commonpath([root, target]) != str(root):
                raise ValueError(f"unsafe tar member path: {member.name}")
        archive.extractall(destination)
