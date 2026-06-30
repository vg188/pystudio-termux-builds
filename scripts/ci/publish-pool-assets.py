#!/usr/bin/env python3
"""Publish split .deb package pool assets to GitHub Releases."""

from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
from types import ModuleType


def load_release_tools() -> ModuleType:
    path = Path(__file__).with_name("backfill-release-components.py")
    spec = importlib.util.spec_from_file_location("pystudio_release_tools", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load release tools from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--source-tag", required=True)
    parser.add_argument("--pool-dir", required=True, type=Path)
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--force-upload", action="store_true")
    args = parser.parse_args()

    if not args.repo:
        raise SystemExit("--repo or GITHUB_REPOSITORY is required")
    if not args.token:
        raise SystemExit("--token or GITHUB_TOKEN is required")
    if not args.pool_dir.is_dir():
        raise SystemExit(f"package pool directory does not exist: {args.pool_dir}")

    tools = load_release_tools()
    release_cache: dict[tuple[str, str], dict] = {}
    uploaded = 0
    skipped_dirs = 0

    for pool_dir in sorted(item for item in args.pool_dir.iterdir() if item.is_dir()):
        pool_arch = pool_dir.name
        debs = sorted(pool_dir.glob("*.deb"))
        if not debs:
            skipped_dirs += 1
            continue
        tag = tools.pool_release_tag(args.source_tag, pool_arch)
        key = (args.repo, tag)
        if key not in release_cache:
            release_cache[key] = tools.ensure_release_by_tag(
                args.token,
                args.repo,
                tag,
                f"PyStudio package pool {pool_arch} {args.source_tag}",
            )
        release = release_cache[key]
        asset_map = tools.cached_release_asset_map(args.token, args.repo, release)
        for deb in debs:
            tools.upload_asset(
                args.token,
                args.repo,
                int(release["id"]),
                asset_map,
                deb,
                deb.name,
                args.force_upload,
            )
            uploaded += 1

    print(f"Processed {uploaded} package pool assets from {args.pool_dir}.")
    if skipped_dirs:
        print(f"Skipped {skipped_dirs} empty pool directories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
