#!/usr/bin/env python3
"""Update PyStudio runtime package manifest from GitHub release assets."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ARCHITECTURES = ["aarch64", "arm", "i686", "x86_64"]
GITHUB_API = "https://api.github.com"
EXTENSIONS_REPO = "vg188/pystudio-python-extensions"
EXTENSIONS_METADATA_URL = (
    "https://raw.githubusercontent.com/vg188/pystudio-python-extensions/main/"
    "extension-profiles.json"
)
EXTENSIONS_RAW_BASE = "https://raw.githubusercontent.com/vg188/pystudio-python-extensions/main/"

CORE_PROFILES: dict[str, dict[str, Any]] = {
    "python": {
        "group": "runtime",
        "title": "Python / Pip",
        "description": "CPython runtime, pip, and their Termux dependencies.",
        "packages": ["python", "python-pip"],
        "primary_repo": "vg188/pystudio-python-toolchain",
        "secondary_repo": "vg188/pystudio-python-toolchain2",
        "tag_prefix": "pystudio-python-toolchain-r",
        "asset_prefix": "pystudio-python-toolchain",
        "installCommandName": "pystudio-install-python",
        "verifyCommands": ["python3 --version", "pip3 --version"],
    },
    "nodejs": {
        "group": "runtime",
        "title": "Node.js / npm",
        "description": "Node.js runtime and npm package manager.",
        "packages": ["nodejs", "npm"],
        "primary_repo": "vg188/pystudio-nodejs-toolchain",
        "secondary_repo": "vg188/pystudio-nodejs-toolchain2",
        "tag_prefix": "pystudio-nodejs-toolchain-r",
        "asset_prefix": "pystudio-nodejs-toolchain",
        "installCommandName": "pystudio-install-nodejs",
        "verifyCommands": ["node --version", "npm --version"],
    },
    "node-build-core": {
        "group": "npm-toolchain",
        "title": "Node.js Native Build Core",
        "description": "Build tools and native headers for npm packages that need source compilation.",
        "packages": [
            "nodejs",
            "npm",
            "python",
            "build-essential",
            "make",
            "cmake",
            "ninja",
            "pkg-config",
            "binutils",
            "ndk-sysroot",
            "libllvm",
            "python-cmake",
            "openssl",
            "zlib",
            "libffi",
            "libsqlite",
        ],
        "primary_repo": "vg188/pystudio-nodejs-toolchain",
        "secondary_repo": "vg188/pystudio-nodejs-toolchain2",
        "primary_release_repo": "vg188/pystudio-node-build-core-toolchain",
        "secondary_release_repo": "vg188/pystudio-node-build-core-toolchain",
        "tag_prefix": "pystudio-node-build-core-toolchain-r",
        "primary_asset_prefix": "pystudio-node-build-core-toolchain-primary",
        "secondary_asset_prefix": "pystudio-node-build-core-toolchain-secondary",
        "installCommandName": "pystudio-install-node-build-core",
        "verifyCommands": ["node --version", "npm --version", "cmake --version", "pkg-config --version"],
    },
    "tree-sitter": {
        "group": "editor-extension",
        "title": "Tree-sitter Parsers",
        "description": "Tree-sitter CLI, runtime library, and common parser grammars for editor features.",
        "packages": [
            "tree-sitter",
            "tree-sitter-parsers",
            "tree-sitter-bash",
            "tree-sitter-c",
            "tree-sitter-css",
            "tree-sitter-go",
            "tree-sitter-html",
            "tree-sitter-java",
            "tree-sitter-javascript",
            "tree-sitter-json",
            "tree-sitter-latex",
            "tree-sitter-lua",
            "tree-sitter-markdown",
            "tree-sitter-python",
            "tree-sitter-query",
            "tree-sitter-regex",
            "tree-sitter-rust",
            "tree-sitter-sql",
            "tree-sitter-toml",
            "tree-sitter-vim",
            "tree-sitter-vimdoc",
            "tree-sitter-xml",
            "tree-sitter-yaml",
        ],
        "primary_repo": "vg188/pystudio-nodejs-toolchain",
        "secondary_repo": "vg188/pystudio-nodejs-toolchain2",
        "primary_release_repo": "vg188/pystudio-tree-sitter-toolchain",
        "secondary_release_repo": "vg188/pystudio-tree-sitter-toolchain",
        "tag_prefix": "pystudio-tree-sitter-toolchain-r",
        "primary_asset_prefix": "pystudio-tree-sitter-toolchain-primary",
        "secondary_asset_prefix": "pystudio-tree-sitter-toolchain-secondary",
        "installCommandName": "pystudio-install-tree-sitter",
        "verifyCommands": ["tree-sitter --version"],
    },
    "cpp": {
        "group": "native-toolchain",
        "title": "C/C++ Toolchain",
        "description": "Compiler, sysroot, CMake, Ninja, Make, and pkg-config.",
        "packages": ["libllvm", "ndk-sysroot", "make", "cmake", "ninja", "pkg-config"],
        "primary_repo": "vg188/pystudio-cpp-toolchain",
        "secondary_repo": "vg188/pystudio-cpp-toolchain2",
        "tag_prefix": "pystudio-cpp-toolchain-r",
        "asset_prefix": "pystudio-cpp-toolchain",
        "installCommandName": "pystudio-install-cpp",
        "verifyCommands": ["clang --version", "cmake --version", "ninja --version"],
    },
}


def github_headers(token: str) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "pystudio-runtime-manifest",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_json(url: str, token: str = "") -> Any:
    request = urllib.request.Request(url, headers=github_headers(token))
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {url} failed: HTTP {exc.code}: {detail}") from exc


def fetch_text(url: str, token: str = "") -> str:
    request = urllib.request.Request(url, headers=github_headers(token))
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {url} failed: HTTP {exc.code}: {detail}") from exc


def release_download_url(repo: str, tag: str, asset_name: str) -> str:
    owner, name = repo.split("/", 1)
    quoted_tag = urllib.parse.quote(tag, safe="")
    quoted_asset = urllib.parse.quote(asset_name, safe="")
    return f"https://github.com/{owner}/{name}/releases/download/{quoted_tag}/{quoted_asset}"


def release_number(tag: str, prefix: str) -> int:
    match = re.fullmatch(re.escape(prefix) + r"(\d+)", tag)
    return int(match.group(1)) if match else -1


def latest_release(repo: str, tag_prefix: str, token: str, explicit_tag: str = "") -> dict[str, Any] | None:
    owner, name = repo.split("/", 1)
    if explicit_tag:
        url = f"{GITHUB_API}/repos/{owner}/{name}/releases/tags/{urllib.parse.quote(explicit_tag, safe='')}"
        return fetch_json(url, token)

    url = f"{GITHUB_API}/repos/{owner}/{name}/releases?per_page=100"
    releases = fetch_json(url, token)
    candidates = [
        release
        for release in releases
        if not release.get("draft")
        and not release.get("prerelease")
        and release.get("tag_name", "").startswith(tag_prefix)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda release: release_number(release["tag_name"], tag_prefix))


def latest_release_with_asset_prefix(
    repo: str,
    tag_prefix: str,
    asset_prefix: str,
    token: str,
) -> dict[str, Any] | None:
    owner, name = repo.split("/", 1)
    url = f"{GITHUB_API}/repos/{owner}/{name}/releases?per_page=100"
    releases = fetch_json(url, token)
    candidates = []
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        if not release.get("tag_name", "").startswith(tag_prefix):
            continue
        if any(asset.get("name", "").startswith(asset_prefix) for asset in release.get("assets", [])):
            candidates.append(release)
    if not candidates:
        return None
    return max(candidates, key=lambda release: release_number(release["tag_name"], tag_prefix))


def asset_names(release: dict[str, Any] | None) -> set[str]:
    if not release:
        return set()
    return {asset["name"] for asset in release.get("assets", [])}


def load_manifest(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"version": 1, "architectures": ARCHITECTURES, "profiles": []}


def profile_index(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    profiles = manifest.setdefault("profiles", [])
    return {profile["id"]: profile for profile in profiles}


def ordered_profiles(manifest: dict[str, Any], order: list[str]) -> None:
    profiles = manifest.get("profiles", [])
    rank = {profile_id: index for index, profile_id in enumerate(order)}
    profiles.sort(key=lambda profile: (rank.get(profile.get("id", ""), 10000), profile.get("id", "")))


def upsert_core_profile(manifest: dict[str, Any], profile_id: str, config: dict[str, Any], token: str) -> None:
    primary_release_repo = config.get("primary_release_repo", config["primary_repo"])
    secondary_release_repo = config.get("secondary_release_repo", config["secondary_repo"])
    primary_asset_prefix = config.get("primary_asset_prefix", config["asset_prefix"])
    secondary_asset_prefix = config.get("secondary_asset_prefix", config["asset_prefix"])
    if "primary_release_repo" in config:
        primary = latest_release_with_asset_prefix(
            primary_release_repo,
            config["tag_prefix"],
            primary_asset_prefix,
            token,
        )
        secondary = latest_release_with_asset_prefix(
            secondary_release_repo,
            config["tag_prefix"],
            secondary_asset_prefix,
            token,
        )
    else:
        primary = latest_release(primary_release_repo, config["tag_prefix"], token)
        secondary = latest_release(secondary_release_repo, config["tag_prefix"], token)
    if not primary and not secondary:
        print(f"Skipping {profile_id}: no releases found.")
        return

    profiles = profile_index(manifest)
    entry = profiles.get(profile_id, {"id": profile_id})
    entry.update(
        {
            "group": config["group"],
            "title": config["title"],
            "description": config["description"],
            "packages": config["packages"],
            "source": {
                "primaryRepository": f"https://github.com/{config['primary_repo']}",
                "secondaryRepository": f"https://github.com/{config['secondary_repo']}",
            },
            "release": {
                "primaryTag": primary["tag_name"] if primary else entry.get("release", {}).get("primaryTag", ""),
                "secondaryTag": secondary["tag_name"] if secondary else entry.get("release", {}).get("secondaryTag", ""),
            },
            "installCommandName": config["installCommandName"],
            "verifyCommands": config["verifyCommands"],
        }
    )

    architectures = entry.setdefault("architectures", {})
    asset_count = 0
    for arch in ARCHITECTURES:
        arch_entry = architectures.setdefault(arch, {})
        for release, repo, asset_prefix, key_prefix in (
            (primary, primary_release_repo, primary_asset_prefix, ""),
            (secondary, secondary_release_repo, secondary_asset_prefix, "fallback"),
        ):
            if not release:
                continue
            names = asset_names(release)
            repo_asset = f"{asset_prefix}-repo-{arch}.tar.gz"
            debs_asset = f"{asset_prefix}-debs-{arch}.tar.gz"
            sums_asset = f"SHA256SUMS-{arch}.txt"
            key = (key_prefix + "RepoArchiveUrl") if key_prefix else "repoArchiveUrl"
            if repo_asset in names:
                arch_entry[key] = release_download_url(repo, release["tag_name"], repo_asset)
                asset_count += 1
            key = (key_prefix + "DebsArchiveUrl") if key_prefix else "debsArchiveUrl"
            if debs_asset in names:
                arch_entry[key] = release_download_url(repo, release["tag_name"], debs_asset)
            key = (key_prefix + "Sha256SumsUrl") if key_prefix else "sha256SumsUrl"
            if sums_asset in names:
                arch_entry[key] = release_download_url(repo, release["tag_name"], sums_asset)

    if asset_count == 0 and profile_id not in profiles:
        print(f"Skipping {profile_id}: no matching assets found.")
        return

    if profile_id not in profiles:
        manifest.setdefault("profiles", []).append(entry)
    print(f"Updated {profile_id}.")


def package_list_from_text(text: str) -> list[str]:
    packages: list[str] = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            packages.append(line)
    return packages


def fetch_extension_packages(package_file: str, token: str) -> list[str]:
    text = fetch_text(urllib.parse.urljoin(EXTENSIONS_RAW_BASE, package_file), token)
    return package_list_from_text(text)


def upsert_extension_profiles(
    manifest: dict[str, Any],
    token: str,
    extension_tag: str = "",
) -> None:
    metadata = fetch_json(EXTENSIONS_METADATA_URL, token)
    release = latest_release(
        EXTENSIONS_REPO,
        "pystudio-python-extensions-r",
        token,
        explicit_tag=extension_tag,
    )
    if not release:
        print("Skipping Python extensions: no release found.")
        return

    names = asset_names(release)
    profiles = profile_index(manifest)
    for meta in metadata.get("profiles", []):
        profile_id = meta["id"]
        arch_map: dict[str, dict[str, str]] = {}
        for arch in ARCHITECTURES:
            repo_asset = f"pystudio-python-extensions-{profile_id}-repo-{arch}.tar.gz"
            debs_asset = f"pystudio-python-extensions-{profile_id}-debs-{arch}.tar.gz"
            sums_asset = f"SHA256SUMS-{profile_id}-{arch}.txt"
            if repo_asset not in names or sums_asset not in names:
                continue
            arch_entry = {
                "repoArchiveUrl": release_download_url(EXTENSIONS_REPO, release["tag_name"], repo_asset),
                "sha256SumsUrl": release_download_url(EXTENSIONS_REPO, release["tag_name"], sums_asset),
            }
            if debs_asset in names:
                arch_entry["debsArchiveUrl"] = release_download_url(EXTENSIONS_REPO, release["tag_name"], debs_asset)
            arch_map[arch] = arch_entry

        if not arch_map:
            continue

        try:
            packages = fetch_extension_packages(meta["packageFile"], token)
        except RuntimeError as exc:
            existing = profiles.get(profile_id, {})
            packages = existing.get("packages", [])
            print(f"Warning: keeping existing package list for {profile_id}: {exc}")

        entry = profiles.get(profile_id, {"id": profile_id})
        entry.update(
            {
                "group": meta.get("group", "python-extension"),
                "title": meta.get("title", profile_id),
                "description": meta.get("description", ""),
                "packages": packages,
                "source": {"repository": f"https://github.com/{EXTENSIONS_REPO}"},
                "release": {"tag": release["tag_name"]},
                "architectures": {**entry.get("architectures", {}), **arch_map},
                "installCommandName": meta.get("installCommandName", f"pystudio-install-{profile_id}"),
                "verifyCommands": meta.get("verifyCommands", []),
            }
        )
        if meta.get("heavy"):
            entry["heavy"] = True
        if profile_id not in profiles:
            manifest.setdefault("profiles", []).append(entry)
        print(f"Updated extension profile {profile_id}: {', '.join(sorted(arch_map))}.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="runtime-packages.json")
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--extension-tag", default="")
    parser.add_argument("--skip-core", action="store_true")
    parser.add_argument("--skip-extensions", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(args.manifest)
    manifest = load_manifest(path)
    manifest["version"] = int(manifest.get("version", 1))
    manifest["updatedAt"] = dt.date.today().isoformat()
    manifest["architectures"] = ARCHITECTURES

    if not args.skip_core:
        for profile_id, config in CORE_PROFILES.items():
            upsert_core_profile(manifest, profile_id, config, args.github_token)

    if not args.skip_extensions:
        upsert_extension_profiles(manifest, args.github_token, args.extension_tag)

    ordered_profiles(manifest, list(CORE_PROFILES) + [profile["id"] for profile in manifest.get("profiles", [])])
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {path} with {len(manifest.get('profiles', []))} profiles.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
