# Runtime Manifest Schema

`runtime-packages.json` is the app-facing catalog for PyStudio bootstrap
archives and optional runtime package sets.

## Version 2

Schema version 2 intentionally uses one `items[]` list for every downloadable
unit. Item type differences are expressed through `type`, `install.mode`, and
artifact `role` values instead of using separate top-level structures.

Top-level fields:

```json
{
  "schemaVersion": 2,
  "generatedAt": "2026-06-24",
  "packageName": "com.vchangxiao.pystudio",
  "architectures": ["aarch64", "arm", "i686", "x86_64"],
  "items": []
}
```

Each item has the same display and lookup shape:

```json
{
  "id": "python",
  "type": "package-set",
  "group": "runtime",
  "profile": "python",
  "title": "Python / Pip",
  "description": "CPython runtime, pip, and their Termux dependencies.",
  "packages": ["python", "python-pip"],
  "commands": ["python", "python3", "pip", "pip3"],
  "source": {
    "repository": "https://github.com/vg188/pystudio-python-toolchain"
  },
  "release": {
    "repository": "https://github.com/vg188/pystudio-python-toolchain",
    "tag": "pystudio-python-toolchain-r10"
  },
  "install": {
    "mode": "install-apt-repository",
    "command": "pystudio-install-python",
    "verifyCommands": ["python3 --version", "pip3 --version"]
  },
  "availableArchitectures": ["aarch64", "arm", "i686", "x86_64"],
  "artifacts": {
    "aarch64": [
      {
        "role": "apt-repository",
        "fileName": "pystudio-python-toolchain-repo-aarch64.tar.gz",
        "format": "tar.gz",
        "downloadUrl": "https://github.com/...",
        "size": 123456,
        "sha256": "..."
      }
    ]
  }
}
```

## Item Types

- `bootstrap`: a rootfs archive that the app extracts to initialize a terminal.
  It uses `install.mode = extract-rootfs`.
- `package-set`: an optional package repository/bundle that the app can install
  after bootstrap. It uses `install.mode = install-apt-repository`.

## Artifact Roles

Bootstrap items may contain:

- `rootfs`: preferred app-specific bootstrap archive.
- `compat-rootfs`: generic Termux-style bootstrap archive kept for compatibility
  or diagnostics.
- `asset-bundle`: full CI artifact bundle for that bootstrap profile and
  architecture.

Package-set items may contain:

- `apt-repository`: preferred installable apt repository archive.
- `debian-packages`: raw `.deb` bundle for debugging or custom installers.
- `checksums`: release checksum text file.

Only real downloadable artifact fields are named `downloadUrl`. Mirror scripts
rewrite `downloadUrl` values to ModelScope or Gitee-backed URLs while leaving
metadata such as `source.repository` and `release.repository` unchanged.

## App Selection

Recommended app flow:

1. Read `architectures` and choose the current device ABI.
2. Filter `items` where the ABI is in `availableArchitectures`.
3. Search over `title`, `description`, `packages`, and `commands`.
4. For `type = bootstrap`, download the artifact with `role = rootfs`.
5. For `type = package-set`, download the artifact with
   `role = apt-repository`.
6. Verify `sha256` when present, then apply `install.mode`.
