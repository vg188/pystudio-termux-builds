#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from component_index import build_component_index, find_debs, safe_extract_tar, write_component_index


GITHUB_API = "https://api.github.com"
GITHUB_UPLOADS = "https://uploads.github.com"
ARCHES = ("aarch64", "arm", "i686", "x86_64")


def headers(token: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    result = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "pystudio-component-backfill",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if extra:
        result.update(extra)
    return result


def request_json(token: str, method: str, url: str, payload: dict[str, Any] | None = None) -> Any:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers=headers(token))
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.URLError:
            if attempt == 5:
                raise
            time.sleep(attempt * 3)


def download(token: str, url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers=headers(token, {"Accept": "application/octet-stream"}))
    destination.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                with destination.open("wb") as output:
                    shutil.copyfileobj(response, output)
            return
        except urllib.error.URLError:
            if attempt == 5:
                raise
            time.sleep(attempt * 5)


def upload_asset(
    token: str,
    repo: str,
    release_id: int,
    existing_assets: set[str],
    path: Path,
    name: str,
    force: bool,
) -> None:
    if name in existing_assets and not force:
        print(f"Asset exists, skipping: {name}")
        return

    owner_repo = urllib.parse.quote(repo, safe="/")
    query = urllib.parse.urlencode({"name": name})
    url = f"{GITHUB_UPLOADS}/repos/{owner_repo}/releases/{release_id}/assets?{query}"
    request = urllib.request.Request(
        url,
        data=path.read_bytes(),
        method="POST",
        headers=headers(
            token,
            {
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/octet-stream",
            },
        ),
    )
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                response.read()
            existing_assets.add(name)
            print(f"Uploaded component asset: {name}")
            return
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code == 422 and "already_exists" in detail and not force:
                existing_assets.add(name)
                print(f"Asset exists after upload race, skipping: {name}")
                return
            if attempt == 5:
                raise RuntimeError(f"upload failed for {name}: HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError:
            if attempt == 5:
                raise
        time.sleep(attempt * 5)


def release_pages(token: str, repo: str) -> list[dict[str, Any]]:
    releases: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = request_json(
            token,
            "GET",
            f"{GITHUB_API}/repos/{repo}/releases?per_page=100&page={page}",
        )
        if not batch:
            return releases
        releases.extend(batch)
        page += 1


def release_by_tag(token: str, repo: str, tag: str) -> dict[str, Any]:
    owner_repo = urllib.parse.quote(repo, safe="/")
    quoted_tag = urllib.parse.quote(tag, safe="")
    return request_json(token, "GET", f"{GITHUB_API}/repos/{owner_repo}/releases/tags/{quoted_tag}")


def repo_slug_from_url(value: str) -> str:
    prefix = "https://github.com/"
    if value.startswith(prefix):
        value = value[len(prefix) :]
    return value.removesuffix(".git").strip("/")


def safe_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "asset"


def selected_releases(args: argparse.Namespace, token: str) -> list[dict[str, Any]]:
    releases = release_pages(token, args.repo)
    wanted_tags = {tag.strip() for tag in args.tags.split(",") if tag.strip()}
    selected = [
        release
        for release in releases
        if not release.get("draft")
        and not release.get("prerelease")
        and (not args.tag_prefix or release.get("tag_name", "").startswith(args.tag_prefix))
        and (not wanted_tags or release.get("tag_name") in wanted_tags)
    ]
    selected.sort(key=lambda release: release.get("created_at", ""), reverse=True)
    if args.max_releases:
        selected = selected[: args.max_releases]
    return selected


def deb_bundle_info(asset_name: str) -> tuple[str, str] | None:
    for arch in ARCHES:
        suffix = f"-debs-{arch}.tar.gz"
        if asset_name.endswith(suffix):
            return asset_name[: -len(suffix)], arch
    return None


def profile_from_artifact_prefix(artifact_prefix: str) -> str:
    profile = artifact_prefix
    for prefix in ("pystudio-python-extensions-", "pystudio-"):
        if profile.startswith(prefix):
            profile = profile[len(prefix) :]
            break
    for suffix in ("-toolchain-primary", "-toolchain-secondary", "-toolchain"):
        if profile.endswith(suffix):
            profile = profile[: -len(suffix)]
            break
    return profile or artifact_prefix


def source_from_artifact_prefix(artifact_prefix: str) -> str:
    if artifact_prefix.endswith("-toolchain-secondary"):
        return "secondary"
    if artifact_prefix.endswith("-toolchain-tur"):
        return "tur"
    return "primary"


def backfill_deb_bundle_asset(
    args: argparse.Namespace,
    token: str,
    release: dict[str, Any],
    asset_name: str,
    profile: str | None = None,
    source: str | None = None,
) -> bool:
    info = deb_bundle_info(asset_name)
    if not info:
        print(f"Skipping non-deb bundle asset: {asset_name}")
        return False

    assets = release.get("assets", [])
    asset_map = {asset["name"]: asset for asset in assets}
    asset = asset_map.get(asset_name)
    if not asset:
        print(f"Missing release asset, skipping: {release['tag_name']}/{asset_name}")
        return False

    artifact_prefix, arch = info
    existing_assets = set(asset_map)
    index_name = f"{artifact_prefix}-component-index-{arch}.json"
    if index_name in existing_assets and not args.force_upload:
        print(f"Component index exists, skipping bundle: {asset_name}")
        return False

    repo_part = safe_part(args.repo)
    tag = release["tag_name"]
    work_dir = args.work_dir / repo_part / tag / artifact_prefix / arch
    archive_path = work_dir / asset_name
    extract_dir = work_dir / "extract"
    components_dir = work_dir / "components"
    index_path = work_dir / index_name
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {args.repo}/{tag}/{asset_name}")
    download(token, str(asset["browser_download_url"]), archive_path)
    safe_extract_tar(archive_path, extract_dir)
    debs = find_debs(extract_dir)
    if not debs:
        print(f"No debs found in {asset_name}, skipping.")
        return False

    index = build_component_index(
        debs=debs,
        components_dir=components_dir,
        artifact_prefix=artifact_prefix,
        profile=profile or profile_from_artifact_prefix(artifact_prefix),
        source=source or source_from_artifact_prefix(artifact_prefix),
        arch=arch,
    )
    write_component_index(index, index_path)

    for component in index["packages"]:
        component_path = components_dir / component["assetName"]
        upload_asset(
            token,
            args.repo,
            int(release["id"]),
            existing_assets,
            component_path,
            component["assetName"],
            args.force_upload,
        )
    upload_asset(token, args.repo, int(release["id"]), existing_assets, index_path, index_name, args.force_upload)
    return True


def backfill_release(args: argparse.Namespace, token: str, release: dict[str, Any]) -> None:
    tag = release["tag_name"]
    assets = release.get("assets", [])
    print(f"Backfilling {tag} with {len(assets)} existing assets.")

    for asset in assets:
        info = deb_bundle_info(str(asset["name"]))
        if not info:
            continue
        backfill_deb_bundle_asset(args, token, release, str(asset["name"]))


def backfill_migration_plan(args: argparse.Namespace, token: str) -> None:
    plan = json.loads(args.migration_plan.read_text(encoding="utf-8"))
    if int(plan.get("schemaVersion", 0)) != 1:
        raise SystemExit(f"unsupported migration plan schema: {plan.get('schemaVersion')}")

    release_cache: dict[tuple[str, str], dict[str, Any]] = {}
    uploaded = 0
    for entry in plan.get("entries", []):
        release_info = entry.get("release", {})
        repo = repo_slug_from_url(str(release_info.get("repository", "")))
        tag = str(release_info.get("tag", ""))
        if not repo or not tag:
            print(f"Skipping migration entry without release: {entry.get('id')}")
            continue

        key = (repo, tag)
        if key not in release_cache:
            print(f"Loading release {repo}/{tag}")
            release_cache[key] = release_by_tag(token, repo, tag)
        release = release_cache[key]

        original_repo = args.repo
        args.repo = repo
        try:
            for arch in ARCHES:
                asset_name = entry.get("debianPackageAssets", {}).get(arch)
                if not asset_name:
                    continue
                if backfill_deb_bundle_asset(
                    args,
                    token,
                    release,
                    str(asset_name),
                    profile=str(entry.get("profile") or entry.get("id") or ""),
                    source=source_from_artifact_prefix(str(asset_name).rsplit(f"-debs-{arch}.tar.gz", 1)[0]),
                ):
                    uploaded += 1
        finally:
            args.repo = original_repo

    print(f"Migration plan backfill complete: processed {uploaded} deb bundles.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill component .deb assets into existing releases.")
    parser.add_argument("--repo", default="vg188/pystudio-termux-builds")
    parser.add_argument("--tag-prefix", default="")
    parser.add_argument("--tags", default="", help="Comma-separated release tags to process. Defaults to all matching.")
    parser.add_argument("--max-releases", type=int, default=0)
    parser.add_argument("--work-dir", type=Path, default=Path("work/component-backfill"))
    parser.add_argument("--force-upload", action="store_true")
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--migration-plan", type=Path, default=None)
    args = parser.parse_args()

    if not args.github_token:
        raise SystemExit("GITHUB_TOKEN is required")

    if args.migration_plan:
        backfill_migration_plan(args, args.github_token)
        return 0

    releases = selected_releases(args, args.github_token)
    if not releases:
        raise SystemExit("no matching releases found")

    for release in releases:
        backfill_release(args, args.github_token, release)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
