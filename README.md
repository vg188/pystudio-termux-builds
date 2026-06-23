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
| `python` | `python python-pip` | `pystudio-python-toolchain` | `pystudio-python-toolchain2` |
| `python-build` | pip native build tools | `pystudio-python-toolchain` | `pystudio-python-toolchain2` |
| `python-science` | NumPy, SciPy, BLAS/FFT support | `pystudio-python-toolchain` | `pystudio-python-toolchain2` |
| `python-data` | packaged Python data/runtime utilities | `pystudio-python-toolchain` | `pystudio-python-toolchain2` |
| `python-image` | Pillow and image libraries | `pystudio-python-toolchain` | `pystudio-python-toolchain2` |
| `python-viz` | matplotlib and font/rendering basics | `pystudio-python-toolchain` | `pystudio-python-toolchain2` |
| `python-xml-html` | lxml, XML, HTML, parser tooling | `pystudio-python-toolchain` | `pystudio-python-toolchain2` |
| `python-crypto-network` | crypto and protocol libraries | `pystudio-python-toolchain` | `pystudio-python-toolchain2` |
| `python-gui-tk` | tkinter/Tcl/Tk/X11 runtime support | `pystudio-python-toolchain` | `pystudio-python-toolchain2` |
| `nodejs` | `nodejs npm` | `pystudio-nodejs-toolchain` | `pystudio-nodejs-toolchain2` |
| `tree-sitter` | Tree-sitter CLI and common parser grammars | `pystudio-nodejs-toolchain` | `pystudio-nodejs-toolchain2` |
| `cpp` | `libllvm ndk-sysroot make cmake ninja pkg-config` | `pystudio-cpp-toolchain` | `pystudio-cpp-toolchain2` |

See `docs/python-runtime-profiles.md` for the package-level split and notes
about pip-only packages.

Source adapters are configured in `sources/`:

| Source | Upstream family | Transitional source repos |
| --- | --- | --- |
| `primary` | `msmt2018/termux-packages` | `pystudio-python-toolchain`, `pystudio-nodejs-toolchain`, `pystudio-cpp-toolchain` |
| `secondary` | `msmt2018/termux-packages2` | `pystudio-python-toolchain2`, `pystudio-nodejs-toolchain2`, `pystudio-cpp-toolchain2` |

Bootstrap profiles are configured in `profiles/bootstrap/`:

| Profile | Additional packages | Source |
| --- | --- | --- |
| `base` | `proot` | `pystudio-termux-generator` |
| `python-pip` | `proot,python,python-pip` | `pystudio-python-pip-bootstrap` |

## GitHub Actions

Use **Actions -> Build PyStudio Toolchain Matrix** to build installable runtime
packages. Select:

- `profile`: `python`, one of the split `python-*` profiles, `all-python`,
  `nodejs`, `node-build-core`, `tree-sitter`, `cpp`, or `all`
- `source`: `primary`, `secondary`, or `all`
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

## Migration Plan

Phase 1 keeps the current source forks as adapters so builds remain close to the
versions already tested in GitHub Actions. In this phase the child workflows are
thin, but the source trees remain in place.

Phase 2 should move source patches into this repository under a future
`patches/` directory, then clone upstream sources directly. At that point the
child repositories can become truly ultra-thin: workflow, config, and README.
