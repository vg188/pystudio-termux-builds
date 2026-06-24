# PyStudio Termux Builds

This is the control repository for PyStudio Termux bootstrap and runtime
toolchain builds.

The repeated CI logic lives here:

- one workflow for runtime toolchains
- one workflow for bootstraps
- one apt repository packager
- one profile directory for package sets
- one source adapter directory for managed package sources
- one reusable workflow that child repositories can call

## Profiles

Runtime toolchains are configured in `profiles/toolchains/`:

| Profile | Packages | Default source |
| --- | --- | --- |
| `python` | `python python-pip` | `primary` |
| `python-build` | pip native build tools | `primary` |
| `python-science` | NumPy, SciPy, BLAS/FFT support | `primary` |
| `python-data` | packaged Python data/runtime utilities | `primary` |
| `python-image` | Pillow and image libraries | `primary` |
| `python-viz` | matplotlib and font/rendering basics | `primary` |
| `python-xml-html` | lxml, XML, HTML, parser tooling | `primary` |
| `python-crypto-network` | crypto and protocol libraries | `primary` |
| `python-gui-tk` | tkinter/Tcl/Tk/X11 runtime support | `primary` |
| `nodejs` | `nodejs npm` | `primary` |
| `cpp` | `libllvm ndk-sysroot make cmake ninja pkg-config` | `primary` |

See `docs/python-runtime-profiles.md` for the package-level split and notes
about pip-only packages.

Source adapters are configured in `sources/`:

| Source | Source adapter repository | Upstream family |
| --- | --- | --- |
| `primary` | `pystudio-termux-source-termux` | `termux/termux-packages` |
| `secondary` | `pystudio-termux-source-pacman` | `termux-pacman/termux-packages` |
| `tur` | `pystudio-termux-source-tur` | `termux-user-repository/tur` |

Each build selects exactly one source. `primary` is the normal source,
`secondary` is the fallback/comparison source, and `tur` is a supplemental
source for packages that live in TUR.

The source adapter repositories are managed mirror forks. Builds clone the
`SOURCE_REPO` fork URL from `sources/*.env`; `SOURCE_UPSTREAM_REPO` is used only
by the main repository sync workflow. GitHub Actions should remain disabled in
those source forks so inherited upstream CI does not run in the PyStudio fork.

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
- `source`: `primary`, `secondary`, or `tur`
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

Each toolchain child repository exposes one workflow with a `source` input:

- `vg188/pystudio-python-toolchain`
- `vg188/pystudio-nodejs-toolchain`
- `vg188/pystudio-cpp-toolchain`
- `vg188/pystudio-tree-sitter-toolchain`
- `vg188/pystudio-node-build-core-toolchain`

Tree-sitter and Node.js native build core are opt-in child-repository builds:

- `vg188/pystudio-tree-sitter-toolchain`
- `vg188/pystudio-node-build-core-toolchain`

`runtime-packages.json` is the app-facing download index. It uses a unified
`items[]` catalog for both bootstrap archives and optional package sets. Each
item exposes the same display fields (`title`, `description`, `packages`,
`commands`), the same install metadata, and per-architecture artifact lists.
The app download window should index `title`, `description`, `packages`, and
`commands` so searches such as `pip`, `openssl`, `xz`, `cmake`, or `xmllint`
can find the right optional download. See `docs/runtime-manifest-schema.md`
for the current schema.

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
