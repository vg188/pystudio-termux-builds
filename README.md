# PyStudio Termux Builds

This is the control repository for PyStudio Termux bootstrap and runtime
toolchain builds.

The previous split repositories are still useful as transitional source
adapters, but the repeated CI logic now lives here:

- one workflow for runtime toolchains
- one workflow for bootstraps
- one apt repository packager
- one profile directory for package sets
- one source adapter directory for `primary` and `secondary`
- one reusable workflow that child repositories can call

## Profiles

Runtime toolchains are configured in `profiles/toolchains/`:

| Profile | Packages | Primary source | Secondary source |
| --- | --- | --- | --- |
| `python` | `python python-pip` | `primary` | `secondary` |
| `python-build` | pip native build tools | `primary` | `secondary` |
| `python-science` | NumPy, SciPy, BLAS/FFT support | `primary` | `secondary` |
| `python-data` | packaged Python data/runtime utilities | `primary` | `secondary` |
| `python-image` | Pillow and image libraries | `primary` | `secondary` |
| `python-viz` | matplotlib and font/rendering basics | `primary` | `secondary` |
| `python-xml-html` | lxml, XML, HTML, parser tooling | `primary` | `secondary` |
| `python-crypto-network` | crypto and protocol libraries | `primary` | `secondary` |
| `python-gui-tk` | tkinter/Tcl/Tk/X11 runtime support | `primary` | `secondary` |
| `nodejs` | `nodejs npm` | `primary` | `secondary` |
| `cpp` | `libllvm ndk-sysroot make cmake ninja pkg-config` | `primary` | `secondary` |

See `docs/python-runtime-profiles.md` for the package-level split and notes
about pip-only packages.

Source adapters are configured in `sources/`:

| Source | Source adapter repository | Upstream family |
| --- | --- | --- |
| `primary` | `pystudio-termux-source-termux` | `termux/termux-packages` |
| `secondary` | `pystudio-termux-source-pacman` | `termux-pacman/termux-packages` |
| `tur` | `pystudio-termux-source-tur` | `termux-user-repository/tur` |

`primary` and `secondary` are full package-tree sources and are included when
`source=all` is selected. `tur` is a supplemental source and should be selected
explicitly for packages that live in TUR.

Bootstrap profiles are configured in `profiles/bootstrap/`:

| Profile | Additional packages | Source |
| --- | --- | --- |
| `base` | `proot` | `pystudio-termux-generator` |
| `python-pip` | `proot,python,python-pip` | `pystudio-python-pip-bootstrap` |

## GitHub Actions

Use **Actions -> Build PyStudio Toolchain Matrix** to build installable runtime
packages. Select:

- `profile`: `python`, one of the split `python-*` profiles, `all-python`,
  `nodejs`, `cpp`, or `all`
- `source`: `primary`, `secondary`, `tur`, or `all`
- `architectures`: `aarch64`, `arm`, `i686`, `x86_64`, or a comma-separated list

By default, manual toolchain runs build `aarch64`, `arm`, `i686`, and `x86_64`
as separate matrix jobs, so the architectures run in parallel.

Use **Actions -> Build PyStudio Bootstrap Profiles** to build bootstrap
tarballs. Select `base` for a minimal terminal bootstrap with the proot
compatibility fallback, or `python-pip` for an integrated Python/Pip bootstrap.

Child repositories can call
`.github/workflows/reusable-toolchain.yml` in this repository. This keeps the
runtime build logic, apt repository packaging, artifact naming, and release
publishing in one place while the child repository keeps only its profile/source
selection workflow.

Bootstrap runs use the same default four-architecture matrix. Selecting
`profile=all` builds `base` and `python-pip` for each architecture as separate
jobs.

Tree-sitter and Node.js native build core are opt-in child-repository builds:

- `vg188/pystudio-tree-sitter-toolchain`
- `vg188/pystudio-node-build-core-toolchain`

Those repositories are intentionally thin and call the reusable workflow in
this repository. The profile definitions still live in `profiles/toolchains/`.
The full Termux package trees live only in the shared source adapter
repositories listed above. Source repositories are direct forks of their root
upstreams where GitHub's fork network allows it; they no longer depend on
`msmt2018` as an upstream middle layer.

See `docs/source-adapter-maintenance.md` for upstream sync and patch
maintenance.

## Migration Plan

Phase 1 keeps shared source adapter repositories so builds remain close to the
versions already tested in GitHub Actions. Child workflows are thin and do not
carry package source trees.

Phase 2 keeps a source patch archive in `patches/source-adapters/` and uses it
as the recovery path when a source fork needs to be rebuilt from a clean
upstream. The active builds still clone the managed source forks so existing
patches remain applied during normal CI runs.
