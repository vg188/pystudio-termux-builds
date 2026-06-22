#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/ci/lib.sh"

profile="${1:-}"
source_kind="${2:-}"
arch="${3:-}"
package_override="${4:-}"

[[ -n "$profile" ]] || die "missing toolchain profile"
[[ -n "$source_kind" ]] || die "missing source kind"
[[ -n "$arch" ]] || die "missing target architecture"

load_env_file "$ROOT/profiles/toolchains/$profile.env"
load_env_file "$ROOT/sources/$source_kind.env"

source_repo_var="$(printf '%s_SOURCE_REPO' "$profile" | tr '[:lower:]-' '[:upper:]_')"
source_repo="${!source_repo_var:-}"
if [[ -z "$source_repo" ]]; then
  source_repo="${SOURCE_UPSTREAM_REPO:-}"
fi
[[ -n "$source_repo" ]] || die "no source repository configured for profile '$profile' and source '$source_kind'"

packages="$(printf '%s' "${package_override:-$DEFAULT_PACKAGES}" | normalize_list)"
[[ -n "$packages" ]] || die "no packages requested"
mapfile -t package_array < <(tr ' ' '\n' <<< "$packages" | sed '/^$/d')

work_dir="$ROOT/work/toolchains/$profile/$source_kind/$arch"
source_dir="$work_dir/source"
stage_dir="$ROOT/dist/toolchains/$profile/$source_kind/$arch"

rm -rf "$work_dir" "$stage_dir"
mkdir -p "$work_dir" "$stage_dir"

echo "Profile: $PROFILE_NAME ($profile)"
echo "Source: $SOURCE_NAME ($source_kind) -> $source_repo"
echo "Patch set: ${SOURCE_PATCH_SET:-none}"
echo "Architecture: $arch"
echo "Packages: ${package_array[*]}"

git clone --depth 1 "$source_repo" "$source_dir"

pushd "$source_dir"
rm -rf output
mkdir -p output
bash ./scripts/run-docker.sh -d ./build-package.sh \
  -C \
  -a "$arch" \
  "${package_array[@]}"
popd

cp -a "$source_dir/output" "$stage_dir/output"
