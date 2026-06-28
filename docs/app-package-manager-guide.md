# PyStudio App Package Manager Guide

This guide is for the agent that implements PyStudio's app-side runtime package
manager. The app is not released yet, so implement schema 4 directly and do not
preserve old `items[]` or apt-repository bundle behavior.

## Manifest

Fetch `runtime-packages.json` from the preferred mirror. The current schema is:

- `entries[]`: searchable user-facing catalog.
- `components`: downloadable `.deb` components keyed by component ID.
- `componentPackages[arch][package]`: package-name lookup for dependency
  resolution.

Supported entry kinds:

- `bootstrap`: initial rootfs archive, installed by extraction.
- `bundle`: logical optional package set, installed by resolving component
  references.

## Local State

Store package manager state under the app prefix, for example:

- `$PREFIX/var/lib/pystudio/pkg/installed-components.json`
- `$PREFIX/var/lib/pystudio/pkg/installed-packages.json`
- `$PREFIX/var/cache/pystudio/components/`
- `$PREFIX/var/cache/pystudio/manifests/`

Track both component IDs and package names. Component IDs prevent duplicate
downloads across bundles. Package names let the app detect upgrades when a
newer component replaces an older package.

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

## Install Bundle

Use this resolver:

1. Start with `entry.componentRefs[arch]`.
2. Pop a component ID from the queue.
3. Skip it if the same component ID is already installed.
4. Read `components[id].dependencyNames`.
5. For each dependency name, look up `componentPackages[arch][name]`.
6. Add missing dependency component IDs to the queue.
7. Download all unresolved components.
8. Verify `sha256`.
9. Install with `dpkg --force-depends -i <component.deb>` in dependency order.
10. Run `dpkg --configure -a`.
11. Run the bundle's `install.verifyCommands`.
12. Persist installed component IDs and package versions.

If multiple component IDs exist for the same package, prefer the newest version
from the selected bundle's release. Keep the resolver deterministic: sort
candidate IDs by version and use the last one only when no explicit component
ID was already selected.

## Download Sources

Use ModelScope-backed `downloadUrl` values when the manifest was fetched from
Gitee/ModelScope. Keep GitHub URLs as fallback. The manifest is intentionally
written so only real downloads use keys ending in `downloadUrl`; mirror scripts
rewrite these fields safely.

Recommended download behavior:

- resume partial downloads;
- show speed and progress;
- verify checksum before install;
- keep a local cache keyed by `sha256`;
- retry GitHub/ModelScope separately before failing the whole bundle.

## Path Compatibility

Prefer PyStudio-built components. They are built for
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
- run this normalizer after `npm`, `pip`, and bundle installs.

Do not print the normalizer shell body into the terminal. Run it as an app-side
maintenance task or a small binary/script with quiet logging.

## UI Search

Index these fields for the download window:

- entry `title`;
- entry `description`;
- entry `packages`;
- entry `commands`;
- component package names and commands for entries selected in the current ABI.

Examples:

- `python`, `pip`, `openssl`, `xz` should find Python / Pip.
- `cmake`, `make`, `pkg-config` should find build bundles.
- `clangd`, `pyright`, `ruff`, `lldb`, `git`, `ssh` should find editor/debug
  tools.

## Error Handling

When a dependency name is missing from `componentPackages[arch]`, show the
missing package name and the selected bundle ID. Do not silently fall back to
official Termux sources unless the user explicitly opts into an external-source
mode, because official packages may contain incompatible paths.

When `dpkg` fails, keep downloaded files in cache and write a diagnostic log
under `$PREFIX/var/log/pystudio/`. The next install attempt should resume from
the same local cache.

## Migration Expectation

Old large `*-debs-ARCH.tar.gz` artifacts are not app install units anymore.
They are CI migration inputs only. After the migration workflow uploads
component assets, the app should install from `components[*].artifact` and
ignore old tar archives entirely.
