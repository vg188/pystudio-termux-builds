#!/usr/bin/env python3
"""Prepare flat repository indexes and split package pool assets for releases."""

from __future__ import annotations

import argparse
import json
import lzma
from pathlib import Path
import re
import shutil
from typing import Any

from component_index import deb_control_fields, sha256_file


ARCHES = ("aarch64", "arm", "i686", "x86_64")
ARCH_RE = re.compile(r"-apt-repo-v1-(aarch64|arm|i686|x86_64)-")


def release_asset_name(file_name: str) -> str:
    return Path(file_name).name.replace(":", ".")


def target_arch_from_path(path: Path) -> str:
    for part in reversed(path.parts):
        match = ARCH_RE.search(part)
        if match:
            return match.group(1)
    for part in reversed(path.parts):
        for arch in ARCHES:
            if re.search(rf"(?:^|-){arch}(?:-|\b)", part):
                return arch
    raise RuntimeError(f"could not infer target architecture from {path}")


def deb_record(path: Path) -> dict[str, Any]:
    fields = deb_control_fields(path)
    package = fields.get("Package", "")
    version = fields.get("Version", "")
    deb_arch = fields.get("Architecture", target_arch_from_path(path))
    if not package or not version:
        raise RuntimeError(f"{path} is missing Package or Version control field")
    return {
        "path": path,
        "name": release_asset_name(path.name),
        "package": package,
        "version": version,
        "debArchitecture": deb_arch,
        "targetArchitecture": target_arch_from_path(path),
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
    }


def select_canonical_debs(paths: list[Path]) -> dict[str, dict[str, Any]]:
    records: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(paths):
        record = deb_record(path)
        records.setdefault(record["name"], []).append(record)

    selected: dict[str, dict[str, Any]] = {}
    for name, variants in sorted(records.items()):
        control_keys = {
            (item["package"], item["version"], item["debArchitecture"])
            for item in variants
        }
        if len(control_keys) != 1:
            raise RuntimeError(f"conflicting release asset name with different package metadata: {name}")
        variants.sort(key=lambda item: (ARCHES.index(item["targetArchitecture"]), str(item["path"])))
        chosen = variants[0]
        unique_hashes = sorted({item["sha256"] for item in variants})
        if len(unique_hashes) > 1:
            print(
                "Canonicalizing duplicate package asset "
                f"{name}: selected {chosen['targetArchitecture']} copy; "
                f"rewriting {len(variants)} index reference(s).",
                flush=True,
            )
        selected[name] = chosen
    return selected


def rewrite_packages_text(text: str, canonical_debs: dict[str, dict[str, Any]]) -> str:
    stanzas = [part for part in text.split("\n\n") if part.strip()]
    rewritten: list[str] = []
    for stanza in stanzas:
        lines = stanza.splitlines()
        filename = ""
        for line in lines:
            if line.startswith("Filename: "):
                filename = release_asset_name(line.split(": ", 1)[1])
                break
        record = canonical_debs.get(filename)
        if not record:
            rewritten.append("\n".join(lines))
            continue

        saw_size = False
        saw_sha256 = False
        out: list[str] = []
        for line in lines:
            if line.startswith("Size: "):
                out.append(f"Size: {record['size']}")
                saw_size = True
            elif line.startswith("SHA256: "):
                out.append(f"SHA256: {record['sha256']}")
                saw_sha256 = True
            else:
                out.append(line)
        if not saw_size:
            out.append(f"Size: {record['size']}")
        if not saw_sha256:
            out.append(f"SHA256: {record['sha256']}")
        rewritten.append("\n".join(out))
    return "\n\n".join(rewritten) + "\n"


def write_rewritten_packages(source: Path, target: Path, canonical_debs: dict[str, dict[str, Any]]) -> None:
    if source.name.endswith(".xz"):
        text = lzma.decompress(source.read_bytes()).decode("utf-8", errors="replace")
        target.write_bytes(lzma.compress(rewrite_packages_text(text, canonical_debs).encode("utf-8"), preset=9))
        return
    text = source.read_text(encoding="utf-8", errors="replace")
    target.write_text(rewrite_packages_text(text, canonical_debs), encoding="utf-8")


def rewrite_metadata(source: Path, target: Path, canonical_debs: dict[str, dict[str, Any]]) -> None:
    data = json.loads(source.read_text(encoding="utf-8"))
    packages = data.get("packages", [])
    if isinstance(packages, list):
        for package in packages:
            if not isinstance(package, dict):
                continue
            file_name = release_asset_name(str(package.get("fileName", "")))
            record = canonical_debs.get(file_name)
            if not record:
                continue
            package["size"] = record["size"]
            package["sha256"] = record["sha256"]
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def copy_unique(source: Path, target: Path) -> bool:
    if target.exists():
        if sha256_file(target) != sha256_file(source):
            raise RuntimeError(f"conflicting release asset name: {target.name}")
        return False
    shutil.copy2(source, target)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--pool-output-dir", required=True, type=Path)
    args = parser.parse_args()

    shutil.rmtree(args.output_dir, ignore_errors=True)
    shutil.rmtree(args.pool_output_dir, ignore_errors=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.pool_output_dir.mkdir(parents=True, exist_ok=True)

    deb_paths = sorted(path for path in args.artifacts_dir.rglob("*.deb") if path.is_file())
    canonical_debs = select_canonical_debs(deb_paths)

    copied_release = 0
    copied_pool = 0
    for record in canonical_debs.values():
        pool_arch = "all" if record["debArchitecture"] == "all" else record["targetArchitecture"]
        target = args.pool_output_dir / pool_arch / record["name"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if copy_unique(record["path"], target):
            copied_pool += 1

    for path in sorted(args.artifacts_dir.rglob("*")):
        if not path.is_file():
            continue
        name = path.name
        if name.endswith(".deb") or name.endswith("-Packages.gz"):
            continue
        target = args.output_dir / name
        if name.endswith("-Packages") or name.endswith("-Packages.xz"):
            write_rewritten_packages(path, target, canonical_debs)
            copied_release += 1
            continue
        if name.endswith(".json"):
            rewrite_metadata(path, target, canonical_debs)
            copied_release += 1
            continue
        if copy_unique(path, target):
            copied_release += 1

    print(f"Prepared {copied_release} index release assets in {args.output_dir}")
    print(f"Prepared {copied_pool} package pool assets in {args.pool_output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
