#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/ci/lib.sh"

profile="${1:-}"
source_kind="${2:-}"
arch="${3:-}"
artifact_prefix="${4:-}"

[[ -n "$profile" ]] || die "missing toolchain profile"
[[ -n "$source_kind" ]] || die "missing source kind"
[[ -n "$arch" ]] || die "missing target architecture"

stage_dir="$ROOT/dist/toolchains/$profile/$source_kind/$arch"
output_dir="$stage_dir/output"
artifact_slug="${artifact_prefix:-pystudio-$profile-toolchain-$source_kind}"

if ! find "$output_dir" -type f -name "*.deb" | grep -q .; then
  die "no deb files were produced in $output_dir"
fi

rm -rf "$stage_dir/components"

python3 "$ROOT/scripts/ci/create-component-index.py" \
  --output-dir "$output_dir" \
  --components-dir "$stage_dir/components" \
  --index "$stage_dir/$artifact_slug-component-index-$arch.json" \
  --artifact-prefix "$artifact_slug" \
  --profile "$profile" \
  --source "$source_kind" \
  --arch "$arch"

find "$stage_dir/components" -type f -name "*.deb" -print | sort
printf '%s\n' "$stage_dir/$artifact_slug-component-index-$arch.json"
