#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from package_repo import build_repo_from_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a PyStudio apt-style package repository.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--repo-dir", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--artifact-prefix", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--distribution", default="pystudio")
    parser.add_argument("--component", default="main")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--build-metadata", type=Path)
    args = parser.parse_args()

    metadata = build_repo_from_path(
        input_path=args.output_dir,
        repo_dir=args.repo_dir,
        profile=args.profile,
        source=args.source,
        arch=args.arch,
        artifact_prefix=args.artifact_prefix,
        version=args.version,
        distribution=args.distribution,
        component=args.component,
        source_root=args.source_root,
        build_metadata_path=args.build_metadata,
    )
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"Wrote {args.repo_dir} with {metadata['packageCount']} packages "
        f"for {args.profile}/{args.source}/{args.arch}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
