# Source Adapter Maintenance

PyStudio now keeps package source trees in shared source adapter repositories:

- `vg188/pystudio-termux-source-termux`
  - upstream: `termux/termux-packages`
- `vg188/pystudio-termux-source-pacman`
  - upstream: `termux-pacman/termux-packages`
- `vg188/pystudio-termux-source-tur`
  - upstream: `termux-user-repository/tur`

Toolchain repositories are thin workflow/config repositories. They do not carry
package source trees. The main orchestrator selects a profile and source
adapter, then the reusable workflow clones the shared source adapter.

## Fork Policy

Keep GitHub fork relationships for source adapter repositories when possible.
They are long-lived downstream package trees and benefit from GitHub's fork
network features: upstream compare views, sync visibility, patch review, and
easier rebasing/merging from upstream.

Thin toolchain repositories should not be forks. They are PyStudio-owned
workflow/config shells, not upstream package trees.

`msmt2018/termux-packages` and `msmt2018/termux-packages2` are historical
references only. Do not use them as the long-term upstream remotes.

If a source adapter was accidentally created as a normal repository, the clean
fix is:

1. Recreate it through GitHub's fork flow from the matching upstream repository.
2. Push or cherry-pick PyStudio patches onto the fork's default branch.
3. Keep the `upstream` remote read-only locally:

```sh
git remote set-url --push upstream DISABLED
```

If GitHub reports that a fork already exists in the same network, either reuse
that fork with the root upstream configured locally, or rebuild the fork after
exporting PyStudio patches. The current primary fork was rebuilt directly from
`termux/termux-packages`.

## Update Flow

For each source adapter:

```sh
git fetch upstream
git checkout master
git merge upstream/master
```

Resolve conflicts by preserving PyStudio-specific changes:

- package name / prefix patches for `com.vchangxiao.pystudio`
- checksum fixes required by current upstream archives
- download retry hardening
- package dependency trims that avoid Android SDK or GUI-only chains
- source-specific fixes documented in `CONTEXT.md`

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
new upstream source, add one `sources/<id>.env`, and point thin child workflows
at that source through the main reusable workflow.
