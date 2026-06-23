# Source Adapter Maintenance

PyStudio keeps package source access centralized in the main orchestrator:

- `vg188/pystudio-termux-source-termux`
  - upstream: `termux/termux-packages`
- `vg188/pystudio-termux-source-pacman`
  - upstream: `termux-pacman/termux-packages`
- `vg188/pystudio-termux-source-tur`
  - upstream: `termux-user-repository/tur`

Toolchain repositories are thin workflow/config repositories. They do not carry
package source trees. The main orchestrator selects a profile and source
adapter, clones the configured upstream package tree, then applies the active
PyStudio patch queue listed in `patches/source-adapters/<source>/series`.

## Fork Policy

Keep GitHub fork relationships for source adapter repositories when possible,
but keep those forks clean. PyStudio-specific changes live in the main
orchestrator as build-time patches, not as commits on the source fork branch.
This keeps upstream compare views useful and avoids permanent
`ahead N / behind M` drift.

Thin toolchain repositories should not be forks. They are PyStudio-owned
workflow/config shells, not upstream package trees.

`msmt2018/termux-packages` and `msmt2018/termux-packages2` are historical
references only. Do not use them as the long-term upstream remotes.

If a source adapter was accidentally created as a normal repository, the clean
fix is:

1. Recreate it through GitHub's fork flow from the matching upstream repository.
2. Reset the fork's default branch to the upstream default branch.
3. Keep the `upstream` remote read-only locally:

```sh
git remote set-url --push upstream DISABLED
```

If GitHub reports that a fork already exists in the same network, either reuse
that fork with the root upstream configured locally, or rebuild the fork after
exporting PyStudio patches into `patches/source-adapters/`.

## Update Flow

The main repository contains a scheduled `Sync PyStudio Source Forks` workflow.
It calls GitHub's upstream-sync API for each `SOURCE_FORK_REPO` listed in
`sources/*.env`. Manual source-fork maintenance should normally be limited to:

```sh
python3 scripts/ci/sync-source-forks.py
```

When a build breaks after an upstream change, inspect whether the active patch
queue still applies cleanly. Preserve only patches that are still needed:

- download retry hardening
- package dependency trims that avoid Android SDK or GUI-only chains
- host build fixes required by GitHub runners
- source-specific fixes documented in `CONTEXT.md`

Checksum or source URL fixes should be removed from the active `series` once
upstream carries the same values.

TUR is a supplemental source, not a full replacement for the main Termux package
tree. Every build should select one source explicitly; select `tur` only for
packages that are known to exist there.

After merging upstream, run focused child builds before broad releases:

```text
pystudio-python-toolchain
pystudio-nodejs-toolchain
pystudio-cpp-toolchain
pystudio-tree-sitter-toolchain
pystudio-node-build-core-toolchain
```

This keeps adding future source families straightforward: fork or mirror the
new upstream source, add one `sources/<id>.env`, add a patch `series` if needed,
and point thin child workflows at that source through the main reusable
workflow.
