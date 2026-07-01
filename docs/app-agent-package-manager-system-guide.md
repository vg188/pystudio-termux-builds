# PyStudio App Agent Package Manager System Guide

This guide is for the agent implementing the PyStudio app package manager.
The app is not released yet, so implement the schema 5 package model directly.
Do not add compatibility for old large toolchain archives.

## Current Public Manifests

Use these URLs as the app's default manifest sources:

- China entry: `https://gitee.com/yourba/pystudio-termux-builds/raw/main/runtime-packages.json`
- GitHub authority: `https://raw.githubusercontent.com/vg188/pystudio-termux-builds/main/runtime-packages.json`
- Gitee mirror status: `https://gitee.com/yourba/pystudio-termux-builds/raw/main/mirror-status.json`

Gitee is a lightweight manifest mirror only. It does not host `.deb`,
bootstrap, or tarball assets. In the Gitee manifest, ModelScope mirrors are
preferred for large files and GitHub Release assets are fallback mirrors.

`mirror-status.json` is operational status, not the install source of truth.
If it says `syncedThisRun = false`, still try declared mirrors in priority
order and fall back per URL/checksum failure.

## Product Goal

Build an in-app package manager that behaves like a small Termux/TUR-style
package installer:

- show searchable bootstrap and package-set entries;
- install bootstrap archives by extraction;
- install optional runtimes and tools from apt-style `Packages.xz` indexes;
- resolve `Depends` and `Pre-Depends`;
- reuse already installed `.deb` packages;
- cache downloads by checksum;
- prefer PyStudio-built packages over official/external Termux packages.

The app should not download opaque toolchain tarballs. Toolchain entries are
indexes over normal `.deb` packages.

## Install Roots

Use the app package name from the manifest unless the app build intentionally
overrides it:

```text
PREFIX=/data/data/com.vchangxiao.pystudio/files/usr
HOME=/data/data/com.vchangxiao.pystudio/files/home
PATH=$PREFIX/bin:$PATH
LD_LIBRARY_PATH=$PREFIX/lib
```

Recommended local package manager paths:

```text
$PREFIX/var/lib/pystudio/pkg/state.json
$PREFIX/var/lib/pystudio/pkg/installed-packages.json
$PREFIX/var/cache/pystudio/manifests/
$PREFIX/var/cache/pystudio/repos/
$PREFIX/var/cache/pystudio/debs/
$PREFIX/var/log/pystudio/package-manager.log
```

Keep cache files outside user project directories.

## Data Model

Implement these app-side records.

`ManifestState`:

- `schemaVersion`
- `generatedAt`
- `packageName`
- `manifestUrl`
- `fetchedAt`
- `sha256`

`CatalogEntry`:

- `id`
- `kind`: `bootstrap` or `package-set`
- `group`
- `profile`
- `title`
- `description`
- `packages[]`
- `commands[]`
- `availableArchitectures[]`
- `repositoryRefs[arch]` for package sets
- `artifacts[arch][]` for bootstraps

`RepositoryRef`:

- `id`
- `profile`
- `architecture`
- `version`
- `indexUrl`
- `mirrors[]`
- `packagePools[]`

`PackageRecord` from `Packages.xz`:

- `Package`
- `Version`
- `Architecture`
- `Filename`
- `Size`
- `SHA256`
- `Depends`
- `Pre-Depends`
- `Description`
- optional `PyStudio-Commands`

`InstalledPackage`:

- `package`
- `version`
- `architecture`
- `sha256`
- `filename`
- `repositoryId`
- `installedAt`
- `files[]` if available from `dpkg -L`

Use `package + version + architecture + sha256` as the strongest installed
identity. Treat `Architecture = all` as reusable on all device ABIs.

## Manifest Fetch Policy

1. Fetch `runtime-packages.json` from Gitee first for China builds.
2. Validate JSON and require `schemaVersion = 5`.
3. If Gitee fetch fails or the JSON is invalid, fetch GitHub raw.
4. Cache the successful manifest with SHA256 and timestamp.
5. Use cached manifest only when the network is unavailable or the user opens
   the package screen offline.

Do not block installs solely because `mirror-status.json` is stale. It is only
for diagnostics.

## Catalog UI

Build the download window from `entries[]`.

Search fields:

- `title`
- `description`
- `group`
- `profile`
- `packages[]`
- `commands[]`
- parsed package names from the selected `Packages.xz`
- `PyStudio-Commands` from parsed package stanzas when present

Expected search examples:

