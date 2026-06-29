#!/usr/bin/env python3
"""Update PyStudio runtime package manifest from GitHub release assets."""

from __future__ import annotations

import argparse
import datetime as dt
import http.client
import json
import os
from pathlib import Path
import re
import shlex
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


SCHEMA_VERSION = 5
ARCHITECTURES = ["aarch64", "arm", "i686", "x86_64"]
GITHUB_API = "https://api.github.com"
REPO_ROOT = Path(__file__).resolve().parents[2]
PYSTUDIO_PACKAGE_NAME = os.environ.get("PYSTUDIO_PACKAGE_NAME", "com.vchangxiao.pystudio")
BOOTSTRAP_RELEASE_REPO = "vg188/pystudio-termux-builds"
BOOTSTRAP_TAG_PREFIX = "pystudio-bootstrap-profiles-r"
DEFAULT_MIGRATION_PLAN = REPO_ROOT / "migration" / "runtime-packages-v2-components.json"
MODELSCOPE_DATASET = "yourba/pystudio-termux-builds"
MODELSCOPE_REVISION = "master"
MODELSCOPE_RESOLVE_BASE = f"https://modelscope.cn/datasets/{MODELSCOPE_DATASET}/resolve/{MODELSCOPE_REVISION}/"
GITEE_MANIFEST_URL = "https://gitee.com/yourba/pystudio-termux-builds/raw/main/runtime-packages.json"
RELEASE_CACHE: dict[str, list[dict[str, Any]]] = {}
RELEASE_SCAN_PAGES = int(os.environ.get("PYSTUDIO_RELEASE_SCAN_PAGES", "2"))

