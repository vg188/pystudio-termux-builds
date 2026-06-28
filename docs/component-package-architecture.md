# Component Package Architecture

PyStudio now treats optional runtime downloads as reusable components instead
of large prepacked toolchain archives.

## Goals

- Avoid downloading the same package repeatedly across Python, debug, LSP, and
  C/C++ bundles.
- Keep GitHub builds parallel and small: each matrix job publishes independent
  `.deb` component assets plus an index.
- Let the app package manager resolve package dependencies from one manifest.
- Keep source selection flexible. A build chooses one source adapter at a time,
  while the main repository still manages all source forks and profiles.

## Build Output

Each toolchain build produces:

- `*-component-index-ARCH.json`
- `components/*-component-ARCH-*.deb`

The component index is build metadata. It is consumed by
`scripts/ci/update-runtime-packages.py` and folded into
`runtime-packages.json`. The app does not need to download component indexes at
runtime.

Bootstrap builds remain separate because the app still needs a first rootfs
archive before `.deb` packages can be installed.

## Manifest Model

`runtime-packages.json` has three app-facing structures:

- `entries[]`: searchable catalog entries for bootstrap archives and logical
  optional bundles.
- `components`: downloadable `.deb` packages keyed by stable component ID.
- `componentPackages`: per-architecture lookup table from package name to
  component ID.

Bundle entries do not contain direct download URLs. They contain
`componentRefs[arch]`, and each referenced component contains its own download
URL, checksum, commands, and dependency names.

## App Resolver

The app should keep local install state by package name and component ID.

Recommended resolver:

1. Pick the current ABI.
2. Add the selected bundle's `componentRefs[abi]` to a queue.
3. For each component, skip it if the same component ID or package/version is
   already installed.
4. Add every missing dependency from `dependencyNames` by looking it up in
   `componentPackages[abi]`.
5. Download, verify, and install each missing `.deb`.
6. Run the bundle's `verifyCommands`.

When a package appears in several bundles with the same component ID, it is
downloaded once. If a later bundle references a newer component ID for the same
package, the app can treat it as an upgrade.

## Backfill

Existing `*-debs-ARCH.tar.gz` release assets can be split into component assets
by the `Backfill PyStudio Component Assets` workflow. It uploads component
`.deb` files and component indexes back to the release that originally produced
the old archive, then triggers runtime manifest sync.

The exact schema-2 entries to migrate are captured in
`migration/runtime-packages-v2-components.json`. This avoids guessing from
"latest releases" and keeps the migration scoped to the package sets that were
already visible to the app in the old manifest.

This lets already successful builds be reused without rebuilding everything.
