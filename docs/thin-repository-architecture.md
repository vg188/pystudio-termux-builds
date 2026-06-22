# Thin Repository Architecture

Recommended direction: keep `pystudio-termux-builds` as the source of truth and
turn package-specific repositories into thin adapters.

## Goals

- Keep shared scripts, profiles, package patches, release metadata, and mirror
  logic in one main repository.
- Keep separate child repositories only where separate Actions history,
  releases, or source-specific patches are useful.
- Support two upstream source families without duplicating every maintenance
  change.
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
- shared patches
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
patches/
  common/
  primary/
  secondary/
scripts/
  ci/
  local/
manifests/
  runtime-packages.json
```

### Thin Child Repositories

Examples:

- `pystudio-python-toolchain`
- `pystudio-python-toolchain2`
- `pystudio-nodejs-toolchain`
- `pystudio-nodejs-toolchain2`
- `pystudio-cpp-toolchain`
- `pystudio-cpp-toolchain2`

The final target is for each child repo to contain only:

```text
.github/workflows/build.yml
pystudio-build.yml
README.md
```

`pystudio-build.yml` or `children/toolchains/*.yml` declares the small
differences:

```yaml
profile: python
source: primary
architectures:
  - aarch64
  - arm
  - i686
  - x86_64
releasePrefix: pystudio-python-toolchain
```

The child workflow calls the main repository reusable workflow or checks out
the main repository scripts at a pinned ref.

Current migration note: the existing toolchain repositories still contain full
Termux package trees because they also act as transitional source adapters.
Do not delete those trees until package patches have moved into the main
repository under `patches/`.

## Two-Source Strategy

Use two source adapters, but avoid treating them as equal forever.

### Source Adapter Model

`sources/primary.env`

```bash
SOURCE_ID=primary
SOURCE_UPSTREAM_REPO=https://github.com/msmt2018/termux-packages.git
SOURCE_PATCH_SET=primary
```

`sources/secondary.env`

```bash
SOURCE_ID=secondary
SOURCE_UPSTREAM_REPO=https://github.com/msmt2018/termux-packages2.git
SOURCE_PATCH_SET=secondary
```

The main repo owns the policy:

- Try primary first for normal builds.
- Use secondary as fallback when primary fails or when a package is known to
  work better there.
- Promote fixes from secondary back to common patches when they are source
  independent.
- Keep source-specific patches isolated.

### Recommended Build Modes

1. `source=primary`

   Fast normal path. This should be the default for routine package builds.

2. `source=secondary`

   Fallback and comparison path. Run when primary fails or for packages with a
   known secondary advantage.

3. `source=race`

   Optional future mode. Launch primary and secondary in parallel, publish the
   first successful artifact, and record the winner in the manifest.

4. `source=both`

   Audit mode. Build both sources and compare package lists, sizes, checksums,
   and install behavior. Useful before changing app defaults.

## Manifest Policy

The app should not know about all build repositories. It should read one
manifest from the main repository or Gitee mirror.

Each profile entry can include source metadata:

```json
{
  "id": "python",
  "preferredSource": "primary",
  "fallbackSource": "secondary",
  "architectures": {
    "aarch64": {
      "repoArchiveUrl": "...",
      "fallbackRepoArchiveUrl": "..."
    }
  }
}
```

When Gitee mirroring is enabled, only URL fields change. Package IDs, source
metadata, install commands, and verification commands should stay the same.

## Migration Plan

1. Keep current child repositories working.
2. Move reusable build logic into `pystudio-termux-builds`.
3. Replace child repo workflows with thin calls into the main repo.
4. Keep the existing full source forks as transitional source adapters.
5. Move duplicated patches into `patches/common`.
6. Keep only source-specific differences under `patches/primary` and
   `patches/secondary`.
7. Point source adapters at upstream repositories plus main-repo patch sets.
8. Thin child repositories down to workflow/config/README only.
9. Generate `runtime-packages.json` from build metadata instead of hand-editing
   URLs.
10. Mirror the final manifest and assets to Gitee through either CI or the local
   relay script.

## Tradeoff

This design keeps failure isolation and release history from separate child
repositories while removing most duplicated logic. It is less simple than a
single monorepo, but much safer for the current state because each source and
toolchain can still fail independently.
