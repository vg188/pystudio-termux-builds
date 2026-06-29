#!/usr/bin/env python3
"""Create flat GitHub Release assets for a split apt repository."""

from __future__ import annotations

import argparse
import lzma
from pathlib import Path
import shutil


def release_asset_name(file_name: str) -> str:
    return Path(file_name).name.replace(":", ".")


def rewrite_packages_index(packages_path: Path, output_path: Path) -> None:
    lines: list[str] = []
    for line in packages_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("Filename: "):
            line = "Filename: " + release_asset_name(line.split(": ", 1)[1])
        lines.append(line)
    data = ("\n".join(lines) + "\n").encode("utf-8")
    output_path.write_bytes(data)
    output_path.with_suffix(output_path.suffix + ".xz").write_bytes(lzma.compress(data, preset=9))


def copy_unique(source: Path, target: Path) -> None:
    if target.exists() and target.read_bytes() != source.read_bytes():
        raise RuntimeError(f"conflicting release asset name: {target.name}")
    if not target.exists():
        shutil.copy2(source, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-dir", required=True, type=Path)
    parser.add_argument("--flat-dir", required=True, type=Path)
    parser.add_argument("--repo-slug", required=True)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--distribution", default="pystudio")
    parser.add_argument("--component", default="main")
    args = parser.parse_args()

    args.flat_dir.mkdir(parents=True, exist_ok=True)
    for deb in sorted((args.repo_dir / "pool" / args.component).rglob("*.deb")):
        copy_unique(deb, args.flat_dir / release_asset_name(deb.name))

    packages = args.repo_dir / "dists" / args.distribution / args.component / f"binary-{args.arch}" / "Packages"
    rewrite_packages_index(packages, args.flat_dir / f"{args.repo_slug}-Packages")
    print(f"Wrote flat release assets to {args.flat_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
