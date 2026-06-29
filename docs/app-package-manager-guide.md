# PyStudio App Package Manager Guide

This guide is for the agent that implements PyStudio's app-side runtime package
manager. The app is not released yet, so implement schema 5 directly.

## Manifest

Fetch `runtime-packages.json` from the preferred manifest mirror. Gitee is a
good first choice in China because it is lightweight and only contains the
manifest.

Current schema:

- `entries[]`: searchable catalog entries for bootstrap archives and package
  sets.
- `repositories`: apt-style package repositories keyed by repository ID.
- `manifestMirrors`: places to fetch the manifest itself.

Supported entry kinds:

- `bootstrap`: initial rootfs archive, installed by extraction.
- `package-set`: curated search/install shortcut. It points to one or more
  apt-style repositories, but the actual install units are package stanzas in
  `Packages.xz` and the `.deb` files under `pool/main`.

## Local State

Store package manager state under the app prefix, for example:

- `$PREFIX/var/lib/pystudio/pkg/installed-packages.json`
- `$PREFIX/var/cache/pystudio/repos/`
- `$PREFIX/var/cache/pystudio/debs/`
- `$PREFIX/var/cache/pystudio/manifests/`

Track package name, version, architecture, SHA256, source repository ID, and
install time. This is enough to skip already installed dependencies across
Python, debug, LSP, Git, and future toolchains.

## Install Bootstrap

1. Detect ABI: `aarch64`, `arm`, `i686`, or `x86_64`.
2. Select a `kind = bootstrap` entry available for the ABI.
3. Download the artifact with `role = rootfs`.
4. Verify `sha256` when present.
5. Extract into the app prefix.
6. Initialize shell environment variables:
   - `PREFIX=/data/data/<package>/files/usr`
   - `HOME=/data/data/<package>/files/home`
   - `PATH=$PREFIX/bin:$PATH`
   - `LD_LIBRARY_PATH=$PREFIX/lib`

## Install Package Set

Use this resolver:

1. Start with `entry.repositoryRefs[arch]`.
2. Load the repository from `manifest.repositories[repoId]`.
3. Prefer `repository.mirrors[]` with `kind = flat-release-repo` or
   `kind = flat-package-repo`, sorted by `priority`.
4. Download `Packages.xz` from `indexUrl`.
5. Parse stanzas in `Packages.xz`.
6. Start with `entry.packages`, or with an explicit package name selected by the
   user from the parsed repository index.
7. Resolve `Depends` and `Pre-Depends`; for alternatives, prefer the first
   package available in the same index.
8. Skip package/version/architecture tuples that are already installed.
9. Download missing `.deb` files using `baseUrl + Filename`.
10. Verify `SHA256` and `Size`.
11. Install with `dpkg --force-depends -i <deb>` in dependency order.
12. Run `dpkg --configure -a`.
13. Run the entry's `install.verifyCommands`.
14. Persist installed package state.

## Download Sources

Recommended behavior:

- Try Gitee for the manifest.
- Try GitHub flat Release package assets first when reachable.
- Try ModelScope flat package mirrors for packages in China.
- Resume partial downloads.
- Show speed and progress.
- Verify SHA256 before install.
- Keep `.deb` cache keyed by SHA256.

Do not silently fall back to official Termux sources unless the user explicitly
opts into an external-source mode. Official packages may contain incompatible
paths for PyStudio's package name.

## Path Compatibility

Prefer PyStudio-built packages. They are built for
`/data/data/com.vchangxiao.pystudio/files/usr` and should not need broad path
rewriting.

For files created by user tools such as `npm install`, run a small post-install
normalizer:

- replace script shebangs using `/usr/bin/env` with `$PREFIX/bin/env`;
- replace hardcoded `/usr/bin/node`, `/usr/bin/python`, and `/bin/sh` when they
  point outside the app prefix;
- only scan newly created executable files under `$PREFIX/bin`,
  `$PREFIX/lib/node_modules/.bin`, project `node_modules/.bin`, and configured
  user bin directories;
- run this normalizer after `npm`, `pip`, and package-set installs.

Do not print the normalizer shell body into the terminal. Run it as an app-side
maintenance task or a small binary/script with quiet logging.

## UI Search

Index these fields for the download window:

- entry `title`;
- entry `description`;
- entry `packages`;
- entry `commands`;
- package names and `PyStudio-Commands` from the active `Packages.xz` index.

Examples:

- `python`, `pip`, `openssl`, `xz` should find Python / Pip.
- `cmake`, `make`, `pkg-config` should find build packages.
- `clangd`, `pyright`, `ruff`, `lldb`, `git`, `ssh` should find editor/debug
  tools.

## Error Handling

When a dependency name is missing from the selected `Packages.xz`, show the
missing package name, repository ID, and selected entry ID.

When `dpkg` fails, keep downloaded files in cache and write a diagnostic log
under `$PREFIX/var/log/pystudio/`. The next install attempt should resume from
the same local cache.
