#!/usr/bin/env python3
"""Verify Termux .deb data paths target the PyStudio app package."""

from __future__ import annotations

import argparse
import gzip
import io
import lzma
import pathlib
import sys
import tarfile

MAX_ERRORS_PER_DEB = 5


def read_ar_members(path: pathlib.Path) -> list[tuple[str, bytes]]:
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


def decompress_tar(name: str, payload: bytes) -> bytes:
    if name.endswith(".xz"):
        return lzma.decompress(payload)
    if name.endswith(".gz"):
        return gzip.decompress(payload)
    if name.endswith(".tar"):
        return payload
    raise ValueError(f"unsupported data archive compression: {name}")


def data_archive_members(path: pathlib.Path) -> list[str]:
    for name, payload in read_ar_members(path):
        if not name.startswith("data.tar"):
            continue
        data = decompress_tar(name, payload)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
            return [member.name for member in archive.getmembers()]
    raise ValueError(f"{path} has no data.tar member")


def normalize_member_name(name: str) -> str:
    while name.startswith("./"):
        name = name[2:]
    return name.lstrip("/")


def validate_deb(path: pathlib.Path, package_name: str) -> list[str]:
    expected_data_root = f"data/data/{package_name}"
    errors: list[str] = []
    omitted = 0

    for raw_name in data_archive_members(path):
        name = normalize_member_name(raw_name)
        if not name or name in {"data", "data/data"}:
            continue
        if name.startswith("data/data/") and not (
            name == expected_data_root or name.startswith(f"{expected_data_root}/")
        ):
            if len(errors) < MAX_ERRORS_PER_DEB:
                errors.append(f"{path.name}: unexpected data path {raw_name}")
            else:
                omitted += 1

    if omitted:
        errors.append(f"{path.name}: ... {omitted} more unexpected data paths")

    return errors


def iter_debs(paths: list[pathlib.Path]) -> list[pathlib.Path]:
    debs: list[pathlib.Path] = []
    for path in paths:
        if path.is_dir():
            debs.extend(sorted(path.rglob("*.deb")))
        elif path.suffix == ".deb":
            debs.append(path)
    return debs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=pathlib.Path)
    parser.add_argument("--package-name", default="com.vchangxiao.pystudio")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    debs = iter_debs(args.paths)
    if not debs:
        print("No .deb files found to check.", file=sys.stderr)
        return 1

    errors: list[str] = []
    for deb in debs:
        errors.extend(validate_deb(deb, args.package_name))

    if errors:
        print("Invalid Termux package prefix detected:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    print(f"Checked {len(debs)} .deb files for /data/data/{args.package_name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
