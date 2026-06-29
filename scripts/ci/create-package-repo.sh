#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/ci/lib.sh"

profile="${1:-}"
source_kind="${2:-}"
arch="${3:-}"
artifact_prefix="${4:-}"
version="${5:-}"

[[ -n "$profile" ]] || die "missing toolchain profile"
[[ -n "$source_kind" ]] || die "missing source kind"
[[ -n "$arch" ]] || die "missing target architecture"
[[ -n "$version" ]] || die "missing package repository version"

stage_dir="$ROOT/dist/toolchains/$profile/$source_kind/$arch"
output_dir="$stage_dir/output"
artifact_slug="${artifact_prefix:-pystudio-$profile-toolchain-$source_kind}"
repo_version="$(tr -cs 'A-Za-z0-9._+-' '-' <<< "$version" | sed 's/^-//;s/-$//')"
repo_slug="$artifact_slug-apt-repo-v1-$arch-$repo_version"
repo_dir="$stage_dir/$repo_slug"
metadata_path="$stage_dir/$repo_slug.json"
archive_path="$stage_dir/$repo_slug.tar.gz"
flat_dir="$stage_dir/$repo_slug-flat"

if ! find "$output_dir" -type f -name "*.deb" | grep -q .; then
  die "no deb files were produced in $output_dir"
fi

rm -rf "$repo_dir" "$metadata_path" "$archive_path" "$flat_dir"

python3 "$ROOT/scripts/ci/create-package-repo.py" \
  --output-dir "$output_dir" \
  --repo-dir "$repo_dir" \
  --metadata "$metadata_path" \
  --artifact-prefix "$artifact_slug" \
  --profile "$profile" \
  --source "$source_kind" \
  --arch "$arch" \
  --version "$repo_version"

python3 "$ROOT/scripts/ci/create-flat-release-repo.py" \
  --repo-dir "$repo_dir" \
  --flat-dir "$flat_dir" \
  --repo-slug "$repo_slug" \
  --arch "$arch"

tar -C "$repo_dir" -czf "$archive_path" .
python3 - <<PY
import hashlib
from pathlib import Path
path = Path("$archive_path")
digest = hashlib.sha256(path.read_bytes()).hexdigest()
print(f"{digest}  {path.name}")
(path.with_suffix(path.suffix + ".sha256")).write_text(f"{digest}  {path.name}\n", encoding="utf-8")
PY

printf '%s\n' "$archive_path"
printf '%s\n' "$archive_path.sha256"
printf '%s\n' "$metadata_path"
printf '%s\n' "$flat_dir"
