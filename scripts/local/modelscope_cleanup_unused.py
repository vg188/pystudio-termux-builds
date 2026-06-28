#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import os
import sys

from modelscope_release_relay import modelscope_token_from_env


DEFAULT_REPO_ID = "yourba/pystudio-termux-builds"
DEFAULT_DELETE_PATTERNS = ["assets/**", "runtime-packages-modelscope.json"]
DEFAULT_ENDPOINT = "https://modelscope.cn"


def run(args: argparse.Namespace) -> None:
    try:
        from modelscope.hub.api import HubApi
    except ImportError as exc:
        raise RuntimeError("modelscope package is required. Install it with: python -m pip install modelscope") from exc

    token = args.modelscope_token or modelscope_token_from_env()
    if not token and not args.dry_run:
        token = getpass.getpass("ModelScope token: ")

    patterns = args.delete_pattern or DEFAULT_DELETE_PATTERNS
    print(f"ModelScope dataset: {args.repo_id}")
    print("Delete patterns:")
    for pattern in patterns:
        print(f"  - {pattern}")

    if args.dry_run:
        print("Dry run only; no files were deleted.")
        return

    api = HubApi()
    result = api.delete_files(
        repo_id=args.repo_id,
        repo_type="dataset",
        delete_patterns=patterns,
        revision=args.revision,
        endpoint=args.endpoint,
        token=token,
    )
    failed = result.get("failed_files", [])
    deleted = result.get("deleted_files", [])
    print(f"Deleted files: {len(deleted)}")
    if failed:
        print(f"Failed files: {len(failed)}")
        for path in failed[:20]:
            print(f"  - {path}")
        if len(failed) > 20:
            print(f"  ... {len(failed) - 20} more")
        raise RuntimeError("ModelScope cleanup finished with failed deletions")
    print("ModelScope cleanup complete.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean unused legacy files from the PyStudio ModelScope dataset.")
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--revision", default="master")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--delete-pattern", action="append", default=[])
    parser.add_argument("--modelscope-token", default=os.environ.get("MODELSCOPE_TOKEN", ""))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    try:
        run(parse_args())
        return 0
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
