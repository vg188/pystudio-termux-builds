# Thin Repository Architecture

Recommended direction: keep `pystudio-termux-builds` as the source of truth and
turn package-specific repositories into thin adapters.

## Goals

- Keep shared scripts, profiles, patch archives, release metadata, and mirror
  logic in one main repository.
- Keep separate child repositories only where separate Actions history or
  releases are useful.
- Support multiple upstream source families without duplicating every
  maintenance change.
- Make the app consume one stable manifest, regardless of which source built a
  package successfully.

## Repository Roles

### Main Repository

`vg188/pystudio-termux-builds`

Owns:

- reusable GitHub workflows
- shared build scripts
- package profiles
- source selection policy
- source patch archives
- runtime manifest generation
- Gitee mirror tooling
- validation

Suggested layout:

```text
profiles/
  bootstrap/
  toolchains/
  python-extensions/
sources/
  primary.env
  secondary.env
  tur.env
patches/
  source-adapters/
scripts/
  ci/
  local/
manifests/
  runtime-packages.json
```

### Thin Child Repositories

Examples:

- `pystudio-python-toolchain`
- `pystudio-nodejs-toolchain`
- `pystudio-cpp-toolchain`
- `pystudio-tree-sitter-toolchain`
- `pystudio-node-build-core-toolchain`
- optional future split repositories for `python-lsp`, `cpp-lsp`,
  `debug-tools`, and `git`

The final target is for each child repo to contain only:

```text
.github/workflows/build.yml
pystudio-build.yml
README.md
```

`pystudio-build.yml` declares the small differences:

```yaml
profile: python
defaultSource: primary
availableSources:
  - primary
  - secondary
  - tur
architectures:
  - aarch64
  - arm
  - i686
  - x86_64
releasePrefix: pystudio-python-toolchain
```

The child workflow calls the main repository reusable workflow or checks out
the main repository scripts at a pinned ref.

Current rule: child repositories must not contain full Termux package trees.
They select a profile/source/architecture and call the reusable workflow in the
main repository.

### Source Repositories

Source repositories are direct forks of their long-term upstreams:

- `vg188/pystudio-termux-source-termux`
  - upstream: `termux/termux-packages`
- `vg188/pystudio-termux-source-pacman`
  - upstream: `termux-pacman/termux-packages`
- `vg188/pystudio-termux-source-tur`
  - upstream: `termux-user-repository/tur`

The active builds clone these managed forks directly. The main repository keeps
patch archives under `patches/source-adapters/` so a source fork can be rebuilt
from clean upstream without losing PyStudio-specific work.

GitHub Actions stay disabled in source repositories. They are source mirrors,
not build executors. Upstream workflows may remain in the tree, but PyStudio
build and release jobs live in the main repository or thin child repositories.

## Multi-Source Strategy

Use full source adapters for normal/fallback builds and supplemental sources
only when explicitly selected. A build run selects exactly one source.

### Source Adapter Model

`sources/primary.env`

```bash
SOURCE_ID=primary
SOURCE_REPO=https://github.com/vg188/pystudio-termux-source-termux.git
SOURCE_UPSTREAM_REPO=https://github.com/termux/termux-packages.git
SOURCE_UPSTREAM_PARENT=termux/termux-packages
SOURCE_PATCH_SET=primary
```

`sources/secondary.env`

```bash
SOURCE_ID=secondary
SOURCE_REPO=https://github.com/vg188/pystudio-termux-source-pacman.git
SOURCE_UPSTREAM_REPO=https://github.com/termux-pacman/termux-packages.git
SOURCE_UPSTREAM_PARENT=termux-pacman/termux-packages
SOURCE_PATCH_SET=secondary
```

`sources/tur.env`

```bash
SOURCE_ID=tur
SOURCE_REPO=https://github.com/vg188/pystudio-termux-source-tur.git
SOURCE_UPSTREAM_REPO=https://github.com/termux-user-repository/tur.git
SOURCE_UPSTREAM_PARENT=termux-user-repository/tur
SOURCE_PATCH_SET=tur
```

The main repo owns the policy:

- Select primary for normal builds.
- Select secondary for fallback or comparison builds when primary fails or when
  a package is known to work better there.
- Promote fixes from secondary back to common patches when they are source
  independent.
- Keep source-specific patches as build-time patch series in the main
  repository.
- Select TUR explicitly because it is not a full package tree replacement.

### Recommended Build Modes

1. `source=primary`

   Fast normal path. This should be the default for routine package builds.

2. `source=secondary`

   Fallback and comparison path. Run when primary fails or for packages with a
   known secondary advantage.

3. `source=tur`

   Explicit supplemental source path. Use only for packages known to exist in
   TUR or for future extension profiles designed around TUR.

## Manifest Policy

The app should not know about all build repositories. It should read one
manifest from the main repository or Gitee mirror.

Manifest schema v2 uses one normalized `items[]` catalog for bootstrap archives
and runtime package sets. Each item includes display/search fields, install
metadata, release metadata, and a per-architecture artifact list:

```json
{
  "id": "python",
  "type": "package-set",
  "group": "runtime",
  "install": {
    "mode": "install-apt-repository",
    "command": "pystudio-install-python"
  },
  "artifacts": {
    "aarch64": [
      {
        "role": "apt-repository",
        "downloadUrl": "..."
      }
    ]
  }
}
```

When ModelScope or Gitee mirroring is enabled, only artifact `downloadUrl`
fields change. Package IDs, source metadata, install commands, and
verification commands should stay the same.

## Migration Plan

1. Keep reusable build logic in `pystudio-termux-builds`.
2. Keep package trees only in direct upstream source forks.
3. Keep toolchain child repositories as workflow/config/README shells.
4. Archive PyStudio source patch series in `patches/source-adapters/`.
5. Add new source families by adding one managed source fork and one
   `sources/<id>.env`.
6. Generate `runtime-packages.json` from build metadata instead of hand-editing
   URLs.
7. Mirror the final manifest and assets to ModelScope/Gitee through CI or the
   local relay script.

## Tradeoff

This design keeps failure isolation and release history from separate child
repositories while removing most duplicated logic. It is less simple than a
single monorepo, but much safer for the current state because each source and
toolchain can still fail independently.