- `python`, `pip`, `openssl`, `xz` finds Python / Pip.
- `node`, `npm`, `npx` finds Node.js / npm.
- `cmake`, `make`, `clang`, `pkg-config` finds C/C++ or pip build tools.
- `pyright`, `ruff`, `clangd`, `lldb`, `debugpy` finds editor/debug tools.
- `xmllint`, `curl`, `sqlite3`, `qhull`, `fc-cache` finds native libraries.

Display for each entry:

- title and short description;
- commands provided;
- package names included;
- available architectures;
- installed/partially installed/not installed state;
- estimated download size after dependency resolution when known.

## Bootstrap Install Flow

1. Detect device ABI: `aarch64`, `arm`, `i686`, or `x86_64`.
2. Select a `kind = bootstrap` entry with `availableArchitectures` containing
   the ABI.
3. Prefer artifact mirrors by ascending `priority`.
4. Download the `role = rootfs` artifact.
5. Verify `sha256` and `size` when present.
6. Extract into `$PREFIX` or the bootstrap target root.
7. Initialize `$HOME`, `$PREFIX`, shell profile, and base cache directories.
8. Verify bootstrap commands such as `sh`, `dpkg`, `pkg`, and `proot`.
9. Persist bootstrap install state separately from `.deb` package state.

Bootstrap extraction should be idempotent. If a prior bootstrap exists, either
repair missing files or require explicit reinstall confirmation.

## Package Set Install Flow

Use this flow for every `kind = package-set` entry.

1. Detect ABI.
2. Read `entry.repositoryRefs[abi]`.
3. Load `manifest.repositories[repoId]`.
4. Fetch the best `Packages.xz` index.
5. Parse package stanzas.
6. Start with `entry.packages[]`, or a user-selected explicit package.
7. Resolve dependencies recursively.
8. Skip installed package identities.
9. Download missing `.deb` files.
10. Verify `Size` and `SHA256`.
11. Install with `dpkg`.
12. Run `dpkg --configure -a`.
13. Run `entry.install.verifyCommands`.
14. Update app-side installed state from `dpkg` output and the app resolver.

Never assume `entry.packages[]` is already dependency-complete. Always resolve
against `Packages.xz`.

## Mirror Selection

For Gitee manifest users, repository mirrors should already put ModelScope
first. For GitHub manifest users, GitHub may be first. The app should still use
a general mirror scorer:

1. lower `priority` wins;
2. prefer `region = CN` when the user chooses China acceleration;
3. prefer mirrors that recently succeeded;
4. temporarily demote mirrors that returned 404, timeout, or checksum failure;
5. always keep GitHub Release URLs as fallback.

For repository indexes, use `mirror.indexUrl`.

For `.deb` files, prefer `repository.packagePools[]` when available:

- `Architecture = all` uses the `all` pool;
- device ABI packages use the matching ABI pool;
- sort pool mirrors by priority and health;
- construct the download URL as `pool.baseUrl + basename(Filename)`.

If no package pool is declared, fall back to `mirror.baseUrl + Filename`.

## Packages.xz Parser

Implement a Debian stanza parser instead of ad hoc line splitting.

Rules:

- stanzas are separated by blank lines;
- continuation lines begin with one space;
- fields are `Key: value`;
- preserve unknown fields;
- parse `Depends` and `Pre-Depends`;
- for alternatives like `foo | bar`, choose the first available package in the
  same index unless the user already installed another valid alternative.

Dependency version constraints can be parsed but may initially be treated as
required metadata for diagnostics if all packages come from one coherent
repository index. Keep the parser ready for stricter checks later.

## Dependency Resolver

Resolver input:

- requested package names;
- parsed package map;
- installed package map;
- target ABI.

Resolver output:

- ordered package list;
- skipped installed packages;
- missing package names;
- conflicts or unsupported architectures;
- total download size.

Algorithm:

1. Index packages by `Package`, then choose the best candidate for the target
   ABI. Prefer exact ABI over `all`.
2. DFS or queue through `Pre-Depends` before `Depends`.
3. Detect cycles and keep the first resolved instance.
4. For alternatives, select the first package available and not conflicting.
5. Topologically sort so dependencies are installed before dependents.
6. Exclude installed packages with the same package/version/architecture or
   same package/version/all identity.
7. Return missing dependency names with the repository ID and entry ID.

Do not continue with a partial install when a required dependency is missing,
unless the user explicitly enables a repair/debug mode.

## Download Manager

Required behavior:

- resume partial downloads;
- show progress, speed, transferred bytes, total bytes, and current file;
- write to `*.part` and rename atomically after checksum verification;
- verify SHA256 before install;
- retry network failures with backoff;
- avoid redownloading cached files with matching SHA256;
- keep one download lock per SHA256 or URL.

Cache key:

