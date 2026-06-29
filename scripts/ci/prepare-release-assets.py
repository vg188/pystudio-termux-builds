#!/usr/bin/env python3
"""Deduplicate files before uploading GitHub Release assets."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil

from component_index import sha256_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in sorted(args.artifacts_dir.rglob("*")):
        if not path.is_file():
            continue
        name = path.name
        if not (
            name.endswith(".deb")
            or name.endswith(".json")
            or name.endswith("-Packages")
            or name.endswith("-Packages.gz")
            or name.endswith("-Packages.xz")
        ):
            continue
        target = args.output_dir / name
        if target.exists():
            if sha256_file(target) != sha256_file(path):
                raise RuntimeError(f"conflicting release asset name: {name}")
            continue
        shutil.copy2(path, target)
        copied += 1
    print(f"Prepared {copied} release assets in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
