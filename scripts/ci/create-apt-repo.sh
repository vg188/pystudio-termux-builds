#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/ci/lib.sh"

profile="${1:-}"
source_kind="${2:-}"
arch="${3:-}"

[[ -n "$profile" ]] || die "missing toolchain profile"
[[ -n "$source_kind" ]] || die "missing source kind"
[[ -n "$arch" ]] || die "missing target architecture"

stage_dir="$ROOT/dist/toolchains/$profile/$source_kind/$arch"
output_dir="$stage_dir/output"
repo_dir="$stage_dir/repo-$arch"
binary_dir="$repo_dir/dists/stable/main/binary-$arch"
artifact_slug="pystudio-$profile-toolchain-$source_kind"

if ! find "$output_dir" -type f -name "*.deb" | grep -q .; then
  die "no deb files were produced in $output_dir"
fi

rm -rf "$repo_dir"
mkdir -p "$repo_dir/pool/main" "$binary_dir"

find "$output_dir" -type f -name "*.deb" -print0 |
  sort -z |
  xargs -0 -I{} cp -f "{}" "$repo_dir/pool/main/"

(
  cd "$repo_dir"
  dpkg-scanpackages --multiversion pool/main > "dists/stable/main/binary-$arch/Packages"
  gzip -9ck "dists/stable/main/binary-$arch/Packages" > "dists/stable/main/binary-$arch/Packages.gz"
  xz -T0 -9ck "dists/stable/main/binary-$arch/Packages" > "dists/stable/main/binary-$arch/Packages.xz"
)

find "$repo_dir/pool/main" -type f -name "*.deb" -print0 |
  sort -z |
  xargs -0 sha256sum > "$stage_dir/SHA256SUMS-$arch.txt"

tar -czf "$stage_dir/$artifact_slug-repo-$arch.tar.gz" -C "$repo_dir" .
tar -czf "$stage_dir/$artifact_slug-debs-$arch.tar.gz" -C "$output_dir" .

find "$repo_dir" -type f -print | sort
cat "$stage_dir/SHA256SUMS-$arch.txt"