PROFILE_OVERRIDES: dict[str, dict[str, Any]] = {
    "python": {
        "group": "runtime",
        "title": "Python / Pip",
        "description": "CPython runtime, pip, and their Termux dependencies.",
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
        "verifyCommands": ["python3 --version", "pip3 --version"],
        "release_repo": "vg188/pystudio-python-toolchain",
        "tag_prefix": "pystudio-python-toolchain-r",
        "asset_prefix": "pystudio-python-toolchain",
    },
    "nodejs": {
        "group": "runtime",
        "title": "Node.js / npm",
        "description": "Node.js runtime and npm package manager.",
        "commands": ["node", "npm", "npx"],
        "verifyCommands": ["node --version", "npm --version"],
        "release_repo": "vg188/pystudio-nodejs-toolchain",
        "tag_prefix": "pystudio-nodejs-toolchain-r",
        "asset_prefix": "pystudio-nodejs-toolchain",
    },
    "cpp": {
        "group": "native-toolchain",
        "title": "C/C++ Toolchain",
        "description": "Compiler, sysroot, CMake, Ninja, Make, and pkg-config.",
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
        "verifyCommands": ["clang --version", "cmake --version", "ninja --version"],
        "release_repo": "vg188/pystudio-cpp-toolchain",
        "tag_prefix": "pystudio-cpp-toolchain-r",
        "asset_prefix": "pystudio-cpp-toolchain",
    },
    "tree-sitter": {
        "group": "editor-extension",
        "title": "Tree-sitter Parsers",
        "description": "Tree-sitter CLI, runtime library, and common parser grammars for editor features.",
        "commands": ["tree-sitter"],
        "verifyCommands": ["tree-sitter --version"],
        "release_repo": "vg188/pystudio-tree-sitter-toolchain",
        "tag_prefix": "pystudio-tree-sitter-toolchain-r",
        "asset_prefix": "pystudio-tree-sitter-toolchain",
    },
    "proot": {
        "group": "runtime",
        "title": "PRoot Runtime",
        "description": "Standalone PRoot runtime with Termux-maintained Android compatibility patches.",
        "commands": ["proot", "termux-chroot"],
        "verifyCommands": ["proot --version", "termux-chroot -h"],
    },
    "proot-distro": {
        "group": "runtime",
        "title": "PRoot Distro",
        "description": "Termux proot-distro manager and its runtime helpers for installing Linux distributions.",
        "commands": ["proot-distro"],
        "verifyCommands": ["proot-distro --help"],
    },
    "proot-full": {
        "group": "runtime",
        "title": "Full PRoot Runtime",
        "description": "PRoot, proot-distro, Python/Pip, Git/SSH, and native build tools as a split apt repository.",
        "commands": [
            "proot",
            "termux-chroot",
            "proot-distro",
            "python",
            "python3",
            "pip",
            "pip3",
            "git",
            "ssh",
            "clang",
            "clang++",
            "make",
            "cmake",
            "ninja",
            "pkg-config",
        ],
        "verifyCommands": [
            "proot --version",
            "proot-distro --help",
            "python3 --version",
            "git --version",
            "clang --version",
        ],
    },
    "node-build-core": {
        "group": "npm-toolchain",
        "title": "Node.js Native Build Core",
        "description": "Build tools and native headers for npm packages that need source compilation.",
        "commands": ["node", "npm", "npx", "python", "python3", "pip", "pip3", "clang", "make", "cmake", "ninja", "pkg-config"],
        "verifyCommands": ["node --version", "npm --version", "cmake --version", "pkg-config --version"],
        "release_repo": "vg188/pystudio-node-build-core-toolchain",
        "tag_prefix": "pystudio-node-build-core-toolchain-r",
        "asset_prefix": "pystudio-node-build-core-toolchain",
    },
    "python-lsp": {
        "group": "editor-extension",
        "title": "Python LSP",
        "description": "Pyright language server and Ruff linter/formatter for Python editing.",
        "commands": ["python", "python3", "pip", "pip3", "node", "pyright", "pyright-langserver", "ruff"],
        "verifyCommands": ["pyright --version", "ruff --version"],
    },
    "cpp-lsp": {
        "group": "editor-extension",
        "title": "C/C++ LSP",
        "description": "clangd plus compilation database generators for C and C++ editing.",
        "commands": ["clang", "clang++", "clangd", "bear", "intercept-build", "compiledb", "python", "python3"],
        "verifyCommands": ["clangd --version", "bear --version", "compiledb --version"],
    },
    "debug-tools": {
        "group": "debug-toolchain",
        "title": "Debug Tools",
        "description": "debugpy plus LLDB and lldb-server for Python and native debugging.",
        "commands": ["python", "python3", "debugpy", "debugpy-adapter", "lldb", "lldb-server"],
        "verifyCommands": ["python -m debugpy --version", "lldb --version", "lldb-server --help"],
    },
    "git": {
        "group": "developer-tool",
        "title": "Git",
        "description": "Git version control with SSH support for clone, fetch, and push workflows.",
        "commands": ["git", "git-upload-pack", "git-receive-pack", "git-shell", "ssh", "scp", "sftp", "ssh-keygen"],
        "verifyCommands": ["git --version", "ssh -V"],
    },
    "pip-build-core": {
        "group": "pip-toolchain",
        "title": "Pip Build Core",
        "description": "Pip, compilers, make, CMake, Ninja, pkg-config, pybind11, and common native headers.",
        "commands": ["python", "python3", "pip", "pip3", "make", "cmake", "ctest", "cpack", "ninja", "pkg-config", "pkgconf", "pybind11-config", "openssl", "xmllint", "xmlcatalog", "xsltproc"],
        "verifyCommands": ["python3 -m pip --version", "make --version", "cmake --version", "pkg-config --version"],
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
        except (urllib.error.URLError, http.client.IncompleteRead):
            if attempt == 5:
                raise
            time.sleep(attempt * 3)
    raise RuntimeError(f"GET {url} failed unexpectedly")


def repo_slug_from_url(value: str) -> str:
    prefix = "https://github.com/"
    if value.startswith(prefix):
        value = value[len(prefix) :]
    return value.removesuffix(".git").strip("/")


def release_number(tag: str, prefix: str) -> int:
    match = re.fullmatch(re.escape(prefix) + r"(\d+)", tag)
    return int(match.group(1)) if match else -1


def version_from_release_tag(tag: str) -> str:
    match = re.search(r"(r\d+)$", tag)
    if match:
        return match.group(1)
    return safe_id_part(tag)


def releases_for_repo(repo: str, token: str) -> list[dict[str, Any]]:
    if repo in RELEASE_CACHE:
        return RELEASE_CACHE[repo]
    owner, name = repo.split("/", 1)
    releases: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = fetch_json(f"{GITHUB_API}/repos/{owner}/{name}/releases?per_page=100&page={page}", token)
        if not batch:
            break
        releases.extend(batch)
        if len(batch) < 100 or page >= RELEASE_SCAN_PAGES:
            break
        page += 1
    RELEASE_CACHE[repo] = releases
    return releases


def latest_release(repo: str, tag_prefix: str, token: str, explicit_tag: str = "") -> dict[str, Any] | None:
    owner, name = repo.split("/", 1)
    if explicit_tag:
        url = f"{GITHUB_API}/repos/{owner}/{name}/releases/tags/{urllib.parse.quote(explicit_tag, safe='')}"
        try:
            return fetch_json(url, token)
        except RuntimeError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise

    releases = releases_for_repo(repo, token)
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


def flat_index_asset_info(asset_prefix: str, arch: str, name: str) -> dict[str, str] | None:
    pattern = re.compile(rf"^{re.escape(asset_prefix)}-apt-repo-v(?P<formatVersion>\d+)-{re.escape(arch)}-(?P<version>.+)-Packages\.xz$")
    match = pattern.fullmatch(name)
    return match.groupdict() if match else None


def release_has_flat_index(release: dict[str, Any], asset_prefix: str) -> bool:
    return any(
        str(asset.get("name", "")).startswith(asset_prefix)
        and str(asset.get("name", "")).endswith("-Packages.xz")
        for asset in release.get("assets", [])
    )


def latest_release_with_flat_index(repo: str, tag_prefix: str, asset_prefix: str, token: str) -> dict[str, Any] | None:
    releases = releases_for_repo(repo, token)
    candidates = []
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        if not release.get("tag_name", "").startswith(tag_prefix):
            continue
        if release_has_flat_index(release, asset_prefix):
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
    for suffix in (".tar.gz", ".tar.xz", ".txt", ".json", ".sha256"):
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


def safe_id_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.+-]+", "-", value).strip("-") or "x"


def modelscope_base_url(release_repo: str, release_tag: str, asset_prefix: str, arch: str) -> str:
    path = f"repo/{release_repo}/{release_tag}/{asset_prefix}/{arch}/"
    return urllib.parse.urljoin(MODELSCOPE_RESOLVE_BASE, urllib.parse.quote(path, safe="/"))


def github_release_base_url(release_repo: str, release_tag: str) -> str:
    return f"https://github.com/{release_repo}/releases/download/{urllib.parse.quote(release_tag, safe='')}/"


def pool_release_tag(source_tag: str, pool_arch: str) -> str:
    version = version_from_release_tag(source_tag)
    base = source_tag[: -len(version)].rstrip("-") if source_tag.endswith(version) else source_tag
    return f"{base}-pool-{pool_arch}-{version}"


def modelscope_pool_base_url(release_repo: str, pool_tag: str, pool_arch: str) -> str:
    path = f"pool/{release_repo}/{pool_tag}/{pool_arch}/"
    return urllib.parse.urljoin(MODELSCOPE_RESOLVE_BASE, urllib.parse.quote(path, safe="/"))


def package_pool_entries(release_repo: str, source_tag: str, arch: str) -> list[dict[str, Any]]:
    if not source_tag:
        return []
    entries: list[dict[str, Any]] = []
    for pool_arch in unique_strings(["all", arch]):
        tag = pool_release_tag(source_tag, pool_arch)
        entries.append(
            {
                "id": f"github-release-pool-{pool_arch}",
                "kind": "flat-release-pool",
                "architecture": pool_arch,
                "baseUrl": github_release_base_url(release_repo, tag),
                "release": {
                    "repository": f"https://github.com/{release_repo}",
                    "tag": tag,
                },
                "priority": 1,
            }
        )
        entries.append(
            {
                "id": f"modelscope-pool-{pool_arch}",
                "kind": "flat-package-pool",
                "architecture": pool_arch,
                "baseUrl": modelscope_pool_base_url(release_repo, tag, pool_arch),
                "priority": 10,
                "region": "CN",
            }
        )
    return entries


def repository_from_flat_index(
    *,
    release_repo: str,
    release_tag: str,
    asset_prefix: str,
    arch: str,
    index_asset: dict[str, Any],
    metadata_asset: dict[str, Any] | None,
    profile: str,
    source_adapter: str,
    package_pool_source_tag: str = "",
) -> dict[str, Any]:
    info = flat_index_asset_info(asset_prefix, arch, str(index_asset["name"]))
    if not info:
        raise RuntimeError(f"invalid flat package index name: {index_asset['name']}")
    version = info["version"]
    index_path = f"dists/pystudio/main/binary-{arch}/Packages.xz"
    base_url = modelscope_base_url(release_repo, release_tag, asset_prefix, arch)
    release_base = github_release_base_url(release_repo, release_tag)
    repo_id = "repo:" + ":".join(
        [
            safe_id_part(profile),
            safe_id_part(source_adapter),
            arch,
            safe_id_part(release_tag),
            safe_id_part(asset_prefix),
        ]
    )
    repository: dict[str, Any] = {
        "id": repo_id,
        "kind": "apt-repository",
        "format": "apt-repo-v1",
        "transport": "flat-release-assets",
        "profile": profile,
        "sourceAdapter": source_adapter,
        "architecture": arch,
        "distribution": "pystudio",
        "component": "main",
        "binaryPath": f"dists/pystudio/main/binary-{arch}",
        "indexPath": index_path,
        "packageRoot": "pool/main",
        "version": version,
        "release": {
            "repository": f"https://github.com/{release_repo}",
            "tag": release_tag,
        },
        "index": artifact_from_asset("package-index", index_asset),
        "mirrors": [
            {
                "id": "github-release-flat",
                "kind": "flat-release-repo",
                "baseUrl": release_base,
                "indexUrl": urllib.parse.urljoin(release_base, str(index_asset["name"])),
                "priority": 1,
            },
            {
                "id": "modelscope",
                "kind": "flat-package-repo",
                "baseUrl": base_url,
                "indexUrl": urllib.parse.urljoin(base_url, str(index_asset["name"])),
                "priority": 10,
                "region": "CN",
            },
        ],
    }
    if metadata_asset:
        repository["metadata"] = artifact_from_asset("apt-repo-metadata", metadata_asset)
    pools = package_pool_entries(release_repo, package_pool_source_tag, arch)
    if pools:
        repository["packagePools"] = pools
    return repository


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


def package_list_from_text(value: str) -> list[str]:
    return unique_strings([part for part in re.split(r"[\s,]+", value) if part])


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


def profile_metadata(profile_id: str, env: dict[str, str] | None = None, migration_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    override = PROFILE_OVERRIDES.get(profile_id, {})
    env = env or {}
    migration_meta = migration_meta or {}
    title = str(migration_meta.get("title") or override.get("title") or env.get("PROFILE_NAME") or profile_id.replace("-", " ").title())
    packages = migration_meta.get("packages") or package_list_from_text(env.get("DEFAULT_PACKAGES", ""))
    verify_commands = migration_meta.get("install", {}).get("verifyCommands") or override.get("verifyCommands", [])
    commands = migration_meta.get("commands") or override.get("commands") or command_names_from_verify([str(item) for item in verify_commands])
    return {
        "id": profile_id,
        "group": str(migration_meta.get("group") or override.get("group") or "runtime"),
        "title": title,
        "description": str(
            migration_meta.get("description")
            or override.get("description")
            or f"{title} packages for PyStudio."
        ),
        "packages": unique_strings([str(item) for item in packages]),
        "commands": unique_strings([str(item) for item in commands]),
        "verifyCommands": [str(item) for item in verify_commands],
        "heavy": bool(migration_meta.get("heavy", False)),
    }


def release_configs_for_profile(profile_id: str) -> list[dict[str, str]]:
    override = PROFILE_OVERRIDES.get(profile_id, {})
    release_repo = str(override.get("release_repo") or "vg188/pystudio-termux-builds")
    tag_prefix = str(override.get("tag_prefix") or "pystudio-toolchains-r")
    if override.get("asset_prefix"):
        return [
            {
                "release_repo": release_repo,
                "tag_prefix": tag_prefix,
                "asset_prefix": str(override["asset_prefix"]),
                "source_adapter": "primary",
            }
        ]
    return [
        {
            "release_repo": release_repo,
            "tag_prefix": tag_prefix,
            "asset_prefix": f"pystudio-{profile_id}-toolchain-{source_adapter}",
            "source_adapter": source_adapter,
        }
        for source_adapter in ("primary", "secondary", "tur")
    ]


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
    verify_commands: list[str],
    profile: str,
) -> dict[str, Any]:
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
        "install": {
            "mode": install_mode,
            "verifyCommands": verify_commands,
        },
        "availableArchitectures": [],
    }
    if kind == "bootstrap":
        entry["artifacts"] = {}
    elif kind == "package-set":
        entry["repositoryRefs"] = {}
    return entry


