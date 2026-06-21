#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/ci/lib.sh"

profile="${1:-}"
architectures="${2:-}"
additional_override="${3:-}"

[[ -n "$profile" ]] || die "missing bootstrap profile"
[[ -n "$architectures" ]] || die "missing architectures"

load_env_file "$ROOT/profiles/bootstrap/$profile.env"

additional_packages="${additional_override:-$DEFAULT_ADDITIONAL_PACKAGES}"
safe_architectures="$(printf '%s' "$architectures" | safe_name)"
work_dir="$ROOT/work/bootstrap/$profile/$safe_architectures"
source_dir="$work_dir/source"
stage_dir="$ROOT/dist/bootstrap/$profile/$safe_architectures"

rm -rf "$work_dir" "$stage_dir"
mkdir -p "$work_dir" "$stage_dir"

echo "Bootstrap profile: $PROFILE_NAME ($profile)"
echo "Source: $SOURCE_REPO"
echo "Architectures: $architectures"
echo "Additional packages: ${additional_packages:-none}"

git clone --depth 1 "$SOURCE_REPO" "$source_dir"

pushd "$source_dir"
args=(
  --name "${PYSTUDIO_PACKAGE_NAME:-com.vchangxiao.pystudio}"
  --type f-droid
  --architectures "$architectures"
  --disable-terminal
  --disable-tasker
  --disable-float
  --disable-widget
  --disable-api
  --disable-boot
  --disable-styling
  --disable-gui
  --disable-x11
)

if [[ -n "$additional_packages" ]]; then
  args+=(--add "$additional_packages")
fi

bash ./build-termux.sh "${args[@]}"
popd

shopt -s nullglob

bootstrap_count=0
for bootstrap in "$source_dir"/*bootstrap-*.tar.xz "$source_dir"/termux-packages-main/bootstrap-*.tar.xz; do
  [[ -f "$bootstrap" ]] || continue
  filename="$(basename "$bootstrap")"
  arch="$(sed -E 's/.*bootstrap-([^.]*)\.tar\.xz$/\1/' <<< "$filename")"
  cp -f "$bootstrap" "$stage_dir/bootstrap-$arch.tar.xz"
  cp -f "$bootstrap" "$stage_dir/${PYSTUDIO_PACKAGE_NAME:-com.vchangxiao.pystudio}-f-droid-$BOOTSTRAP_ALIAS_SUFFIX-$arch.tar.xz"
  bootstrap_count=$((bootstrap_count + 1))
done

for xz_dir in "$source_dir"/termux-packages-main/xz-* "$source_dir"/xz-*; do
  [[ -d "$xz_dir" ]] || continue
  cp -a "$xz_dir" "$stage_dir/"
done

[[ "$bootstrap_count" -gt 0 ]] || die "no bootstrap tarballs were produced"

archive_tmp="$stage_dir/../$ARTIFACT_PREFIX-assets-$safe_architectures.tar.gz"
tar -czf "$archive_tmp" -C "$stage_dir" .
mv "$archive_tmp" "$stage_dir/"

(
  cd "$stage_dir"
  find . -type f ! -name SHA256SUMS.txt -print0 |
    sort -z |
    xargs -0 sha256sum > SHA256SUMS.txt
)

find "$stage_dir" -maxdepth 3 -type f -print | sort
