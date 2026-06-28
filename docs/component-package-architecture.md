# Package Repository Architecture

PyStudio now treats optional runtime downloads as Termux-style package
repositories instead of large opaque toolchain archives or thousands of loose
release assets.

## Goals

- Keep each installable package as a normal `.deb` with clear version,
  architecture, dependency, size, and checksum metadata.
- Let the app implement a familiar package manager flow by reading
  `Packages.xz` and resolving `Depends` / `Pre-Depends`.
- Avoid GitHub Release pages containing hundreds of loose `.deb` files.
- Keep domestic acceleration available through a full ModelScope mirror.
- Keep Gitee lightweight by syncing only `runtime-packages.json`.

## Build Output

Each toolchain build produces one repository snapshot per architecture:

- `ARTIFACT-apt-repo-v1-ARCH-rN.tar.gz`
- `ARTIFACT-apt-repo-v1-ARCH-rN.tar.gz.sha256`
- `ARTIFACT-apt-repo-v1-ARCH-rN.json`

The snapshot expands to:

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

GitHub Releases are the authority and retain compact snapshots. ModelScope is a
full-file mirror: CI or a local relay expands the snapshot and uploads the
resulting `dists/` and `pool/` tree. Gitee is manifest-only and should not host
large `.deb` files because of attachment and quota limits.

The app should prefer mirrors by priority:

1. `modelscope` full repo in China;
2. any future full-file mirror;
3. `github-snapshot` fallback, downloaded and extracted locally.

## App Resolver

The app should keep local install state by package name, version, architecture,
and SHA256.

Recommended resolver:

1. Pick the current ABI.
2. Read the selected entry's `repositoryRefs[abi]`.
3. Fetch `Packages.xz` from the best full mirror, or extract the snapshot.
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
`Backfill PyStudio Package Repositories` workflow converts them into
`apt-repo-v1` snapshots and deletes old loose `*-component-*.deb` assets left by
the earlier component experiment.
