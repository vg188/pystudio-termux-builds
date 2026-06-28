# Runtime Manifest Schema

`runtime-packages.json` is the app-facing catalog for PyStudio bootstrap
archives and optional runtime components.

## Version 4

Schema version 4 is component-first. Bootstrap archives are still downloaded as
rootfs files, but every optional runtime/toolchain entry is a logical bundle
that references independent `.deb` components. The app package manager installs
only missing components and resolves dependencies through the manifest graph.

Top-level fields:

```json
{
  "schemaVersion": 4,
  "generatedAt": "2026-06-28",
  "packageName": "com.vchangxiao.pystudio",
  "architectures": ["aarch64", "arm", "i686", "x86_64"],
  "packageManagement": {
    "mode": "component-deb-v2",
    "componentKey": "id",
    "entryKey": "entries"
  },
  "entries": [],
  "components": {},
  "componentPackages": {}
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
        "fileName": "com.vchangxiao.pystudio-f-droid-bootstrap-aarch64.tar.xz",
        "format": "tar.xz",
        "downloadUrl": "https://github.com/...",
        "size": 123456,
        "sha256": "..."
      }
    ]
  }
}
```

Bundle entry:

```json
{
  "id": "python",
  "kind": "bundle",
  "group": "runtime",
  "profile": "python",
  "title": "Python / Pip",
  "description": "CPython runtime, pip, and their Termux dependencies.",
  "packages": ["python", "python-pip"],
  "commands": ["python", "python3", "pip", "pip3"],
  "install": {
    "mode": "install-components",
    "verifyCommands": ["python3 --version", "pip3 --version"]
  },
  "availableArchitectures": ["aarch64"],
  "componentRefs": {
    "aarch64": ["deb:aarch64:python:3.12.11-1"]
  }
}
```

## Components

`components` is keyed by component ID. A component is a single downloadable
`.deb` asset.

```json
{
  "id": "deb:aarch64:python:3.12.11-1",
  "kind": "component",
  "format": "deb",
  "package": "python",
  "version": "3.12.11-1",
  "architecture": "aarch64",
  "debArchitecture": "aarch64",
  "commands": ["python", "python3"],
  "dependencyNames": ["libandroid-support", "openssl", "zlib"],
  "dependencies": {
    "depends": "libandroid-support, openssl, zlib",
    "preDepends": "",
    "names": ["libandroid-support", "openssl", "zlib"]
  },
  "artifact": {
    "role": "component-deb",
    "fileName": "python_3.12.11-1_aarch64.deb",
    "assetName": "pystudio-python-toolchain-component-aarch64-python_3.12.11-1_aarch64.deb",
    "format": "deb",
    "downloadUrl": "https://github.com/...",
    "size": 123456,
    "sha256": "..."
  }
}
```

`componentPackages[arch][package]` maps package names to component IDs. The app
uses this table when a selected component declares `dependencyNames`.

## App Install Flow

1. Choose the current ABI from `architectures`.
2. Search `entries[]` by `title`, `description`, `packages`, and `commands`.
3. For `kind = bootstrap`, download the `rootfs` artifact for the ABI and
   extract it into the app prefix.
4. For `kind = bundle`, start with `componentRefs[abi]`.
5. For every selected component, read `dependencyNames` and resolve names
   through `componentPackages[abi]`.
6. Download each missing component `.deb`, verify `sha256` when present, and
   install it into the same prefix.
7. Treat installed package names and component IDs as local state so another
   bundle can reuse already installed components.

Only real downloadable fields are named `downloadUrl`. Mirror scripts rewrite
these URLs to ModelScope-backed URLs while leaving metadata such as
`source.repository` and `release.repository` unchanged.
