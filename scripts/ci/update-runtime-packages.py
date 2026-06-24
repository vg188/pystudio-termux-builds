#!/usr/bin/env python3
"""Update PyStudio runtime package manifest from GitHub release assets."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shlex
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ARCHITECTURES = ["aarch64", "arm", "i686", "x86_64"]
GITHUB_API = "https://api.github.com"
REPO_ROOT = Path(__file__).resolve().parents[2]
PYSTUDIO_PACKAGE_NAME = os.environ.get("PYSTUDIO_PACKAGE_NAME", "com.vchangxiao.pystudio")
BOOTSTRAP_RELEASE_REPO = "vg188/pystudio-termux-builds"
BOOTSTRAP_TAG_PREFIX = "pystudio-bootstrap-profiles-r"
EXTENSIONS_REPO = "vg188/pystudio-python-extensions"
EXTENSIONS_METADATA_URL = (
    "https://raw.githubusercontent.com/vg188/pystudio-python-extensions/main/"
    "extension-profiles.json"
)
EXTENSIONS_RAW_BASE = "https://raw.githubusercontent.com/vg188/pystudio-python-extensions/main/"

EXTENSION_PROFILE_COMMANDS: dict[str, list[str]] = {
    "pip-build-core": [
        "python",
        "python3",
        "pip",
        "pip3",
        "make",
        "cmake",
        "ctest",
        "cpack",
        "ninja",
        "pkg-config",
        "pkgconf",
        "pybind11-config",
        "openssl",
        "xmllint",
        "xmlcatalog",
        "xsltproc",
    ],
    "pip-build-rust": ["rustc", "cargo", "rustdoc", "uv"],
    "native-libs-scientific": [
        "gsl-config",
        "h5cc",
        "h5dump",
        "h5ls",
        "ncdump",
        "ncgen",
        "fftw-wisdom",
        "qhull",
        "rbox",
        "qconvex",
        "qdelaunay",
        "qvoronoi",
    ],
    "native-libs-data": [
        "duckdb",
        "sqlite3",
        "zstd",
        "unzstd",
        "zstdcat",
        "xmlcatalog",
        "xmllint",
        "xsltproc",
    ],
    "native-libs-image": [
        "fc-cache",
        "fc-list",
        "fc-match",
        "freetype-config",
        "cjpeg",
        "djpeg",
        "jpegtran",
        "pngfix",
        "tiffinfo",
        "tiffcp",
        "cwebp",
        "dwebp",
        "img2webp",
        "webpinfo",
        "webpmux",
        "opj_compress",
        "opj_decompress",
    ],
    "native-libs-visualize": ["fc-cache", "fc-list", "fc-match", "freetype-config", "qhull"],
    "native-libs-markup": [
        "xmllint",
        "xmlcatalog",
        "xsltproc",
        "xmlsec1",
        "tidy",
        "hxclean",
        "hxcopy",
        "hxextract",
        "hxnormalize",
        "hxpipe",
        "hxselect",
        "hxtoc",
    ],
    "native-libs-crypto-network": [
        "openssl",
        "curl",
        "protoc",
        "grpc_cpp_plugin",
        "kinit",
        "klist",
        "kdestroy",
        "kvno",
    ],
    "native-libs-media": [
        "flac",
        "metaflac",
        "opusdec",
        "opusenc",
        "opusinfo",
        "cwebp",
        "dwebp",
        "jpegtran",
        "cjpeg",
        "djpeg",
        "taglib-config",
    ],
    "prebuilt-python-scientific": ["python", "python3", "pip", "pip3"],
    "prebuilt-python-data": ["python", "python3", "pip", "pip3"],
    "prebuilt-python-image": ["python", "python3", "pip", "pip3"],
    "prebuilt-python-visualize": ["python", "python3", "pip", "pip3"],
    "prebuilt-python-markup": ["python", "python3", "pip", "pip3"],
    "prebuilt-python-crypto-network": ["python", "python3", "pip", "pip3"],
    "prebuilt-python-media": ["python", "python3", "pip", "pip3", "ffmpeg", "ffprobe"],
    "prebuilt-python-ai-ml": ["python", "python3", "pip", "pip3"],
}

CORE_PROFILES: dict[str, dict[str, Any]] = {
    "python": {
        "group": "runtime",
        "title": "Python / Pip",
        "description": "CPython runtime, pip, and their Termux dependencies.",
        "packages": ["python", "python-pip"],
        "commands": [
            "python",
            "python3",
            "python-config",
            "python3-config",
            "pip",
            "pip3",
            "pydoc",
            "pydoc3",
            "idle",
            "idle3",
            "py3compile",
            "py3clean",
            "openssl",
            "sqlite3",
            "xz",
            "unxz",
            "xzcat",
            "lzma",
            "unlzma",
        ],
        "primary_repo": "vg188/pystudio-python-toolchain",
        "secondary_repo": "vg188/pystudio-python-toolchain",
        "primary_release_repo": "vg188/pystudio-python-toolchain",
        "secondary_release_repo": "vg188/pystudio-python-toolchain",
        "tag_prefix": "pystudio-python-toolchain-r",
        "primary_tag_prefix": "pystudio-python-toolchain-primary-r",
        "secondary_tag_prefix": "pystudio-python-toolchain-secondary-r",
        "primary_asset_prefix": "pystudio-python-toolchain-primary",
        "secondary_asset_prefix": "pystudio-python-toolchain-secondary",
        "asset_prefix": "pystudio-python-toolchain",
        "primary_legacy_tag_prefix": "pystudio-python-toolchain-r",
        "primary_legacy_asset_prefix": "pystudio-python-toolchain",
        "installCommandName": "pystudio-install-python",
        "verifyCommands": ["python3 --version", "pip3 --version"],
    },
    "nodejs": {
        "group": "runtime",
        "title": "Node.js / npm",
        "description": "Node.js runtime and npm package manager.",
        "packages": ["nodejs", "npm"],
        "commands": ["node", "npm", "npx"],
        "primary_repo": "vg188/pystudio-nodejs-toolchain",
        "secondary_repo": "vg188/pystudio-nodejs-toolchain",
        "primary_release_repo": "vg188/pystudio-nodejs-toolchain",
        "secondary_release_repo": "vg188/pystudio-nodejs-toolchain",
        "tag_prefix": "pystudio-nodejs-toolchain-r",
        "primary_tag_prefix": "pystudio-nodejs-toolchain-primary-r",
        "secondary_tag_prefix": "pystudio-nodejs-toolchain-secondary-r",
        "primary_asset_prefix": "pystudio-nodejs-toolchain-primary",
        "secondary_asset_prefix": "pystudio-nodejs-toolchain-secondary",
        "asset_prefix": "pystudio-nodejs-toolchain",
        "primary_legacy_tag_prefix": "pystudio-nodejs-toolchain-r",
        "primary_legacy_asset_prefix": "pystudio-nodejs-toolchain",
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
        "commands": [
            "node",
            "npm",
            "npx",
            "python",
            "python3",
            "pip",
            "pip3",
            "cc",
            "c++",
            "clang",
            "clang++",
            "ar",
            "as",
            "ld",
            "lld",
            "llvm-ar",
            "llvm-ranlib",
            "make",
            "cmake",
            "ctest",
            "cpack",
            "ninja",
            "pkg-config",
            "pkgconf",
            "openssl",
            "sqlite3",
            "xz",
        ],
        "primary_repo": "vg188/pystudio-node-build-core-toolchain",
        "secondary_repo": "vg188/pystudio-node-build-core-toolchain",
        "primary_release_repo": "vg188/pystudio-node-build-core-toolchain",
        "secondary_release_repo": "vg188/pystudio-node-build-core-toolchain",
        "tag_prefix": "pystudio-node-build-core-toolchain-r",
        "primary_tag_prefix": "pystudio-node-build-core-toolchain-primary-r",
        "secondary_tag_prefix": "pystudio-node-build-core-toolchain-secondary-r",
        "primary_asset_prefix": "pystudio-node-build-core-toolchain-primary",
        "secondary_asset_prefix": "pystudio-node-build-core-toolchain-secondary",
        "asset_prefix": "pystudio-node-build-core-toolchain",
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
        "commands": ["tree-sitter"],
        "primary_repo": "vg188/pystudio-tree-sitter-toolchain",
        "secondary_repo": "vg188/pystudio-tree-sitter-toolchain",
        "primary_release_repo": "vg188/pystudio-tree-sitter-toolchain",
        "secondary_release_repo": "vg188/pystudio-tree-sitter-toolchain",
        "tag_prefix": "pystudio-tree-sitter-toolchain-r",
        "primary_tag_prefix": "pystudio-tree-sitter-toolchain-primary-r",
        "secondary_tag_prefix": "pystudio-tree-sitter-toolchain-secondary-r",
        "primary_asset_prefix": "pystudio-tree-sitter-toolchain-primary",
        "secondary_asset_prefix": "pystudio-tree-sitter-toolchain-secondary",
        "asset_prefix": "pystudio-tree-sitter-toolchain",
        "installCommandName": "pystudio-install-tree-sitter",
        "verifyCommands": ["tree-sitter --version"],
    },
    "cpp": {
        "group": "native-toolchain",
        "title": "C/C++ Toolchain",
        "description": "Compiler, sysroot, CMake, Ninja, Make, and pkg-config.",
        "packages": ["libllvm", "ndk-sysroot", "make", "cmake", "ninja", "pkg-config"],
        "commands": [
            "cc",
            "c++",
            "clang",
            "clang++",
            "cpp",
            "ar",
            "as",
            "ld",
            "lld",
            "llvm-ar",
            "llvm-ranlib",
            "strip",
            "readelf",
            "objdump",
            "nm",
            "make",
            "cmake",
            "ctest",
            "cpack",
            "ninja",
            "pkg-config",
            "pkgconf",
        ],
        "primary_repo": "vg188/pystudio-cpp-toolchain",
        "secondary_repo": "vg188/pystudio-cpp-toolchain",
        "primary_release_repo": "vg188/pystudio-cpp-toolchain",
        "secondary_release_repo": "vg188/pystudio-cpp-toolchain",
        "tag_prefix": "pystudio-cpp-toolchain-r",
        "primary_tag_prefix": "pystudio-cpp-toolchain-primary-r",
        "secondary_tag_prefix": "pystudio-cpp-toolchain-secondary-r",
        "primary_asset_prefix": "pystudio-cpp-toolchain-primary",
        "secondary_asset_prefix": "pystudio-cpp-toolchain-secondary",
        "asset_prefix": "pystudio-cpp-toolchain",
        "primary_legacy_tag_prefix": "pystudio-cpp-toolchain-r",
        "primary_legacy_asset_prefix": "pystudio-cpp-toolchain",
        "installCommandName": "pystudio-install-cpp",
        "verifyCommands": ["clang --version", "cmake --version", "ninja --version"],
    },
}

BOOTSTRAP_DESCRIPTIONS = {
    "base": "Minimal PyStudio terminal bootstrap with proot and core shell packages.",
    "python-pip": "PyStudio terminal bootstrap with proot, Python, and pip preinstalled.",
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
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GET {url} failed: HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError:
            if attempt == 5:
                raise
            time.sleep(attempt * 3)
    raise RuntimeError(f"GET {url} failed unexpectedly")


def fetch_text(url: str, token: str = "") -> str:
    request = urllib.request.Request(url, headers=github_headers(token))
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GET {url} failed: HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError:
            if attempt == 5:
                raise
            time.sleep(attempt * 3)
    raise RuntimeError(f"GET {url} failed unexpectedly")


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


def release_asset_map(release: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not release:
        return {}
    return {asset["name"]: asset for asset in release.get("assets", [])}


def asset_sha256(asset: dict[str, Any]) -> str:
    digest = str(asset.get("digest", ""))
    if digest.startswith("sha256:"):
        return digest.split(":", 1)[1]
    return ""


def set_asset_metadata(entry: dict[str, Any], key_prefix: str, asset: dict[str, Any]) -> None:
    entry[f"{key_prefix}Url"] = str(asset["browser_download_url"])
    entry[f"{key_prefix}Size"] = int(asset.get("size", 0))
    sha256 = asset_sha256(asset)
    if sha256:
        entry[f"{key_prefix}Sha256"] = sha256


def load_manifest(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"version": 1, "architectures": ARCHITECTURES, "bootstraps": [], "profiles": []}


def profile_index(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    profiles = manifest.setdefault("profiles", [])
    return {profile["id"]: profile for profile in profiles}


def unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def command_names_from_verify(verify_commands: list[str]) -> list[str]:
    commands: list[str] = []
    for command in verify_commands:
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = command.split()
        if parts:
            commands.append(Path(parts[0]).name)
    return unique_strings(commands)


def profile_commands(profile_id: str, metadata: dict[str, Any]) -> list[str]:
    explicit = metadata.get("commands")
    if isinstance(explicit, list):
        return unique_strings([str(command) for command in explicit])
    if profile_id in EXTENSION_PROFILE_COMMANDS:
        return EXTENSION_PROFILE_COMMANDS[profile_id]
    return command_names_from_verify(metadata.get("verifyCommands", []))


def ordered_profiles(manifest: dict[str, Any], order: list[str]) -> None:
    profiles = manifest.get("profiles", [])
    rank = {profile_id: index for index, profile_id in enumerate(order)}
    profiles.sort(key=lambda profile: (rank.get(profile.get("id", ""), 10000), profile.get("id", "")))


def parse_env_value(raw_value: str) -> str:
    try:
        parts = shlex.split(raw_value, comments=False, posix=True)
    except ValueError:
        return raw_value.strip().strip("\"'")
    return parts[0] if parts else ""


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            values[key] = parse_env_value(raw_value.strip())
    return values


def package_list_from_env(value: str) -> list[str]:
    return unique_strings([part for part in re.split(r"[\s,]+", value) if part])


def bootstrap_profile_configs() -> list[dict[str, Any]]:
    profiles_dir = REPO_ROOT / "profiles" / "bootstrap"
    order = {"base": 0, "python-pip": 1}
    configs: list[dict[str, Any]] = []
    for path in sorted(profiles_dir.glob("*.env")):
        env = parse_env_file(path)
        profile_id = env.get("PROFILE_SLUG", path.stem)
        profile_name = env.get("PROFILE_NAME", profile_id.replace("-", " ").title())
        configs.append(
            {
                "id": profile_id,
                "title": f"{profile_name} Bootstrap",
                "description": BOOTSTRAP_DESCRIPTIONS.get(
                    profile_id,
                    f"PyStudio {profile_name} bootstrap rootfs.",
                ),
                "packages": package_list_from_env(env.get("DEFAULT_ADDITIONAL_PACKAGES", "")),
                "source_repo": env.get("SOURCE_REPO", ""),
                "artifact_prefix": env.get("ARTIFACT_PREFIX", f"pystudio-{profile_id}-bootstrap"),
                "alias_suffix": env.get("BOOTSTRAP_ALIAS_SUFFIX", f"{profile_id}-bootstrap"),
            }
        )
    return sorted(configs, key=lambda config: (order.get(config["id"], 100), config["id"]))


def upsert_bootstraps(manifest: dict[str, Any], token: str) -> None:
    release = latest_release(BOOTSTRAP_RELEASE_REPO, BOOTSTRAP_TAG_PREFIX, token)
    if not release:
        print("Skipping bootstraps: no releases found.")
        return

    assets = release_asset_map(release)
    bootstraps: list[dict[str, Any]] = []
    for config in bootstrap_profile_configs():
        entry: dict[str, Any] = {
            "id": config["id"],
            "group": "bootstrap",
            "title": config["title"],
            "description": config["description"],
            "packageName": PYSTUDIO_PACKAGE_NAME,
            "packages": config["packages"],
            "source": {"repository": config["source_repo"]},
            "release": {
                "repository": f"https://github.com/{BOOTSTRAP_RELEASE_REPO}",
                "tag": release["tag_name"],
            },
            "archiveFormat": "termux-bootstrap-tar.xz",
            "installMode": "extract-rootfs",
            "architectures": {},
        }

        for arch in ARCHITECTURES:
            arch_entry: dict[str, Any] = {}
            alias_asset = assets.get(
                f"{PYSTUDIO_PACKAGE_NAME}-f-droid-{config['alias_suffix']}-{arch}.tar.xz"
            )
            generic_asset = assets.get(f"bootstrap-{arch}.tar.xz")
            assets_archive = assets.get(f"{config['artifact_prefix']}-assets-{arch}.tar.gz")

            if alias_asset:
                set_asset_metadata(arch_entry, "bootstrapArchive", alias_asset)
            elif generic_asset:
                set_asset_metadata(arch_entry, "bootstrapArchive", generic_asset)

            if generic_asset and config["id"] == "base":
                set_asset_metadata(arch_entry, "termuxBootstrapArchive", generic_asset)

            if assets_archive:
                set_asset_metadata(arch_entry, "assetsArchive", assets_archive)

            if arch_entry:
                entry["architectures"][arch] = arch_entry

        if entry["architectures"]:
            bootstraps.append(entry)
            print(f"Updated bootstrap {config['id']}: {', '.join(entry['architectures'])}.")
        else:
            print(f"Skipping bootstrap {config['id']}: no matching assets found.")

    manifest["bootstraps"] = bootstraps


def upsert_core_profile(manifest: dict[str, Any], profile_id: str, config: dict[str, Any], token: str) -> None:
    release_repo = config.get("primary_release_repo", config["primary_repo"])
    asset_prefix = config["asset_prefix"]
    release = latest_release_with_asset_prefix(release_repo, config["tag_prefix"], asset_prefix, token)
    if not release and config.get("primary_legacy_tag_prefix") and config.get("primary_legacy_asset_prefix"):
        release = latest_release_with_asset_prefix(
            release_repo,
            config["primary_legacy_tag_prefix"],
            config["primary_legacy_asset_prefix"],
            token,
        )
        if release:
            asset_prefix = config["primary_legacy_asset_prefix"]
    if not release:
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
            "commands": profile_commands(profile_id, config),
            "source": {
                "repository": f"https://github.com/{release_repo}",
            },
            "release": {
                "tag": release["tag_name"],
            },
            "installCommandName": config["installCommandName"],
            "verifyCommands": config["verifyCommands"],
        }
    )

    architectures = entry.setdefault("architectures", {})
    asset_count = 0
    for arch in ARCHITECTURES:
        arch_entry = architectures.setdefault(arch, {})
        for stale_key in (
            "fallbackRepoArchiveUrl",
            "fallbackDebsArchiveUrl",
            "fallbackSha256SumsUrl",
        ):
            arch_entry.pop(stale_key, None)
        names = asset_names(release)
        repo_asset = f"{asset_prefix}-repo-{arch}.tar.gz"
        debs_asset = f"{asset_prefix}-debs-{arch}.tar.gz"
        sums_asset = f"SHA256SUMS-{arch}.txt"
        if repo_asset in names:
            arch_entry["repoArchiveUrl"] = release_download_url(release_repo, release["tag_name"], repo_asset)
            asset_count += 1
        if debs_asset in names:
            arch_entry["debsArchiveUrl"] = release_download_url(release_repo, release["tag_name"], debs_asset)
        if sums_asset in names:
            arch_entry["sha256SumsUrl"] = release_download_url(release_repo, release["tag_name"], sums_asset)

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
                "commands": profile_commands(profile_id, meta),
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
    parser.add_argument("--skip-bootstraps", action="store_true")
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

    if not args.skip_bootstraps:
        upsert_bootstraps(manifest, args.github_token)

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