def set_arch_artifacts(entry: dict[str, Any], arch: str, artifacts: list[dict[str, Any]]) -> None:
    if not artifacts:
        return
    entry["artifacts"][arch] = artifacts
    entry["availableArchitectures"] = sorted(entry["artifacts"], key=ARCHITECTURES.index)
    entry.setdefault("sizeByArch", {})[arch] = sum(int(artifact.get("size", 0)) for artifact in artifacts)


def set_arch_repository_ref(entry: dict[str, Any], arch: str, repository_id: str, index_size: int) -> None:
    if not repository_id:
        return
    entry["repositoryRefs"][arch] = repository_id
    entry["availableArchitectures"] = sorted(entry["repositoryRefs"], key=ARCHITECTURES.index)
    entry.setdefault("indexSizeByArch", {})[arch] = index_size


def repository_refs_for_arch(entry: dict[str, Any], arch: str) -> list[str]:
    refs = entry.get("repositoryRefs", {}).get(arch)
    if isinstance(refs, str):
        return [refs]
    if isinstance(refs, list):
        return unique_strings([str(ref) for ref in refs])
    return []


def set_arch_repository_refs(
    manifest: dict[str, Any],
    entry: dict[str, Any],
    arch: str,
    repository_ids: list[str],
) -> None:
    repository_ids = unique_strings(repository_ids)
    if not repository_ids:
        return
    entry["repositoryRefs"][arch] = repository_ids
    entry["availableArchitectures"] = sorted(entry["repositoryRefs"], key=ARCHITECTURES.index)
    entry.setdefault("indexSizeByArch", {})[arch] = sum(
        int(manifest["repositories"].get(repository_id, {}).get("index", {}).get("size", 0))
        for repository_id in repository_ids
    )


