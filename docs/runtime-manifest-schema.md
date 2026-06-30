# Runtime Manifest Schema

`runtime-packages.json` is the app-facing catalog for PyStudio bootstrap
archives and optional package repositories.

## Version 5

Schema version 5 uses a Termux-style package repository model. Bootstrap
archives are still downloaded as rootfs files, but optional runtimes and
toolchains are installed from apt-style repositories containing:

- `dists/pystudio/main/binary-ARCH/Packages`
- `dists/pystudio/main/binary-ARCH/Packages.gz`
- `dists/pystudio/main/binary-ARCH/Packages.xz`
- `pool/main/.../*.deb`

Top-level fields:

```json
{
  "schemaVersion": 5,
  "generatedAt": "2026-06-28",
  "packageName": "com.vchangxiao.pystudio",
  "architectures": ["aarch64", "arm", "i686", "x86_64"],
  "packageManagement": {
    "mode": "apt-repository-v1",
    "distribution": "pystudio",
    "component": "main"
  },
  "manifestMirrors": [],
  "repositories": {},
  "entries": []
}
```

## Entries

`entries[]` is the unified app catalog. Every entry has the same display/search
fields: `title`, `description`, `packages`, and `commands`. A `package-set`
entry is a curated install/search shortcut, not an opaque bundle. The real
installation units are package stanzas in the referenced `Packages.xz` indexes.

Bootstrap entry:

```json
{
  "id": "bootstrap-base",
  "kind": "bootstrap",
  "group": "bootstrap",
  "profile": "base",
  "title": "Base Bootstrap",
  "description": "Minimal PyStudio terminal bootstrap.",
  "packages": ["proot"],
  "commands": ["sh", "bash", "pkg", "dpkg"],
  "install": {
    "mode": "extract-rootfs",
    "verifyCommands": []
  },
  "availableArchitectures": ["aarch64"],
  "artifacts": {
    "aarch64": [
      {
        "role": "rootfs",
        "fileName": "bootstrap-aarch64.tar.xz",
        "format": "tar.xz",
        "downloadUrl": "https://github.com/...",
        "size": 123456,
        "sha256": "..."
      }
    ]
  }
}
```

Package-set entry:

```json
{
  "id": "python",
  "kind": "package-set",
  "group": "runtime",
  "profile": "python",
  "title": "Python / Pip",
  "description": "CPython runtime, pip, and their Termux dependencies.",
  "packages": ["python", "python-pip"],
  "commands": ["python", "python3", "pip", "pip3"],
  "install": {
    "mode": "install-from-package-repository",
    "verifyCommands": ["python3 --version", "pip3 --version"]
  },
  "availableArchitectures": ["aarch64"],
  "repositoryRefs": {
    "aarch64": "repo:python:primary:aarch64:pystudio-python-toolchain-r10:pystudio-python-toolchain"
  }
}
```

## Repositories

`repositories` is keyed by repository ID. A repository is an apt-style package
source for one profile/source/architecture build.

```json
{
  "id": "repo:python:primary:aarch64:pystudio-python-toolchain-r10:pystudio-python-toolchain",
  "kind": "apt-repository",
  "format": "apt-repo-v1",
  "profile": "python",
  "sourceAdapter": "primary",
  "architecture": "aarch64",
  "distribution": "pystudio",
  "component": "main",
  "indexPath": "dists/pystudio/main/binary-aarch64/Packages.xz",
  "packageRoot": "pool/main",
  "version": "r10",
  "index": {
    "role": "package-index",
    "fileName": "pystudio-python-toolchain-apt-repo-v1-aarch64-r10-Packages.xz",
    "format": "xz",
    "downloadUrl": "https://github.com/...",
    "size": 123456
  },
  "mirrors": [
    {
      "id": "github-release-flat",
      "kind": "flat-release-repo",
      "baseUrl": "https://github.com/.../releases/download/...",
      "indexUrl": "https://github.com/.../ARTIFACT-apt-repo-v1-aarch64-r10-Packages.xz",
      "priority": 1
    },
    {
      "id": "modelscope",
      "kind": "flat-package-repo",
      "baseUrl": "https://modelscope.cn/datasets/.../resolve/master/repo/...",
      "indexUrl": "https://modelscope.cn/datasets/.../ARTIFACT-apt-repo-v1-aarch64-r10-Packages.xz",
      "priority": 10,
      "region": "CN"
    }
  ]
}
```

`github-release-flat` stores the `Packages.xz` index and metadata in the main
release. `.deb` files are stored in `packagePools` releases, split by
`Architecture = all` and by target ABI. The index rewrites `Filename` to the
flat `.deb` asset name, so app-side download code should prefer a matching
`packagePools[]` base URL and fall back to `baseUrl + Filename` only for legacy
or emergency cases. ModelScope mirrors expose the same index and pool layout.
Toolchain tarballs are not part of the app-side package model.

## App Install Flow

1. Choose the current ABI from `architectures`.
2. Search `entries[]` by `title`, `description`, `packages`, and `commands`.
3. For `kind = bootstrap`, download the `rootfs` artifact for the ABI and
   extract it into the app prefix.
4. For `kind = package-set`, read `repositoryRefs[abi]` and fetch the referenced
   repository index.
5. Prefer `flat-release-repo` or `flat-package-repo` mirrors by priority and
   download `Packages.xz` from `indexUrl`.
6. For each `.deb`, prefer a matching `packagePools[]` mirror: `Architecture =
   all` uses the `all` pool, otherwise use the current ABI pool. Fall back to
   `baseUrl + Filename` only when no pool is declared.
7. Resolve `Depends` and `Pre-Depends` from the package index, skip already
   installed package/version pairs, verify `SHA256`, and install missing `.deb`
   files with `dpkg`.

Only real downloads use keys ending in `downloadUrl` or `indexUrl`. Gitee is a
manifest-only mirror; it should not be treated as a full package source unless a
future manifest explicitly marks it as one.

## Gitee CN Mirror Index

The GitHub copy of `runtime-packages.json` remains the authority. The Gitee copy
is generated as a China-optimized lightweight entry point:

- Gitee stores only JSON indexes: `runtime-packages.json`,
  `package-assets.json`, `package-indexes.json`, and `mirror-status.json`.
- Gitee does not store `.deb`, bootstrap, or tarball assets.
- The Gitee `runtime-packages.json` rewrites mirror priorities so ModelScope is
  preferred for large files and GitHub release assets remain the fallback.
- Bootstrap artifacts in the Gitee manifest include `mirrors[]`, with
  ModelScope first and GitHub second.
- `mirror-status.json` records the source GitHub manifest, generated files, and
  whether ModelScope was synced in the same workflow run.

App-side download policy for users in mainland China should be:

1. Fetch the Gitee manifest first.
2. Prefer mirrors with `region = "CN"` and the lowest `priority`.
3. Fall back to GitHub mirrors if ModelScope returns 404, times out, or fails
   checksum verification.
