#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import lzma
import os
from pathlib import Path
import re
import shutil
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from component_index import find_debs, safe_extract_tar
from package_repo import build_package_repo


GITHUB_API = "https://api.github.com"
GITHUB_UPLOADS = "https://uploads.github.com"
ARCHES = ("aarch64", "arm", "i686", "x86_64")


def headers(token: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    result = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "pystudio-package-repo-backfill",
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


def request_empty(token: str, method: str, url: str) -> None:
    request = urllib.request.Request(url, method=method, headers=headers(token))
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                response.read()
            return
        except urllib.error.URLError:
            if attempt == 5:
                raise
            time.sleep(attempt * 3)


def download(token: str, url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers=headers(token, {"Accept": "application/octet-stream"}))
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(1, 6):
        try:
            if partial.exists():
                partial.unlink()
            with urllib.request.urlopen(request, timeout=300) as response:
                content_length = response.headers.get("Content-Length")
                expected = int(content_length) if content_length and content_length.isdigit() else None
                copied = 0
                with partial.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        copied += len(chunk)
                if expected is not None and copied != expected:
                    raise RuntimeError(
                        f"incomplete download for {destination.name}: got {copied} bytes, expected {expected}"
                    )
            partial.replace(destination)
            return
        except (urllib.error.URLError, EOFError, RuntimeError) as exc:
            if attempt == 5:
                raise
            print(f"Warning: download attempt {attempt} failed for {destination.name}: {exc}")
            time.sleep(attempt * 5)


def delete_asset(token: str, repo: str, asset: dict[str, Any]) -> None:
    owner_repo = urllib.parse.quote(repo, safe="/")
    asset_id = int(asset["id"])
    request_empty(token, "DELETE", f"{GITHUB_API}/repos/{owner_repo}/releases/assets/{asset_id}")
    print(f"Deleted loose component asset: {asset['name']}")


def upload_asset(
    token: str,
    repo: str,
    release_id: int,
    asset_map: dict[str, dict[str, Any]],
    path: Path,
    name: str,
    force: bool,
) -> None:
    existing = asset_map.get(name)
    if existing and not force:
        print(f"Asset exists, skipping: {name}")
        return
    if existing and force:
        delete_asset(token, repo, existing)
        asset_map.pop(name, None)

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
            with urllib.request.urlopen(request, timeout=600) as response:
                uploaded = json.loads(response.read().decode("utf-8"))
            asset_map[name] = uploaded
            print(f"Uploaded package repository asset: {name}")
            return
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code == 422 and "already_exists" in detail and not force:
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
        batch = request_json(token, "GET", f"{GITHUB_API}/repos/{repo}/releases?per_page=100&page={page}")
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
    return re.sub(r"[^A-Za-z0-9_.+-]+", "-", value).strip(".-") or "asset"


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


def version_from_release_tag(tag: str) -> str:
    match = re.search(r"(r\d+)$", tag)
    if match:
        return match.group(1)
    return safe_part(tag)


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


def copy_unique(source: Path, target: Path) -> None:
    if target.exists() and target.read_bytes() != source.read_bytes():
        raise RuntimeError(f"conflicting flat release asset name: {target.name}")
    if not target.exists():
        shutil.copy2(source, target)


def write_flat_packages_index(packages_path: Path, output_path: Path) -> None:
    lines: list[str] = []
    for line in packages_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("Filename: "):
            line = "Filename: " + Path(line.split(": ", 1)[1]).name
        lines.append(line)
    data = ("\n".join(lines) + "\n").encode("utf-8")
    output_path.write_bytes(data)
    with gzip.open(output_path.with_suffix(output_path.suffix + ".gz"), "wb", compresslevel=9) as handle:
        handle.write(data)
    output_path.with_suffix(output_path.suffix + ".xz").write_bytes(lzma.compress(data, preset=9))


def create_flat_release_assets(repo_dir: Path, flat_dir: Path, repo_slug: str, arch: str) -> list[Path]:
    shutil.rmtree(flat_dir, ignore_errors=True)
    flat_dir.mkdir(parents=True, exist_ok=True)

    for deb in sorted((repo_dir / "pool" / "main").rglob("*.deb")):
        copy_unique(deb, flat_dir / deb.name)

    packages = repo_dir / "dists" / "pystudio" / "main" / f"binary-{arch}" / "Packages"
    write_flat_packages_index(packages, flat_dir / f"{repo_slug}-Packages")
    return sorted(path for path in flat_dir.iterdir() if path.is_file())


def upload_flat_release_assets(
    token: str,
    repo: str,
    release_id: int,
    asset_map: dict[str, dict[str, Any]],
    flat_dir: Path,
    force: bool,
) -> None:
    for path in sorted(flat_dir.iterdir()):
        if path.is_file():
            upload_asset(token, repo, release_id, asset_map, path, path.name, force)


def cleanup_loose_component_assets(
    token: str,
    repo: str,
    asset_map: dict[str, dict[str, Any]],
    artifact_prefix: str,
    arch: str,
) -> None:
    names = [
        name
        for name in asset_map
        if name == f"{artifact_prefix}-component-index-{arch}.json"
        or (name.startswith(f"{artifact_prefix}-component-{arch}-") and name.endswith(".deb"))
    ]
    for name in sorted(names):
        delete_asset(token, repo, asset_map[name])
        asset_map.pop(name, None)


def cleanup_large_assets(
    token: str,
    repo: str,
    asset_map: dict[str, dict[str, Any]],
    names: list[str],
) -> None:
    for name in names:
        asset = asset_map.get(name)
        if asset:
            delete_asset(token, repo, asset)
            asset_map.pop(name, None)


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

    asset_map = {asset["name"]: asset for asset in release.get("assets", [])}
    artifact_prefix, arch = info
    tag = str(release["tag_name"])
    version = version_from_release_tag(tag)
    repo_slug = f"{artifact_prefix}-apt-repo-v1-{arch}-{version}"
    archive_name = f"{repo_slug}.tar.gz"
    metadata_name = f"{repo_slug}.json"
    flat_index_name = f"{repo_slug}-Packages.xz"
    large_asset_names = [
        asset_name,
        archive_name,
        f"{archive_name}.sha256",
        f"{artifact_prefix}-repo-{arch}.tar.gz",
    ]

    if flat_index_name in asset_map and not args.force_upload:
        print(f"Flat package index exists, skipping bundle: {flat_index_name}")
        if args.cleanup_loose_components:
            cleanup_loose_component_assets(token, args.repo, asset_map, artifact_prefix, arch)
        if args.cleanup_large_assets:
            cleanup_large_assets(token, args.repo, asset_map, large_asset_names)
        return False

    source_asset_names = []
    if archive_name in asset_map:
        source_asset_names.append(archive_name)
    source_asset_names.append(asset_name)
    repo_fallback_asset = f"{artifact_prefix}-repo-{arch}.tar.gz"
    if repo_fallback_asset in asset_map:
        source_asset_names.append(repo_fallback_asset)

    repo_part = safe_part(args.repo)
    work_dir = args.work_dir / repo_part / tag / artifact_prefix / arch
    extract_dir = work_dir / "extract"
    repo_dir = work_dir / repo_slug
    metadata_path = work_dir / metadata_name
    flat_dir = work_dir / f"{repo_slug}-flat"
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    last_extract_error: Exception | None = None
    for source_asset_name in source_asset_names:
        asset = asset_map.get(source_asset_name)
        if not asset:
            print(f"Missing release asset, skipping source: {tag}/{source_asset_name}")
            continue
        archive_source_path = work_dir / source_asset_name
        for attempt in range(1, 4):
            print(f"Downloading {args.repo}/{tag}/{source_asset_name}")
            download(token, str(asset["browser_download_url"]), archive_source_path)
            shutil.rmtree(extract_dir, ignore_errors=True)
            try:
                safe_extract_tar(archive_source_path, extract_dir)
                last_extract_error = None
                break
            except (EOFError, tarfile.TarError, OSError) as exc:
                last_extract_error = exc
                if attempt == 3:
                    break
                print(f"Warning: extract attempt {attempt} failed for {source_asset_name}: {exc}")
                archive_source_path.unlink(missing_ok=True)
                time.sleep(attempt * 5)
        if last_extract_error is None and extract_dir.exists():
            if source_asset_name != asset_name:
                print(f"Using fallback source asset for {asset_name}: {source_asset_name}")
            break

    if last_extract_error is not None:
        raise last_extract_error

    debs = find_debs(extract_dir)
    if not debs:
        print(f"No debs found in {asset_name}, skipping.")
        return False

    metadata = build_package_repo(
        debs=debs,
        repo_dir=repo_dir,
        artifact_prefix=artifact_prefix,
        profile=profile or profile_from_artifact_prefix(artifact_prefix),
        source=source or source_from_artifact_prefix(artifact_prefix),
        arch=arch,
        version=version,
    )
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    create_flat_release_assets(repo_dir, flat_dir, repo_slug, arch)

    upload_asset(token, args.repo, int(release["id"]), asset_map, metadata_path, metadata_name, args.force_upload)
    upload_flat_release_assets(token, args.repo, int(release["id"]), asset_map, flat_dir, args.force_upload)
    if args.cleanup_loose_components:
        cleanup_loose_component_assets(token, args.repo, asset_map, artifact_prefix, arch)
    if args.cleanup_large_assets:
        cleanup_large_assets(token, args.repo, asset_map, large_asset_names)
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
                artifact_prefix = str(asset_name).rsplit(f"-debs-{arch}.tar.gz", 1)[0]
                if backfill_deb_bundle_asset(
                    args,
                    token,
                    release,
                    str(asset_name),
                    profile=str(entry.get("profile") or entry.get("id") or ""),
                    source=source_from_artifact_prefix(artifact_prefix),
                ):
                    uploaded += 1
        finally:
            args.repo = original_repo

    print(f"Migration plan backfill complete: processed {uploaded} package repositories.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill flat apt-style package assets into releases.")
    parser.add_argument("--repo", default="vg188/pystudio-termux-builds")
    parser.add_argument("--tag-prefix", default="")
    parser.add_argument("--tags", default="", help="Comma-separated release tags to process. Defaults to all matching.")
    parser.add_argument("--max-releases", type=int, default=0)
    parser.add_argument("--work-dir", type=Path, default=Path("work/package-repo-backfill"))
    parser.add_argument("--force-upload", action="store_true")
    parser.add_argument("--cleanup-loose-components", action="store_true", default=True)
    parser.add_argument("--no-cleanup-loose-components", action="store_false", dest="cleanup_loose_components")
    parser.add_argument("--cleanup-large-assets", action="store_true", default=True)
    parser.add_argument("--no-cleanup-large-assets", action="store_false", dest="cleanup_large_assets")
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