def attach_package_repositories(
    manifest: dict[str, Any],
    entry: dict[str, Any],
    *,
    release_repo: str,
    release: dict[str, Any],
    asset_prefix: str,
    source_adapter: str,
    package_pool_source_tag: str = "",
) -> int:
    assets = release_asset_map(release)
    count = 0
    for arch in ARCHITECTURES:
        matches = [
            asset
            for asset in assets.values()
            if flat_index_asset_info(asset_prefix, arch, str(asset.get("name", "")))
        ]
        if not matches:
            continue
        index_asset = sorted(matches, key=lambda item: str(item["name"]))[-1]
        base_name = str(index_asset["name"])
        metadata_asset = assets.get(base_name[: -len("-Packages.xz")] + ".json")
        repository = repository_from_flat_index(
            release_repo=release_repo,
            release_tag=str(release["tag_name"]),
            asset_prefix=asset_prefix,
            arch=arch,
            index_asset=index_asset,
            metadata_asset=metadata_asset,
            profile=str(entry["profile"]),
            source_adapter=source_adapter,
            package_pool_source_tag=package_pool_source_tag,
        )
        manifest.setdefault("repositories", {})[repository["id"]] = repository
        set_arch_repository_ref(entry, arch, repository["id"], int(index_asset.get("size", 0)))
        count += 1
    return count


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
                "description": BOOTSTRAP_DESCRIPTIONS.get(profile_id, f"PyStudio {profile_name} bootstrap rootfs."),
                "packages": package_list_from_text(env.get("DEFAULT_ADDITIONAL_PACKAGES", "")),
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
            commands=unique_strings(BOOTSTRAP_COMMANDS + BOOTSTRAP_PROFILE_COMMANDS.get(profile_id, [])),
            source_repository=config["source_repo"],
            release_repository=f"https://github.com/{BOOTSTRAP_RELEASE_REPO}",
            release_tag=release["tag_name"],
            install_mode="extract-rootfs",
            verify_commands=[],
            profile=profile_id,
        )

        for arch in ARCHITECTURES:
            arch_artifacts: list[dict[str, Any]] = []
            alias_asset = assets.get(f"{PYSTUDIO_PACKAGE_NAME}-f-droid-{config['alias_suffix']}-{arch}.tar.xz")
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


