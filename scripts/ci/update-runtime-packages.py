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


SCHEMA_VERSION = 4
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
DEFAULT_MIGRATION_PLAN = REPO_ROOT / "migration" / "runtime-packages-v2-components.json"

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
    "proot": {
        "group": "runtime",
        "title": "PRoot Runtime",
        "description": (
            "Standalone PRoot runtime based on the Termux-maintained proot fork, "
            "including libandroid-shmem support and high-version Android compatibility fixes."
        ),
        "packages": [
            "proot",
            "libandroid-shmem",
            "libtalloc",
        ],
        "commands": [
            "proot",
            "termux-chroot",
        ],
        "primary_repo": "vg188/pystudio-termux-builds",
        "secondary_repo": "vg188/pystudio-termux-builds",
        "primary_release_repo": "vg188/pystudio-termux-builds",
        "secondary_release_repo": "vg188/pystudio-termux-builds",
        "tag_prefix": "pystudio-toolchains-r",
        "asset_prefix": "pystudio-proot-toolchain-primary",
        "installCommandName": "pystudio-install-proot",
        "verifyCommands": ["proot --version", "termux-chroot -h"],
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


def repo_slug_from_url(value: str) -> str:
    prefix = "https://github.com/"
    if value.startswith(prefix):
        value = value[len(prefix) :]
    return value.removesuffix(".git").strip("/")


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
    for suffix in (".tar.xz", ".tar.gz", ".txt", ".json", ".deb"):
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


def component_index_asset_name(asset_prefix: str, arch: str) -> str:
    return f"{asset_prefix}-component-index-{arch}.json"


def component_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return manifest.setdefault("components", {})


def component_package_index(manifest: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    index = manifest.setdefault("componentPackages", {})
    for arch in ARCHITECTURES:
        index.setdefault(arch, {})
    return index


def component_entry_from_index(
    package: dict[str, Any],
    release_repo: str,
    release_tag: str,
    asset: dict[str, Any],
) -> dict[str, Any]:
    artifact = artifact_from_asset("component-deb", asset)
    artifact["fileName"] = str(package.get("fileName") or artifact["fileName"])
    artifact["assetName"] = str(asset["name"])
    if package.get("sha256"):
        artifact["sha256"] = str(package["sha256"])
    if package.get("size"):
        artifact["size"] = int(package["size"])

    dependency_names = unique_strings([str(item) for item in package.get("dependencyNames", [])])
    entry = {
        "id": str(package["id"]),
        "kind": "component",
        "format": "deb",
        "package": str(package["package"]),
        "version": str(package["version"]),
        "architecture": str(package["architecture"]),
        "debArchitecture": str(package.get("debArchitecture", package["architecture"])),
        "source": {
            "profile": str(package.get("sourceProfile", "")),
            "adapter": str(package.get("source", "")),
        },
        "commands": unique_strings([str(item) for item in package.get("commands", [])]),
        "dependencyNames": dependency_names,
        "dependencies": {
            "depends": str(package.get("depends", "")),
            "preDepends": str(package.get("preDepends", "")),
            "names": dependency_names,
        },
        "release": {
            "repository": f"https://github.com/{release_repo}",
            "tag": release_tag,
        },
        "artifact": artifact,
    }
    return entry


def register_component(manifest: dict[str, Any], component: dict[str, Any]) -> None:
    components = component_map(manifest)
    components.setdefault(component["id"], component)

    arch = str(component["architecture"])
    package = str(component["package"])
    packages = component_package_index(manifest).setdefault(arch, {})
    refs = packages.setdefault(package, [])
    if component["id"] not in refs:
        refs.append(component["id"])


def attach_component_index(
    manifest: dict[str, Any],
    entry_id: str,
    arch: str,
    release_repo: str,
    release_tag: str,
    assets: dict[str, dict[str, Any]],
    index_asset: dict[str, Any],
    token: str,
) -> list[str]:
    index = fetch_json(str(index_asset["browser_download_url"]), token)
    component_ids: list[str] = []
    for package in index.get("packages", []):
        asset_name = str(package.get("assetName", ""))
        asset = assets.get(asset_name)
        if not asset:
            print(f"Warning: component asset missing for {entry_id}/{arch}: {asset_name}")
            continue
        component = component_entry_from_index(package, release_repo, release_tag, asset)
        register_component(manifest, component)
        component_ids.append(component["id"])
    return unique_strings(component_ids)


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


def entry_order_key(entry_id: str) -> tuple[int, int, str]:
    bootstrap_order = {"bootstrap-base": 0, "bootstrap-python-pip": 1}
    runtime_order = {
        "python": 0,
        "nodejs": 1,
        "proot": 2,
        "cpp": 3,
        "tree-sitter": 4,
        "node-build-core": 5,
        "python-lsp": 6,
        "cpp-lsp": 7,
        "debug-tools": 8,
        "git": 9,
    }
    if entry_id in bootstrap_order:
        return (0, bootstrap_order[entry_id], entry_id)
    if entry_id in runtime_order:
        return (1, runtime_order[entry_id], entry_id)
    return (2, 10000, entry_id)


def ordered_entries(manifest: dict[str, Any]) -> None:
    manifest.get("entries", []).sort(key=lambda entry: entry_order_key(entry.get("id", "")))


def base_entry(
    *,
    entry_id: str,
    kind: str,
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
    install: dict[str, Any] = {
        "mode": install_mode,
        "verifyCommands": verify_commands,
    }
    if install_command:
        install["command"] = install_command

    entry = {
        "id": entry_id,
        "kind": kind,
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
        "install": install,
        "availableArchitectures": [],
    }
    if kind == "bootstrap":
        entry["artifacts"] = {}
    elif kind == "bundle":
        entry["componentRefs"] = {}
    return entry


def set_arch_artifacts(entry: dict[str, Any], arch: str, artifacts: list[dict[str, Any]]) -> None:
    if not artifacts:
        return
    entry["artifacts"][arch] = artifacts
    entry["availableArchitectures"] = sorted(entry["artifacts"], key=ARCHITECTURES.index)
    entry.setdefault("sizeByArch", {})[arch] = sum(int(artifact.get("size", 0)) for artifact in artifacts)


def set_arch_component_refs(
    manifest: dict[str, Any],
    entry: dict[str, Any],
    arch: str,
    component_ids: list[str],
) -> None:
    component_ids = unique_strings(component_ids)
    if not component_ids:
        return
    entry["componentRefs"][arch] = component_ids
    entry["availableArchitectures"] = sorted(entry["componentRefs"], key=ARCHITECTURES.index)
    entry.setdefault("sizeByArch", {})[arch] = sum(
        int(component_map(manifest).get(component_id, {}).get("artifact", {}).get("size", 0))
        for component_id in component_ids
    )


def validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise RuntimeError(f"manifest schemaVersion must be {SCHEMA_VERSION}")
    if manifest.get("architectures") != ARCHITECTURES:
        raise RuntimeError("manifest architectures are not normalized")
    if not isinstance(manifest.get("entries"), list):
        raise RuntimeError("manifest entries must be a list")
    if not isinstance(manifest.get("components"), dict):
        raise RuntimeError("manifest components must be an object")
    if not isinstance(manifest.get("componentPackages"), dict):
        raise RuntimeError("manifest componentPackages must be an object")

    ids: set[str] = set()
    for entry in manifest["entries"]:
        entry_id = entry.get("id")
        if not entry_id or entry_id in ids:
            raise RuntimeError(f"invalid or duplicate manifest entry id: {entry_id!r}")
        ids.add(entry_id)

        for key in (
            "kind",
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
        ):
            if key not in entry:
                raise RuntimeError(f"manifest entry {entry_id} missing key: {key}")

        kind = entry.get("kind")
        if kind == "bootstrap":
            if entry.get("install", {}).get("mode") != "extract-rootfs":
                raise RuntimeError(f"bootstrap {entry_id} must use extract-rootfs")
            artifacts_by_arch = entry.get("artifacts")
            if not isinstance(artifacts_by_arch, dict):
                raise RuntimeError(f"bootstrap {entry_id} missing artifacts")
            if sorted(artifacts_by_arch, key=ARCHITECTURES.index) != entry["availableArchitectures"]:
                raise RuntimeError(f"bootstrap {entry_id} has inconsistent architecture lists")
            for arch, artifacts in artifacts_by_arch.items():
                if arch not in ARCHITECTURES:
                    raise RuntimeError(f"bootstrap {entry_id} has unsupported architecture: {arch}")
                if not isinstance(artifacts, list) or not artifacts:
                    raise RuntimeError(f"bootstrap {entry_id} has no artifacts for {arch}")
                if not any(artifact.get("role") == "rootfs" for artifact in artifacts):
                    raise RuntimeError(f"bootstrap {entry_id}/{arch} has no rootfs artifact")
                for artifact in artifacts:
                    for key in ("role", "fileName", "format", "downloadUrl", "size"):
                        if key not in artifact:
                            raise RuntimeError(
                                f"bootstrap {entry_id} artifact for {arch} missing key: {key}"
                            )
        elif kind == "bundle":
            if entry.get("install", {}).get("mode") != "install-components":
                raise RuntimeError(f"bundle {entry_id} must use install-components")
            component_refs = entry.get("componentRefs")
            if not isinstance(component_refs, dict):
                raise RuntimeError(f"bundle {entry_id} missing componentRefs")
            if sorted(component_refs, key=ARCHITECTURES.index) != entry["availableArchitectures"]:
                raise RuntimeError(f"bundle {entry_id} has inconsistent architecture lists")
            for arch, refs in component_refs.items():
                if arch not in ARCHITECTURES:
                    raise RuntimeError(f"bundle {entry_id} has unsupported architecture: {arch}")
                if not isinstance(refs, list) or not refs:
                    raise RuntimeError(f"bundle {entry_id} has no component refs for {arch}")
                for component_id in refs:
                    component = manifest["components"].get(component_id)
                    if not component:
                        raise RuntimeError(f"bundle {entry_id}/{arch} references missing component {component_id}")
                    if component.get("architecture") != arch:
                        raise RuntimeError(f"bundle {entry_id}/{arch} references {component_id} for wrong arch")
        else:
            raise RuntimeError(f"manifest entry {entry_id} has unsupported kind: {kind}")

    for component_id, component in manifest["components"].items():
        if component.get("id") != component_id:
            raise RuntimeError(f"component key mismatch: {component_id}")
        for key in (
            "kind",
            "format",
            "package",
            "version",
            "architecture",
            "debArchitecture",
            "dependencyNames",
            "commands",
            "release",
            "artifact",
        ):
            if key not in component:
                raise RuntimeError(f"component {component_id} missing key: {key}")
        if component["architecture"] not in ARCHITECTURES:
            raise RuntimeError(f"component {component_id} has unsupported architecture")
        artifact = component["artifact"]
        for key in ("role", "fileName", "format", "downloadUrl", "size"):
            if key not in artifact:
                raise RuntimeError(f"component {component_id} artifact missing key: {key}")
        indexed_refs = manifest["componentPackages"].get(component["architecture"], {}).get(component["package"], [])
        if component_id not in indexed_refs:
            raise RuntimeError(f"component {component_id} missing from componentPackages")


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
        entry = base_entry(
            entry_id=f"bootstrap-{profile_id}",
            kind="bootstrap",
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

            if alias_asset:
                arch_artifacts.append(artifact_from_asset("rootfs", alias_asset))
            elif generic_asset:
                arch_artifacts.append(artifact_from_asset("rootfs", generic_asset))

            set_arch_artifacts(entry, arch, arch_artifacts)

        if entry["artifacts"]:
            manifest.setdefault("entries", []).append(entry)
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

    entry = base_entry(
        entry_id=profile_id,
        kind="bundle",
        group=config["group"],
        title=config["title"],
        description=config["description"],
        packages=config["packages"],
        commands=profile_commands(profile_id, config),
        source_repository=f"https://github.com/{release_repo}",
        release_repository=f"https://github.com/{release_repo}",
        release_tag=release["tag_name"],
        install_mode="install-components",
        install_command=None,
        verify_commands=config["verifyCommands"],
        profile=profile_id,
    )

    component_count = 0
    assets = release_asset_map(release)
    for arch in ARCHITECTURES:
        component_index_asset = component_index_asset_name(asset_prefix, arch)
        if component_index_asset in assets:
            component_ids = attach_component_index(
                manifest,
                entry["id"],
                arch,
                release_repo,
                release["tag_name"],
                assets,
                assets[component_index_asset],
                token,
            )
            set_arch_component_refs(manifest, entry, arch, component_ids)
            component_count += len(component_ids)

    if component_count == 0:
        print(f"Skipping {profile_id}: no component indexes found.")
        return

    manifest.setdefault("entries", []).append(entry)
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
    extension_tag_prefix = "pystudio-python-extensions-r"
    if extension_tag and not extension_tag.startswith(extension_tag_prefix):
        print(
            "Warning: ignoring extension tag "
            f"{extension_tag!r}; expected prefix {extension_tag_prefix!r}."
        )
        extension_tag = ""

    metadata = fetch_json(EXTENSIONS_METADATA_URL, token)
    release = latest_release(
        EXTENSIONS_REPO,
        extension_tag_prefix,
        token,
        explicit_tag=extension_tag,
    )
    if not release:
        print("Skipping Python extensions: no release found.")
        return

    assets = release_asset_map(release)
    for meta in metadata.get("profiles", []):
        profile_id = meta["id"]
        try:
            packages = fetch_extension_packages(meta["packageFile"], token)
        except RuntimeError as exc:
            packages = []
            print(f"Warning: no package list for {profile_id}: {exc}")

        entry = base_entry(
            entry_id=profile_id,
            kind="bundle",
            group=meta.get("group", "python-extension"),
            title=meta.get("title", profile_id),
            description=meta.get("description", ""),
            packages=packages,
            commands=profile_commands(profile_id, meta),
            source_repository=f"https://github.com/{EXTENSIONS_REPO}",
            release_repository=f"https://github.com/{EXTENSIONS_REPO}",
            release_tag=release["tag_name"],
            install_mode="install-components",
            install_command=None,
            verify_commands=meta.get("verifyCommands", []),
            profile=profile_id,
        )

        component_count = 0
        asset_prefix = f"pystudio-python-extensions-{profile_id}"
        for arch in ARCHITECTURES:
            index_name = component_index_asset_name(asset_prefix, arch)
            if index_name not in assets:
                continue
            component_ids = attach_component_index(
                manifest,
                entry["id"],
                arch,
                EXTENSIONS_REPO,
                release["tag_name"],
                assets,
                assets[index_name],
                token,
            )
            set_arch_component_refs(manifest, entry, arch, component_ids)
            component_count += len(component_ids)

        if component_count == 0:
            continue
        if meta.get("heavy"):
            entry["heavy"] = True
        manifest.setdefault("entries", []).append(entry)
        print(f"Updated extension profile {profile_id}: {', '.join(entry['availableArchitectures'])}.")


def asset_prefix_from_debs_asset(asset_name: str, arch: str) -> str:
    suffix = f"-debs-{arch}.tar.gz"
    if not asset_name.endswith(suffix):
        return ""
    return asset_name[: -len(suffix)]


def existing_entry_ids(manifest: dict[str, Any]) -> set[str]:
    return {str(entry.get("id", "")) for entry in manifest.get("entries", [])}


def upsert_migration_plan_profiles(
    manifest: dict[str, Any],
    token: str,
    plan_path: Path,
) -> None:
    if not plan_path.exists():
        return

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if int(plan.get("schemaVersion", 0)) != 1:
        raise RuntimeError(f"unsupported migration plan schema: {plan.get('schemaVersion')}")

    release_cache: dict[tuple[str, str], dict[str, Any] | None] = {}
    for meta in plan.get("entries", []):
        entry_id = str(meta.get("id", ""))
        if not entry_id or entry_id in existing_entry_ids(manifest):
            continue

        release_meta = meta.get("release", {})
        release_repo = repo_slug_from_url(str(release_meta.get("repository", "")))
        release_tag = str(release_meta.get("tag", ""))
        if not release_repo or not release_tag:
            continue

        cache_key = (release_repo, release_tag)
        if cache_key not in release_cache:
            release_cache[cache_key] = latest_release(release_repo, "", token, explicit_tag=release_tag)
        release = release_cache[cache_key]
        if not release:
            continue

        entry = base_entry(
            entry_id=entry_id,
            kind="bundle",
            group=str(meta.get("group", "runtime")),
            title=str(meta.get("title", entry_id)),
            description=str(meta.get("description", "")),
            packages=unique_strings([str(item) for item in meta.get("packages", [])]),
            commands=unique_strings([str(item) for item in meta.get("commands", [])]),
            source_repository=str(meta.get("source", {}).get("repository", f"https://github.com/{release_repo}")),
            release_repository=f"https://github.com/{release_repo}",
            release_tag=release_tag,
            install_mode="install-components",
            install_command=None,
            verify_commands=[str(item) for item in meta.get("install", {}).get("verifyCommands", [])],
            profile=str(meta.get("profile") or entry_id),
        )

        component_count = 0
        assets = release_asset_map(release)
        deb_assets = meta.get("debianPackageAssets", {})
        for arch in ARCHITECTURES:
            artifact_prefix = asset_prefix_from_debs_asset(str(deb_assets.get(arch, "")), arch)
            if not artifact_prefix:
                continue
            index_name = component_index_asset_name(artifact_prefix, arch)
            if index_name not in assets:
                continue
            component_ids = attach_component_index(
                manifest,
                entry["id"],
                arch,
                release_repo,
                release_tag,
                assets,
                assets[index_name],
                token,
            )
            set_arch_component_refs(manifest, entry, arch, component_ids)
            component_count += len(component_ids)

        if component_count == 0:
            print(f"Skipping migrated profile {entry_id}: no component indexes found.")
            continue
        if meta.get("heavy"):
            entry["heavy"] = True
        manifest.setdefault("entries", []).append(entry)
        print(f"Updated migrated profile {entry_id}: {', '.join(entry['availableArchitectures'])}.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="runtime-packages.json")
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--extension-tag", default="")
    parser.add_argument("--migration-plan", type=Path, default=DEFAULT_MIGRATION_PLAN)
    parser.add_argument("--skip-bootstraps", action="store_true")
    parser.add_argument("--skip-core", action="store_true")
    parser.add_argument("--skip-extensions", action="store_true")
    parser.add_argument("--skip-migration-plan", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(args.manifest)
    manifest: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": dt.date.today().isoformat(),
        "packageName": PYSTUDIO_PACKAGE_NAME,
        "architectures": ARCHITECTURES,
        "packageManagement": {
            "mode": "component-deb-v2",
            "componentKey": "id",
            "entryKey": "entries",
            "resolver": (
                "select an entry for the device architecture, install its componentRefs, "
                "then recursively resolve dependencyNames through componentPackages[arch]"
            ),
            "bootstrapMode": "extract the selected rootfs before installing component bundles",
        },
        "components": {},
        "componentPackages": {arch: {} for arch in ARCHITECTURES},
        "entries": [],
    }

    if not args.skip_bootstraps:
        upsert_bootstraps(manifest, args.github_token)

    if not args.skip_core:
        for profile_id, config in CORE_PROFILES.items():
            upsert_core_profile(manifest, profile_id, config, args.github_token)

    if not args.skip_extensions:
        upsert_extension_profiles(manifest, args.github_token, args.extension_tag)

    if not args.skip_migration_plan:
        upsert_migration_plan_profiles(manifest, args.github_token, args.migration_plan)

    ordered_entries(manifest)
    validate_manifest(manifest)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"Wrote {path} with {len(manifest.get('entries', []))} entries "
        f"and {len(manifest.get('components', {}))} components."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
