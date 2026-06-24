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


SCHEMA_VERSION = 2
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
    "python-lsp": {
        "group": "editor-extension",
        "title": "Python LSP",
        "description": "Pyright language server and Ruff linter/formatter for Python editing.",
        "packages": ["python", "python-pip", "nodejs", "pyright", "ruff", "python-ruff"],
        "commands": [
            "python",
            "python3",
            "pip",
            "pip3",
            "node",
            "pyright",
            "pyright-langserver",
            "ruff",
        ],
        "primary_repo": "vg188/pystudio-termux-builds",
        "secondary_repo": "vg188/pystudio-termux-builds",
        "primary_release_repo": "vg188/pystudio-termux-builds",
        "secondary_release_repo": "vg188/pystudio-termux-builds",
        "tag_prefix": "pystudio-toolchains-r",
        "asset_prefix": "pystudio-python-lsp-toolchain-primary",
        "installCommandName": "pystudio-install-python-lsp",
        "verifyCommands": ["pyright --version", "ruff --version"],
    },
    "cpp-lsp": {
        "group": "editor-extension",
        "title": "C/C++ LSP",
        "description": "clangd plus compilation database generators for C and C++ editing.",
        "packages": [
            "libllvm",
            "clang",
            "bear",
            "compiledb",
            "python",
            "python-pip",
            "python-click",
            "python-bashlex",
        ],
        "commands": [
            "clang",
            "clang++",
            "clangd",
            "bear",
            "intercept-build",
            "compiledb",
            "python",
            "python3",
        ],
        "primary_repo": "vg188/pystudio-termux-builds",
        "secondary_repo": "vg188/pystudio-termux-builds",
        "primary_release_repo": "vg188/pystudio-termux-builds",
        "secondary_release_repo": "vg188/pystudio-termux-builds",
        "tag_prefix": "pystudio-toolchains-r",
        "asset_prefix": "pystudio-cpp-lsp-toolchain-primary",
        "installCommandName": "pystudio-install-cpp-lsp",
        "verifyCommands": ["clangd --version", "bear --version", "compiledb --version"],
    },
    "debug-tools": {
        "group": "debug-toolchain",
        "title": "Debug Tools",
        "description": "debugpy plus LLDB and lldb-server for Python and native debugging.",
        "packages": ["python", "python-pip", "debugpy", "libllvm", "lldb"],
        "commands": [
            "python",
            "python3",
            "debugpy",
            "debugpy-adapter",
            "lldb",
            "lldb-server",
        ],
        "primary_repo": "vg188/pystudio-termux-builds",
        "secondary_repo": "vg188/pystudio-termux-builds",
        "primary_release_repo": "vg188/pystudio-termux-builds",
        "secondary_release_repo": "vg188/pystudio-termux-builds",
        "tag_prefix": "pystudio-toolchains-r",
        "asset_prefix": "pystudio-debug-tools-toolchain-primary",
        "installCommandName": "pystudio-install-debug-tools",
        "verifyCommands": ["python -m debugpy --version", "lldb --version", "lldb-server --help"],
    },
    "git": {
        "group": "developer-tool",
        "title": "Git",
        "description": "Git version control with SSH support for clone, fetch, and push workflows.",
        "packages": ["git", "openssh"],
        "commands": [
            "git",
            "git-upload-pack",
            "git-receive-pack",
            "git-shell",
            "ssh",
            "scp",
            "sftp",
            "ssh-keygen",
        ],
        "primary_repo": "vg188/pystudio-termux-builds",
        "secondary_repo": "vg188/pystudio-termux-builds",
        "primary_release_repo": "vg188/pystudio-termux-builds",
        "secondary_release_repo": "vg188/pystudio-termux-builds",
        "tag_prefix": "pystudio-toolchains-r",
        "asset_prefix": "pystudio-git-toolchain-primary",
        "installCommandName": "pystudio-install-git",
        "verifyCommands": ["git --version", "ssh -V"],
    },
}

BOOTSTRAP_DESCRIPTIONS = {
    "base": "Minimal PyStudio terminal bootstrap with proot and core shell packages.",
    "python-pip": "PyStudio terminal bootstrap with proot, Python, and pip preinstalled.",
}

BOOTSTRAP_COMMANDS = [
    "sh",
    "bash",
    "dash",
    "ls",
    "pwd",
    "cat",
    "cp",
    "mv",
    "rm",
    "mkdir",
    "pkg",
    "apt",
    "dpkg",
    "proot",
]