def upsert_profile_from_release(
    manifest: dict[str, Any],
    *,
    profile_id: str,
    metadata: dict[str, Any],
    release_repo: str,
    release: dict[str, Any],
    asset_prefix: str,
    source_adapter: str,
    source_repository: str = "",
    package_pool_source_tag: str = "",
) -> None:
    entry = base_entry(
        entry_id=profile_id,
        kind="package-set",
        group=metadata["group"],
        title=metadata["title"],
        description=metadata["description"],
        packages=metadata["packages"],
        commands=metadata["commands"],
        source_repository=source_repository or f"https://github.com/{release_repo}",
        release_repository=f"https://github.com/{release_repo}",
        release_tag=release["tag_name"],
        install_mode="install-from-package-repository",
        verify_commands=metadata["verifyCommands"],
        profile=profile_id,
    )
    count = attach_package_repositories(
        manifest,
        entry,
        release_repo=release_repo,
        release=release,
        asset_prefix=asset_prefix,
        source_adapter=source_adapter,
        package_pool_source_tag=package_pool_source_tag,
    )
    if count == 0:
        print(f"Skipping {profile_id}: no flat package indexes found.")
        return
    if metadata.get("heavy"):
        entry["heavy"] = True
    manifest.setdefault("entries", []).append(entry)
    print(f"Updated package set {profile_id}: {', '.join(entry['availableArchitectures'])}.")


