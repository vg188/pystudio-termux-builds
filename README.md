# PyStudio Termux Builds

This is the control repository for PyStudio Termux bootstrap and runtime
toolchain builds.

The previous split repositories are still useful as source adapters, but the
repeated CI logic now lives here:

- one workflow for runtime toolchains
- one workflow for bootstraps
- one apt repository packager
- one profile directory for package sets and source adapters

## Profiles

Runtime toolchains are configured in `profiles/toolchains/`:

| Profile | Packages | Primary source | Secondary source |
| --- | --- | --- | --- |
| `python` | `python python-pip` | `pystudio-python-toolchain` | `pystudio-python-toolchain2` |
| `nodejs` | `nodejs npm` | `pystudio-nodejs-toolchain` | `pystudio-nodejs-toolchain2` |
| `cpp` | `libllvm ndk-sysroot make cmake ninja pkg-config` | `pystudio-cpp-toolchain` | `pystudio-cpp-toolchain2` |

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

Bootstrap runs use the same default four-architecture matrix. Selecting
`profile=all` builds `base` and `python-pip` for each architecture as separate
jobs.

## Migration Plan

Phase 1 keeps the current source forks as adapters so builds remain close to
the versions already tested in GitHub Actions.

Phase 2 should move source patches into this repository under a future
`patches/` directory, then clone upstream sources directly. At that point the
old split repositories can become read-only references or be removed.