BOOTSTRAP_PROFILE_COMMANDS = {
    "python-pip": ["python", "python3", "pip", "pip3"],
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


def release_asset_map(release: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not release:
        return {}
    return {asset["name"]: asset for asset in release.get("assets", [])}


def asset_sha256(asset: dict[str, Any]) -> str:
    digest = str(asset.get("digest", ""))
    if digest.startswith("sha256:"):
        return digest.split(":", 1)[1]
    return ""


def artifact_format(file_name: str) -> str:
    for suffix in (".tar.xz", ".tar.gz", ".txt", ".deb"):
        if file_name.endswith(suffix):
            return suffix.removeprefix(".")
    return Path(file_name).suffix.removeprefix(".") or "binary"


def artifact_from_asset(role: str, asset: dict[str, Any]) -> dict[str, Any]:
    file_name = str(asset["name"])
    artifact: dict[str, Any] = {
        "role": role,
        "fileName": file_name,
        "format": artifact_format(file_name),
        "downloadUrl": str(asset["browser_download_url"]),
        "size": int(asset.get("size", 0)),
    }
    sha256 = asset_sha256(asset)
    if sha256:
        artifact["sha256"] = sha256
    return artifact


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


def item_order_key(item_id: str) -> tuple[int, int, str]:
    bootstrap_order = {"bootstrap-base": 0, "bootstrap-python-pip": 1}
    runtime_order = {
        "python": 0,
        "nodejs": 1,
        "cpp": 2,
        "tree-sitter": 3,
        "node-build-core": 4,
        "python-lsp": 5,
        "cpp-lsp": 6,
        "debug-tools": 7,
        "git": 8,
    }
    if item_id in bootstrap_order:
        return (0, bootstrap_order[item_id], item_id)
    if item_id in runtime_order:
        return (1, runtime_order[item_id], item_id)
    return (2, 10000, item_id)


def ordered_items(manifest: dict[str, Any]) -> None:
    manifest.get("items", []).sort(key=lambda item: item_order_key(item.get("id", "")))


def base_item(
    *,
    item_id: str,
    item_type: str,
    group: str,
    title: str,
    description: str,
    packages: list[str],
    commands: list[str],
    source_repository: str,
    release_repository: str,
    release_tag: str,
    install_mode: str,
    install_command: str | None,
    verify_commands: list[str],
    profile: str,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "type": item_type,
        "group": group,
        "profile": profile,
        "title": title,
        "description": description,
        "packages": packages,
        "commands": commands,
        "source": {
            "repository": source_repository,
        },
        "release": {
            "repository": release_repository,
            "tag": release_tag,
        },
        "install": {
            "mode": install_mode,
            "command": install_command,
            "verifyCommands": verify_commands,
        },
        "availableArchitectures": [],
        "artifacts": {},
    }


def set_arch_artifacts(item: dict[str, Any], arch: str, artifacts: list[dict[str, Any]]) -> None:
    if not artifacts:
        return
    item["artifacts"][arch] = artifacts
    item["availableArchitectures"] = sorted(item["artifacts"], key=ARCHITECTURES.index)


def validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise RuntimeError(f"manifest schemaVersion must be {SCHEMA_VERSION}")
    if manifest.get("architectures") != ARCHITECTURES:
        raise RuntimeError("manifest architectures are not normalized")
    if not isinstance(manifest.get("items"), list):
        raise RuntimeError("manifest items must be a list")

    ids: set[str] = set()
    for item in manifest["items"]:
        item_id = item.get("id")
        if not item_id or item_id in ids:
            raise RuntimeError(f"invalid or duplicate manifest item id: {item_id!r}")
        ids.add(item_id)

        for key in (
            "type",
            "group",
            "profile",
            "title",
            "description",
            "packages",
            "commands",
            "source",
            "release",
            "install",
            "availableArchitectures",
            "artifacts",
        ):
            if key not in item:
                raise RuntimeError(f"manifest item {item_id} missing key: {key}")

        if sorted(item["artifacts"], key=ARCHITECTURES.index) != item["availableArchitectures"]:
            raise RuntimeError(f"manifest item {item_id} has inconsistent architecture lists")

        for arch, artifacts in item["artifacts"].items():
            if arch not in ARCHITECTURES:
                raise RuntimeError(f"manifest item {item_id} has unsupported architecture: {arch}")
            if not isinstance(artifacts, list) or not artifacts:
                raise RuntimeError(f"manifest item {item_id} has no artifacts for {arch}")
            for artifact in artifacts:
                for key in ("role", "fileName", "format", "downloadUrl", "size"):
                    if key not in artifact:
                        raise RuntimeError(
                            f"manifest item {item_id} artifact for {arch} missing key: {key}"
                        )


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
    for config in bootstrap_profile_configs():
        profile_id = config["id"]
        entry = base_item(
            item_id=f"bootstrap-{profile_id}",
            item_type="bootstrap",
            group="bootstrap",
            title=config["title"],
            description=config["description"],
            packages=config["packages"],
            commands=unique_strings(
                BOOTSTRAP_COMMANDS + BOOTSTRAP_PROFILE_COMMANDS.get(profile_id, [])
            ),
            source_repository=config["source_repo"],
            release_repository=f"https://github.com/{BOOTSTRAP_RELEASE_REPO}",
            release_tag=release["tag_name"],
            install_mode="extract-rootfs",
            install_command=None,
            verify_commands=[],
            profile=profile_id,
        )

        for arch in ARCHITECTURES:
            arch_artifacts: list[dict[str, Any]] = []
            alias_asset = assets.get(
                f"{PYSTUDIO_PACKAGE_NAME}-f-droid-{config['alias_suffix']}-{arch}.tar.xz"
            )
            generic_asset = assets.get(f"bootstrap-{arch}.tar.xz")
            assets_archive = assets.get(f"{config['artifact_prefix']}-assets-{arch}.tar.gz")

            if alias_asset:
                arch_artifacts.append(artifact_from_asset("rootfs", alias_asset))
            elif generic_asset:
                arch_artifacts.append(artifact_from_asset("rootfs", generic_asset))

            if generic_asset and profile_id == "base":
                arch_artifacts.append(artifact_from_asset("compat-rootfs", generic_asset))

            if assets_archive:
                arch_artifacts.append(artifact_from_asset("asset-bundle", assets_archive))

            set_arch_artifacts(entry, arch, arch_artifacts)

        if entry["artifacts"]:
            manifest.setdefault("items", []).append(entry)
            print(f"Updated bootstrap {profile_id}: {', '.join(entry['availableArchitectures'])}.")
        else:
            print(f"Skipping bootstrap {profile_id}: no matching assets found.")


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

    entry = base_item(
        item_id=profile_id,
        item_type="package-set",
        group=config["group"],
        title=config["title"],
        description=config["description"],
        packages=config["packages"],
        commands=profile_commands(profile_id, config),
        source_repository=f"https://github.com/{release_repo}",
        release_repository=f"https://github.com/{release_repo}",
        release_tag=release["tag_name"],
        install_mode="install-apt-repository",
        install_command=config["installCommandName"],
        verify_commands=config["verifyCommands"],
        profile=profile_id,
    )

    asset_count = 0
    assets = release_asset_map(release)
    for arch in ARCHITECTURES:
        arch_artifacts: list[dict[str, Any]] = []
        repo_asset = f"{asset_prefix}-repo-{arch}.tar.gz"
        debs_asset = f"{asset_prefix}-debs-{arch}.tar.gz"
        sums_asset = f"SHA256SUMS-{arch}.txt"
        if repo_asset in assets:
            arch_artifacts.append(artifact_from_asset("apt-repository", assets[repo_asset]))
            asset_count += 1
        if debs_asset in assets:
            arch_artifacts.append(artifact_from_asset("debian-packages", assets[debs_asset]))
        if sums_asset in assets:
            arch_artifacts.append(artifact_from_asset("checksums", assets[sums_asset]))
        set_arch_artifacts(entry, arch, arch_artifacts)

    if asset_count == 0:
        print(f"Skipping {profile_id}: no matching assets found.")
        return

    manifest.setdefault("items", []).append(entry)
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

    assets = release_asset_map(release)
    for meta in metadata.get("profiles", []):
        profile_id = meta["id"]
        arch_map: dict[str, list[dict[str, Any]]] = {}
        for arch in ARCHITECTURES:
            repo_asset = f"pystudio-python-extensions-{profile_id}-repo-{arch}.tar.gz"
            debs_asset = f"pystudio-python-extensions-{profile_id}-debs-{arch}.tar.gz"
            sums_asset = f"SHA256SUMS-{profile_id}-{arch}.txt"
            if repo_asset not in assets or sums_asset not in assets:
                continue
            arch_artifacts = [
                artifact_from_asset("apt-repository", assets[repo_asset]),
                artifact_from_asset("checksums", assets[sums_asset]),
            ]
            if debs_asset in assets:
                arch_artifacts.append(artifact_from_asset("debian-packages", assets[debs_asset]))
            arch_map[arch] = arch_artifacts

        if not arch_map:
            continue

        try:
            packages = fetch_extension_packages(meta["packageFile"], token)
        except RuntimeError as exc:
            packages = []
            print(f"Warning: no package list for {profile_id}: {exc}")

        entry = base_item(
            item_id=profile_id,
            item_type="package-set",
            group=meta.get("group", "python-extension"),
            title=meta.get("title", profile_id),
            description=meta.get("description", ""),
            packages=packages,
            commands=profile_commands(profile_id, meta),
            source_repository=f"https://github.com/{EXTENSIONS_REPO}",
            release_repository=f"https://github.com/{EXTENSIONS_REPO}",
            release_tag=release["tag_name"],
            install_mode="install-apt-repository",
            install_command=meta.get("installCommandName", f"pystudio-install-{profile_id}"),
            verify_commands=meta.get("verifyCommands", []),
            profile=profile_id,
        )
        for arch, artifacts in arch_map.items():
            set_arch_artifacts(entry, arch, artifacts)
        if meta.get("heavy"):
            entry["heavy"] = True
        manifest.setdefault("items", []).append(entry)
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
    manifest: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": dt.date.today().isoformat(),
        "packageName": PYSTUDIO_PACKAGE_NAME,
        "architectures": ARCHITECTURES,
        "items": [],
    }

    if not args.skip_bootstraps:
        upsert_bootstraps(manifest, args.github_token)

    if not args.skip_core:
        for profile_id, config in CORE_PROFILES.items():
            upsert_core_profile(manifest, profile_id, config, args.github_token)

    if not args.skip_extensions:
        upsert_extension_profiles(manifest, args.github_token, args.extension_tag)

    ordered_items(manifest)
    validate_manifest(manifest)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {path} with {len(manifest.get('items', []))} items.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