def toolchain_profile_envs() -> dict[str, dict[str, str]]:
    profiles: dict[str, dict[str, str]] = {}
    for path in sorted((REPO_ROOT / "profiles" / "toolchains").glob("*.env")):
        env = parse_env_file(path)
        profile_id = env.get("PROFILE_SLUG", path.stem)
        profiles[profile_id] = env
    return profiles


def upsert_latest_toolchain_profiles(manifest: dict[str, Any], token: str) -> None:
    for profile_id, env in toolchain_profile_envs().items():
        selected: tuple[dict[str, str], dict[str, Any]] | None = None
        for config in release_configs_for_profile(profile_id):
            release = latest_release_with_flat_index(
                config["release_repo"],
                config["tag_prefix"],
                config["asset_prefix"],
                token,
            )
            if not release:
                continue
            if not selected or release_number(release["tag_name"], config["tag_prefix"]) > release_number(
                selected[1]["tag_name"],
                selected[0]["tag_prefix"],
            ):
                selected = (config, release)
        if not selected:
            continue
        config, release = selected
        upsert_profile_from_release(
            manifest,
            profile_id=profile_id,
            metadata=profile_metadata(profile_id, env=env),
            release_repo=config["release_repo"],
            release=release,
            asset_prefix=config["asset_prefix"],
            source_adapter=config["source_adapter"],
        )


def existing_entry_ids(manifest: dict[str, Any]) -> set[str]:
    return {str(entry.get("id", "")) for entry in manifest.get("entries", [])}


def remove_manifest_entry(manifest: dict[str, Any], entry_id: str) -> None:
    entries = manifest.get("entries", [])
    keep_entries = []
    repository_ids: set[str] = set()
    for entry in entries:
        if entry.get("id") == entry_id:
            repository_ids.update(str(value) for value in (entry.get("repositoryRefs") or {}).values())
        else:
            keep_entries.append(entry)
    manifest["entries"] = keep_entries
    repositories = manifest.get("repositories", {})
    for repository_id in repository_ids:
        repositories.pop(repository_id, None)


