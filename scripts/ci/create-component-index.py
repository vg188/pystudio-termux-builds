#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from component_index import build_component_index, find_debs, write_component_index


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a PyStudio component package index.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--components-dir", required=True, type=Path)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--artifact-prefix", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--arch", required=True)
    args = parser.parse_args()

    debs = find_debs(args.output_dir)
    if not debs:
        raise SystemExit(f"no .deb files found in {args.output_dir}")

    index = build_component_index(
        debs=debs,
        components_dir=args.components_dir,
        artifact_prefix=args.artifact_prefix,
        profile=args.profile,
        source=args.source,
        arch=args.arch,
    )
    write_component_index(index, args.index)
    print(f"Wrote {args.index} with {len(index['packages'])} packages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
