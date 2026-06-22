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
| `nodejs` | `nodejs npm` | `pystudio-nodejs-toolchain` | `pystudio-nodejs-toolchain2` |
| `cpp` | `libllvm ndk-sysroot make cmake ninja pkg-config` | `pystudio-cpp-toolchain` | `pystudio-cpp-toolchain2` |

Source adapters are configured in `sources/`:

| Source | Upstream family | Transitional source repos |
| --- | --- | --- |
| `primary` | `msmt2018/termux-packages` | `pystudio-python-toolchain`, `pystudio-nodejs-toolchain`, `pystudio-cpp-toolchain` |
| `secondary` | `msmt2018/termux-packages2` | `pystudio-python-toolchain2`, `pystudio-nodejs-toolchain2`, `pystudio-cpp-toolchain2` |

Bootstrap profiles are configured in `profiles/bootstrap/`:

| Profile | Additional packages | Source |
| --- | --- | --- |
| `base` | none | `pystudio-termux-generator` |
| `python-pip` | `python,python-pip` | `pystudio-python-pip-bootstrap` |

## GitHub Actions

Use **Actions -> Build PyStudio Toolchain Matrix** to build installable runtime
packages. Select:

- `profile`: `python`, `nodejs`, `cpp`, or `all`
- `source`: `primary`, `secondary`, or `all`
- `architectures`: `aarch64`, `arm`, `i686`, `x86_64`, or a comma-separated list

By default, manual toolchain runs build `aarch64`, `arm`, `i686`, and `x86_64`
as separate matrix jobs, so the architectures run in parallel.

Use **Actions -> Build PyStudio Bootstrap Profiles** to build bootstrap
tarballs. Select `base` for a minimal terminal bootstrap or `python-pip` for an
integrated Python/Pip bootstrap.

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