```text
$PREFIX/var/cache/pystudio/debs/<sha256>/<filename>
```

If a URL returns 404, mark only that mirror URL as failed and try the next
mirror. Do not mark the package itself as unavailable until all mirrors fail.

## Dpkg Installer

Install only verified local `.deb` files.

Recommended commands:

```sh
dpkg --force-depends -i "$deb"
dpkg --configure -a
```

Run commands with:

- `PREFIX` set;
- `HOME` set;
- `PATH=$PREFIX/bin:$PATH`;
- `LD_LIBRARY_PATH=$PREFIX/lib`.

Capture stdout/stderr to the app log. Show a concise user error, but keep the
full diagnostic file path.

After install, refresh installed state from:

```sh
dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n'
```

When `dpkg` fails, keep downloaded `.deb` files in cache and allow retry after
the user installs missing prerequisites or after the manifest updates.

## Official Source Policy

Default mode must use PyStudio-built packages only. They are compiled for the
app prefix and package name.

Official Termux or third-party sources are an explicit external-source mode.
Warn that external packages may contain incompatible paths such as `/usr/bin`,
`/data/data/com.termux/files/usr`, or scripts that assume another package name.

Do not mix official packages into normal PyStudio package-set installs.

## Path Normalization

PyStudio-built `.deb` packages should not need broad path rewriting.

Still implement a small post-install normalizer for files created by user-level
tools such as `npm install` and `pip install`:

- scan only newly created executable files;
- scan `$PREFIX/bin`;
- scan `$PREFIX/lib/node_modules/.bin`;
- scan project `node_modules/.bin`;
- scan configured user bin directories;
- replace `/usr/bin/env` with `$PREFIX/bin/env` when needed;
- replace hardcoded `/usr/bin/node`, `/usr/bin/python`, and `/bin/sh` only when
  they point outside the app prefix;
- keep the operation quiet and log details to app diagnostics.

Do not print large shell bodies into the interactive terminal.

## Package State And Reuse

Before downloading, compare resolver output with local installed state.

Skip package downloads when:

- same package/version/architecture is already installed;
- same package/version/all is installed for an `all` package;
- matching SHA256 exists in cache.

Do not skip a package only because the file name matches. Use version,
architecture, and SHA256.

Support repair actions:

- reinstall selected package;
- redownload selected package;
- clear failed mirror health;
- rebuild local package state from `dpkg-query`;
- verify installed entry commands.

## UI States

Each catalog entry should expose:

- `Available`: manifest entry is valid for current ABI.
- `Installed`: every requested package and dependency is installed.
- `Partial`: some packages installed, others missing.
- `Update available`: manifest package version differs from installed version.
- `Unavailable`: no repository or bootstrap artifact for current ABI.
- `Mirror degraded`: preferred mirror failed but fallback exists.
- `Broken`: dependency resolution or verification failed.

The package details screen should show requested packages, resolved
dependencies, commands provided, mirrors, total download size, and install log
location.

## Verification Commands

After an install, run `entry.install.verifyCommands` when present. Also use
entry command probes for UI health.

Recommended probes:

- Python: `python3 --version`, `python3 -m pip --version`
- Node.js: `node --version`, `npm --version`, `npx --version`
- PRoot: `proot --version`
- Git: `git --version`, `ssh -V`
- C/C++: `clang --version`, `cmake --version`, `make --version`
- LSP/debug: `pyright --version`, `ruff --version`, `lldb --version`

Run probes with timeouts and show failures as diagnostics, not as crashes.

## Minimum Tests For The App Agent

Implement tests or scripted checks for:

- manifest fetch fallback from Gitee to GitHub;
- schema 5 validation;
- ABI selection;
- Debian stanza parsing with continuation lines;
- dependency parsing with alternatives;
- dependency cycle handling;
- package pool URL construction for `all` and ABI packages;
- SHA256 mismatch rejection;
- resume download behavior;
- installed package skip behavior;
- fallback from ModelScope 404 to GitHub;
- bootstrap extraction idempotency;
- `dpkg` failure logging;
- npm shebang normalization for `/usr/bin/env`;
- package search by command name.

## Implementation Order

1. Manifest fetch/cache and schema validation.
2. Catalog UI from `entries[]`.
3. ABI selection and bootstrap installer.
4. `Packages.xz` download and parser.
5. Dependency resolver.
6. Download manager with mirror fallback and SHA256 cache.
7. `dpkg` installer and installed-state database.
8. Entry verification commands.
9. Post-install path normalizer.
10. Repair/debug UI.

Keep each layer independently testable. The app package manager should be able
to resolve and plan an install without touching the filesystem, then execute
the plan in a separate installer step.

