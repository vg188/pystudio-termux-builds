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
fields: `title`, `description`, `packages`, and `commands`.

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
  "snapshot": {
    "role": "apt-repo-snapshot",
    "fileName": "pystudio-python-toolchain-apt-repo-v1-aarch64-r10.tar.gz",
    "format": "tar.gz",
    "downloadUrl": "https://github.com/...",
    "size": 123456
  },
  "mirrors": [
    {
      "id": "modelscope",
      "kind": "full-repo",
      "baseUrl": "https://modelscope.cn/datasets/.../resolve/master/repo/...",
      "indexUrl": "https://modelscope.cn/datasets/.../Packages.xz",
      "priority": 10,
      "region": "CN"
    },
    {
      "id": "github-snapshot",
      "kind": "snapshot",
      "downloadUrl": "https://github.com/...",
      "priority": 50
    }
  ]
}
```

ModelScope mirrors expose the repository as normal files. GitHub snapshots are
compact release artifacts that the app can download and expand into a local
package cache when a full-file mirror is unavailable.

## App Install Flow

1. Choose the current ABI from `architectures`.
2. Search `entries[]` by `title`, `description`, `packages`, and `commands`.
3. For `kind = bootstrap`, download the `rootfs` artifact for the ABI and
   extract it into the app prefix.
4. For `kind = package-set`, read `repositoryRefs[abi]` and fetch the referenced
   repository index.
5. Prefer a `full-repo` mirror by priority. Download `Packages.xz` from
   `indexUrl`, then download `.deb` files using `baseUrl + Filename`.
6. If no full-file mirror is reachable, download the GitHub `snapshot`, extract
   it to a local cache, and read the same `Packages.xz` from disk.
7. Resolve `Depends` and `Pre-Depends` from the package index, skip already
   installed package/version pairs, verify `SHA256`, and install missing `.deb`
   files with `dpkg`.

Only real downloads use keys ending in `downloadUrl` or `indexUrl`. Gitee is a
manifest-only mirror; it should not be treated as a full package source unless a
future manifest explicitly marks it as one.
