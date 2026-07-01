#!/usr/bin/env python3
"""Audit PyStudio proot .deb files against the app-domain runtime contract."""

from __future__ import annotations

import argparse
import gzip
import io
import lzma
import pathlib
import re
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field


FORBIDDEN_PREFIX_PATTERNS = [
    re.compile(rb"/data/data/com\.termux/files/usr"),
    re.compile(rb"/data/data/com\.[A-Za-z0-9_.-]+/files/usr"),
]


@dataclass
class AuditResult:
    deb: pathlib.Path
    package: str = ""
    architecture: str = ""
    version: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)


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
    raise ValueError(f"unsupported tar archive compression: {name}")


def deb_tar(path: pathlib.Path, prefix: str) -> tarfile.TarFile:
    for name, payload in read_ar_members(path):
        if name.startswith(prefix):
            data = decompress_tar(name, payload)
            return tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    raise ValueError(f"{path} has no {prefix} member")


def control_fields(path: pathlib.Path) -> dict[str, str]:
    with deb_tar(path, "control.tar") as archive:
        control = archive.extractfile("./control") or archive.extractfile("control")
        if control is None:
            raise ValueError(f"{path} has no control file")
        text = control.read().decode("utf-8", errors="replace")

    fields: dict[str, str] = {}
    current = ""
    for line in text.splitlines():
        if line.startswith((" ", "\t")) and current:
            fields[current] += "\n" + line
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current = key
        fields[key] = value.strip()
    return fields


def data_members(path: pathlib.Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    with deb_tar(path, "data.tar") as archive:
        for member in archive.getmembers():
            name = member.name[2:] if member.name.startswith("./") else member.name
            if member.isfile():
                extracted = archive.extractfile(member)
                if extracted is not None:
                    result[name] = extracted.read()
            else:
                result.setdefault(name.rstrip("/"), b"")
    return result


def find_member(members: dict[str, bytes], suffix: str) -> tuple[str, bytes] | None:
    for name, payload in members.items():
        if name.endswith(suffix):
            return name, payload
    return None


def run_readelf_dynamic(binary: bytes) -> str:
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(binary)
        temp_path = pathlib.Path(handle.name)
    try:
        try:
            proc = subprocess.run(
                ["readelf", "-d", str(temp_path)],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except FileNotFoundError:
            return "readelf not found"
        return proc.stdout
    finally:
        temp_path.unlink(missing_ok=True)


def audit_proot(path: pathlib.Path) -> AuditResult:
    fields = control_fields(path)
    members = data_members(path)
    result = AuditResult(
        deb=path,
        package=fields.get("Package", ""),
        architecture=fields.get("Architecture", ""),
        version=fields.get("Version", ""),
    )

    if result.package != "proot":
        result.info.append("skipped non-proot package")
        return result

    depends = fields.get("Depends", "")
    for dependency in ("libandroid-shmem", "libtalloc"):
        if dependency not in depends:
            result.errors.append(f"missing runtime dependency: {dependency}")

    proot_entry = find_member(members, "/bin/proot")
    if proot_entry is None:
        result.errors.append("missing $PREFIX/bin/proot")
        return result

    proot_path, proot_binary = proot_entry
    result.info.append(f"found proot at {proot_path}")

    loader_entry = find_member(members, "/libexec/proot/loader")
    if loader_entry is None:
        result.errors.append("missing $PREFIX/libexec/proot/loader")
    else:
        result.info.append(f"found loader at {loader_entry[0]}")

    if result.architecture in {"aarch64", "x86_64"}:
        loader32_entry = find_member(members, "/libexec/proot/loader32")
        if loader32_entry is None:
            result.warnings.append("missing loader32 for mixed-ABI architecture")
        else:
            result.info.append(f"found loader32 at {loader32_entry[0]}")

    for name, payload in members.items():
        if not payload:
            continue
        for pattern in FORBIDDEN_PREFIX_PATTERNS:
            match = pattern.search(payload)
            if match:
                result.warnings.append(f"{name} embeds hardcoded prefix {match.group(0).decode('utf-8', errors='replace')}")
                break

    for pattern in FORBIDDEN_PREFIX_PATTERNS:
        match = pattern.search(proot_binary)
        if match:
            result.warnings.append(
                f"proot binary embeds hardcoded prefix {match.group(0).decode('utf-8', errors='replace')}"
            )
            break

    dynamic = run_readelf_dynamic(proot_binary)
    if dynamic == "readelf not found":
        result.warnings.append("readelf was not available; ELF dynamic section was not checked")
    elif "RUNPATH" in dynamic and "/data/data/" in dynamic:
        result.warnings.append("proot ELF RUNPATH contains an Android app data prefix")
    if dynamic != "readelf not found":
        if "There is no dynamic section" in dynamic:
            result.info.append("proot binary appears static")
        elif "NEEDED" in dynamic:
            result.info.append("proot binary is dynamically linked")

    if b"built-in accelerators: process_vm = %s, seccomp_filter = %s" not in proot_binary:
        result.warnings.append("proot --version may not report accelerator status")
    if b"PROOT_NO_SECCOMP" not in proot_binary:
        result.warnings.append("PROOT_NO_SECCOMP runtime toggle was not found in binary strings")
    if b"clone3" not in proot_binary:
        result.warnings.append("clone3 handling string was not found in binary strings")

    return result


def iter_debs(paths: list[pathlib.Path]) -> list[pathlib.Path]:
    debs: list[pathlib.Path] = []
    for path in paths:
        if path.is_dir():
            debs.extend(sorted(path.rglob("proot_*.deb")))
        elif path.name.startswith("proot_") and path.suffix == ".deb":
            debs.append(path)
    return debs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=pathlib.Path)
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Report contract gaps without failing the build.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    debs = iter_debs(args.paths)
    if not debs:
        print("No proot .deb files found to audit.", file=sys.stderr)
        return 1

    hard_fail = False
    for deb in debs:
        result = audit_proot(deb)
        heading = f"{result.deb.name} [{result.architecture} {result.version}]"
        print(f"==> {heading}")
        for item in result.info:
            print(f"  info: {item}")
        for item in result.warnings:
            print(f"  warning: {item}")
        for item in result.errors:
            print(f"  error: {item}")
        if result.errors or (result.warnings and not args.warn_only):
            hard_fail = True

    if hard_fail:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
