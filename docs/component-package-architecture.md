# Package Repository Architecture

PyStudio now treats optional runtime downloads as Termux-style package
repositories instead of large opaque toolchain archives.

## Goals

- Keep each installable package as a normal `.deb` with clear version,
  architecture, dependency, size, and checksum metadata.
- Let the app implement a familiar package manager flow by reading
  `Packages.xz` and resolving `Depends` / `Pre-Depends`.
- Publish normal `.deb` package files with stable package/version/architecture
  names, matching the Termux/TUR package management model.
- Keep domestic acceleration available through a full ModelScope mirror.
- Keep Gitee lightweight by syncing only `runtime-packages.json`.

## Build Output

Each toolchain build produces one apt repository index per architecture. GitHub
Release assets expose the package manager view directly:

- `package_version_ARCH.deb`
- `ARTIFACT-apt-repo-v1-ARCH-rN-Packages`
- `ARTIFACT-apt-repo-v1-ARCH-rN-Packages.gz`
- `ARTIFACT-apt-repo-v1-ARCH-rN-Packages.xz`
- `ARTIFACT-apt-repo-v1-ARCH-rN.json`

The generated repository directory is temporary build state used to produce the
flat index:

```text
dists/pystudio/main/binary-aarch64/Packages
dists/pystudio/main/binary-aarch64/Packages.gz
dists/pystudio/main/binary-aarch64/Packages.xz
dists/pystudio/Release
pool/main/p/python/python_3.12.x_aarch64.deb
repo-metadata.json
```

The file name carries the important maintenance coordinates:

- artifact/profile prefix;
- repo format version, currently `apt-repo-v1`;
- architecture;
- release version, for example `r10`.

## Mirrors

GitHub Releases are the authority. New builds publish normal package files as
flat release assets: each `.deb` keeps its Debian file name such as
`python_3.12.x_aarch64.deb`, and each architecture gets a matching
`ARTIFACT-apt-repo-v1-ARCH-rN-Packages.xz` index. Toolchain tarballs are not
published as install units.

ModelScope is an optional flat-file mirror: CI or a local relay can copy the
same `Packages.xz` and `.deb` assets from GitHub Releases. Gitee is
manifest-only and should not host large `.deb` files because of attachment and
quota limits.

The app should prefer mirrors by priority:

1. `github-release-flat` release assets for direct `.deb` downloads;
2. `modelscope` flat package mirrors when available.

## Build-Time Reuse

CI can reuse packages that were already built in previous flat package indexes.
Profiles declare `REUSE_PACKAGE_SETS`, for example `proot-full` reuses
`proot`, `proot-distro`, `python`, `git`, and `cpp`.

During a GitHub Actions build, `scripts/ci/prefetch-package-reuse.py` always
reads the GitHub raw `runtime-packages.json`, downloads the referenced GitHub
Release `Packages.xz` indexes, resolves only the packages requested by the
current profile, downloads those `.deb` files, extracts package data under the
Docker `/data` mount, and writes Termux built markers. `build-package.sh` then
compiles only requested packages that were not already present.

This keeps CI fast while preserving the Termux `pkg`-style split: the final
artifact is still independent `.deb` packages plus a `Packages.xz` index.

## App Resolver

The app should keep local install state by package name, version, architecture,
and SHA256.

Recommended resolver:

1. Pick the current ABI.
2. Read the selected entry's `repositoryRefs[abi]`.
3. Fetch `Packages.xz` from the best flat/full mirror.
4. Resolve requested package names from entry `packages`.
5. Recursively resolve `Depends` and `Pre-Depends`.
6. Skip packages where the same package/version/architecture is already
   installed.
7. Download missing `.deb` files from `Filename`, verify `SHA256`, and install.
8. Run the entry's `verifyCommands`.

This achieves the same reuse goal as component-level manifests, but the package
metadata is now standard and easier to maintain.

## Backfill

Existing `*-debs-ARCH.tar.gz` release assets are migration inputs. The
`Backfill PyStudio Flat Package Repositories` workflow converts them into
flat `.deb` Release assets and `Packages.xz` indexes. It also deletes old loose
`*-component-*.deb` assets left by the earlier component experiment.