def asset_prefix_from_debs_asset(asset_name: str, arch: str) -> str:
    suffix = f"-debs-{arch}.tar.gz"
    if not asset_name.endswith(suffix):
        return ""
    return asset_name[: -len(suffix)]


def upsert_migration_plan_profiles(manifest: dict[str, Any], token: str, plan_path: Path) -> None:
    if not plan_path.exists():
        return

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if int(plan.get("schemaVersion", 0)) != 1:
        raise RuntimeError(f"unsupported migration plan schema: {plan.get('schemaVersion')}")

    release_cache: dict[tuple[str, str], dict[str, Any] | None] = {}
    for meta in plan.get("entries", []):
        entry_id = str(meta.get("id", ""))
        if not entry_id:
            continue

        release_meta = meta.get("release", {})
        source_release_meta = meta.get("sourceRelease", release_meta)
        release_repo = repo_slug_from_url(str(release_meta.get("repository", "")))
        release_tag = str(release_meta.get("tag", ""))
        source_release_tag = str(source_release_meta.get("tag", ""))
        if not release_repo or not release_tag:
            continue

        cache_key = (release_repo, release_tag)
        if cache_key not in release_cache:
            release_cache[cache_key] = latest_release(release_repo, "", token, explicit_tag=release_tag)
        release = release_cache[cache_key]
        if not release:
            continue

        deb_assets = meta.get("debianPackageAssets", {})
        first_asset = next((str(value) for value in deb_assets.values() if value), "")
        first_arch = next((arch for arch in ARCHITECTURES if str(deb_assets.get(arch, ""))), "")
        asset_prefix = asset_prefix_from_debs_asset(first_asset, first_arch) if first_asset and first_arch else ""
        if not asset_prefix:
            continue

        if entry_id in existing_entry_ids(manifest):
            remove_manifest_entry(manifest, entry_id)

        source_adapter = "secondary" if asset_prefix.endswith("-toolchain-secondary") else "primary"
        upsert_profile_from_release(
            manifest,
            profile_id=entry_id,
            metadata=profile_metadata(entry_id, migration_meta=meta),
            release_repo=release_repo,
            release=release,
            asset_prefix=asset_prefix,
            source_adapter=source_adapter,
            source_repository=str(meta.get("source", {}).get("repository", f"https://github.com/{release_repo}")),
            package_pool_source_tag=source_release_tag if source_release_meta else "",
        )


def entry_order_key(entry_id: str) -> tuple[int, int, str]:
    bootstrap_order = {"bootstrap-base": 0, "bootstrap-python-pip": 1}
    runtime_order = {
        "python": 0,
        "nodejs": 1,
        "proot": 2,
        "proot-distro": 3,
        "proot-full": 4,
        "cpp": 5,
        "tree-sitter": 6,
        "node-build-core": 7,
        "python-lsp": 8,
        "cpp-lsp": 9,
        "debug-tools": 10,
        "git": 11,
    }
    if entry_id in bootstrap_order:
        return (0, bootstrap_order[entry_id], entry_id)
    if entry_id in runtime_order:
        return (1, runtime_order[entry_id], entry_id)
    return (2, 10000, entry_id)


def ordered_entries(manifest: dict[str, Any]) -> None:
    manifest.get("entries", []).sort(key=lambda entry: entry_order_key(entry.get("id", "")))


def validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise RuntimeError(f"manifest schemaVersion must be {SCHEMA_VERSION}")
    if manifest.get("architectures") != ARCHITECTURES:
        raise RuntimeError("manifest architectures are not normalized")
    if not isinstance(manifest.get("entries"), list):
        raise RuntimeError("manifest entries must be a list")
    if not isinstance(manifest.get("repositories"), dict):
        raise RuntimeError("manifest repositories must be an object")

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
        elif kind == "package-set":
            if entry.get("install", {}).get("mode") != "install-from-package-repository":
                raise RuntimeError(f"package set {entry_id} must use install-from-package-repository")
            refs = entry.get("repositoryRefs")
            if not isinstance(refs, dict):
                raise RuntimeError(f"package set {entry_id} missing repositoryRefs")
            if sorted(refs, key=ARCHITECTURES.index) != entry["availableArchitectures"]:
                raise RuntimeError(f"package set {entry_id} has inconsistent architecture lists")
            for arch in refs:
                if arch not in ARCHITECTURES:
                    raise RuntimeError(f"package set {entry_id} has unsupported architecture: {arch}")
                arch_refs = repository_refs_for_arch(entry, arch)
                if not arch_refs:
                    raise RuntimeError(f"package set {entry_id}/{arch} has no repository refs")
                for repo_id in arch_refs:
                    repository = manifest["repositories"].get(repo_id)
                    if not repository:
                        raise RuntimeError(f"package set {entry_id}/{arch} references missing repository {repo_id}")
                    if repository.get("architecture") != arch:
                        raise RuntimeError(f"package set {entry_id}/{arch} references repository for wrong arch")
        else:
            raise RuntimeError(f"manifest entry {entry_id} has unsupported kind: {kind}")

    for repo_id, repository in manifest["repositories"].items():
        if repository.get("id") != repo_id:
            raise RuntimeError(f"repository key mismatch: {repo_id}")
        for key in (
            "kind",
            "format",
            "profile",
            "architecture",
            "distribution",
            "component",
            "indexPath",
            "packageRoot",
            "version",
            "release",
            "index",
            "mirrors",
        ):
            if key not in repository:
                raise RuntimeError(f"repository {repo_id} missing key: {key}")
        if repository["architecture"] not in ARCHITECTURES:
            raise RuntimeError(f"repository {repo_id} has unsupported architecture")
        index = repository["index"]
        for key in ("role", "fileName", "format", "downloadUrl", "size"):
            if key not in index:
                raise RuntimeError(f"repository {repo_id} index missing key: {key}")
        pools = repository.get("packagePools", [])
        if pools and not isinstance(pools, list):
            raise RuntimeError(f"repository {repo_id} packagePools must be a list")
        for pool in pools:
            for key in ("id", "kind", "architecture", "baseUrl", "priority"):
                if key not in pool:
                    raise RuntimeError(f"repository {repo_id} package pool missing key: {key}")
            if pool["architecture"] not in [*ARCHITECTURES, "all"]:
                raise RuntimeError(f"repository {repo_id} has unsupported package pool architecture")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="runtime-packages.json")
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--extension-tag", default="", help="Reserved for compatibility with existing dispatch payloads.")
    parser.add_argument("--migration-plan", type=Path, default=DEFAULT_MIGRATION_PLAN)
    parser.add_argument("--skip-bootstraps", action="store_true")
    parser.add_argument("--skip-toolchains", action="store_true")
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
            "mode": "apt-repository-v1",
            "distribution": "pystudio",
            "component": "main",
            "entryKey": "entries",
            "repositoryKey": "repositories",
            "resolver": (
                "select a package-set entry for the device architecture, fetch one or more "
                "referenced Packages.xz indexes, resolve Depends/Pre-Depends recursively, then "
                "download missing .deb files from the selected flat/full repository mirror"
            ),
            "bootstrapMode": "extract a bootstrap rootfs before installing package-set entries",
        },
        "manifestMirrors": [
            {
                "id": "gitee",
                "kind": "manifest-only",
                "manifestUrl": GITEE_MANIFEST_URL,
                "priority": 5,
                "region": "CN",
            },
            {
                "id": "github",
                "kind": "manifest",
                "manifestUrl": "https://raw.githubusercontent.com/vg188/pystudio-termux-builds/main/runtime-packages.json",
                "priority": 50,
            },
        ],
        "repositories": {},
        "entries": [],
    }

    if not args.skip_bootstraps:
        upsert_bootstraps(manifest, args.github_token)
    if not args.skip_toolchains:
        upsert_latest_toolchain_profiles(manifest, args.github_token)
    if not args.skip_migration_plan:
        upsert_migration_plan_profiles(manifest, args.github_token, args.migration_plan)

    ordered_entries(manifest)
    validate_manifest(manifest)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"Wrote {path} with {len(manifest.get('entries', []))} entries "
        f"and {len(manifest.get('repositories', {}))} package repositories."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
