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

source_key="${PROFILE_SOURCE_KEY:-$profile}"
source_repo_var="$(printf '%s_SOURCE_REPO' "$source_key" | tr '[:lower:]-' '[:upper:]_')"
source_repo="${!source_repo_var:-}"
if [[ -z "$source_repo" ]]; then
  source_repo="${SOURCE_REPO:-${SOURCE_UPSTREAM_REPO:-}}"
fi
[[ -n "$source_repo" ]] || die "no source repository configured for profile '$profile' and source '$source_kind'"

packages="$(printf '%s' "${package_override:-$DEFAULT_PACKAGES}" | normalize_list)"
[[ -n "$packages" ]] || die "no packages requested"
mapfile -t package_array < <(tr ' ' '\n' <<< "$packages" | sed '/^$/d')
reuse_sets="$(printf '%s' "${REUSE_PACKAGE_SETS:-}" | normalize_list)"

work_dir="$ROOT/work/toolchains/$profile/$source_kind/$arch"
source_dir="$work_dir/source"
stage_dir="$ROOT/dist/toolchains/$profile/$source_kind/$arch"
fallback_root="$work_dir/fallback-sources"
docker_data_dir="$work_dir/docker-data"
reuse_cache_dir="$work_dir/reuse-cache"
missing_packages_file="$work_dir/reuse/missing-packages.txt"
build_metadata_file="$stage_dir/build-metadata.json"

rm -rf "$work_dir" "$stage_dir"
mkdir -p "$work_dir" "$stage_dir"

dump_failure_context() {
  local status="$?"
  set +e
  echo "::group::PyStudio build failure diagnostics"
  if [[ -d "$source_dir/.termux-build" ]]; then
    while IFS= read -r log_file; do
      echo
      echo "==> $log_file"
      tail -n 160 "$log_file"
    done < <(find "$source_dir/.termux-build" -type f \( -name "config.log" -o -name "*.log" \) | sort | tail -n 20)
  else
    echo "No .termux-build directory was found."
  fi
  if command -v docker >/dev/null 2>&1 && docker container inspect termux-package-builder >/dev/null 2>&1; then
    echo
    echo "==> Docker builder logs"
    docker exec termux-package-builder sh -lc '
      if [ -d "$HOME/.termux-build" ]; then
        find "$HOME/.termux-build" -type f \( -name "config.log" -o -name "*.log" \) | sort | tail -n 20 |
          while IFS= read -r log_file; do
            printf "\n==> %s\n" "$log_file"
            if [ "$(basename "$log_file")" = "config.log" ]; then
              grep -in -C 8 -E "C compiler|cannot create|conftest|ld\\.lld|clang|gcc|error:|fatal:|No such file|cannot find" "$log_file" | tail -n 220 || true
              printf "\n==> %s tail\n" "$log_file"
            fi
            tail -n 160 "$log_file"
          done
      else
        echo "No container .termux-build directory was found."
      fi
    ' || true
  else
    echo "Docker builder container is not available for log collection."
  fi
  echo "::endgroup::"
  exit "$status"
}
trap dump_failure_context ERR

echo "Profile: $PROFILE_NAME ($profile)"
echo "Source: $SOURCE_NAME ($source_kind) -> $source_repo"
echo "Patch set: ${SOURCE_PATCH_SET:-none}"
echo "Architecture: $arch"
echo "Packages: ${package_array[*]}"
echo "Build-time reuse package sets: ${reuse_sets:-none}"
echo "Android package: ${PYSTUDIO_PACKAGE_NAME:-com.vchangxiao.pystudio}"

git clone --depth 1 "$source_repo" "$source_dir"
source_commit="$(git -C "$source_dir" rev-parse HEAD)"

apply_source_patch_set() {
  local target_dir="$1"
  local patch_set="${2:-}"
  local source_label="${3:-$patch_set}"
  local series patch_name patch_path entry

  [[ -n "$patch_set" && "$patch_set" != "none" ]] || return 0
  series="$ROOT/patches/source-adapters/$patch_set/series"
  if [[ ! -f "$series" ]]; then
    echo "No active patch series for source '$source_label' ($patch_set)."
    return 0
  fi

  echo "Applying PyStudio source patch set '$patch_set' to '$source_label'"
  while IFS= read -r patch_name || [[ -n "$patch_name" ]]; do
    entry="${patch_name%%#*}"
    entry="$(xargs <<< "$entry")"
    [[ -n "$entry" ]] || continue

    patch_path="$ROOT/patches/source-adapters/$patch_set/$entry"
    [[ -f "$patch_path" ]] || die "patch listed in $series was not found: $entry"

    if git -C "$target_dir" apply --reverse --check "$patch_path" >/dev/null 2>&1; then
      echo "Patch already applied: $patch_set/$entry"
      continue
    fi

    if ! git -C "$target_dir" apply --check "$patch_path" >/dev/null 2>&1; then
      die "patch no longer applies cleanly to '$source_label': $patch_set/$entry"
    fi

    git -C "$target_dir" apply "$patch_path"
    echo "Applied patch: $patch_set/$entry"
  done < "$series"
}

apply_source_patch_set "$source_dir" "${SOURCE_PATCH_SET:-}" "$source_kind"
bash "$ROOT/scripts/ci/configure-termux-prefix.sh" "$source_dir" "${PYSTUDIO_PACKAGE_NAME:-com.vchangxiao.pystudio}"

compute_patch_set_hash() {
  local patch_set="${1:-}"
  PATCH_ROOT="$ROOT/patches/source-adapters" PATCH_SET="$patch_set" python3 - <<'PY'
from __future__ import annotations

import hashlib
import os
from pathlib import Path

patch_set = os.environ.get("PATCH_SET", "")
patch_root = Path(os.environ["PATCH_ROOT"])
if not patch_set or patch_set == "none":
    print("")
    raise SystemExit(0)

series = patch_root / patch_set / "series"
if not series.exists():
    print("")
    raise SystemExit(0)

digest = hashlib.sha256()
for raw_line in series.read_text(encoding="utf-8").splitlines():
    entry = raw_line.split("#", 1)[0].strip()
    if not entry:
        continue
    path = series.parent / entry
    digest.update(entry.encode("utf-8") + b"\0")
    digest.update(path.read_bytes())
    digest.update(b"\0")
print(digest.hexdigest())
PY
}

source_patch_hash="$(compute_patch_set_hash "${SOURCE_PATCH_SET:-}")"
source_tree_diff_hash="$(git -C "$source_dir" diff --binary | sha256sum | awk '{print $1}')"
mkdir -p "$stage_dir"
BUILD_METADATA_FILE="$build_metadata_file" \
PROFILE="$profile" \
SOURCE_KIND="$source_kind" \
SOURCE_REPO="$source_repo" \
SOURCE_COMMIT="$source_commit" \
SOURCE_PATCH_SET="${SOURCE_PATCH_SET:-}" \
SOURCE_PATCH_HASH="$source_patch_hash" \
SOURCE_TREE_DIFF_HASH="$source_tree_diff_hash" \
PYSTUDIO_PACKAGE_NAME="${PYSTUDIO_PACKAGE_NAME:-com.vchangxiao.pystudio}" \
python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

metadata = {
    "schemaVersion": 1,
    "profile": os.environ["PROFILE"],
    "source": os.environ["SOURCE_KIND"],
    "sourceRepository": os.environ["SOURCE_REPO"],
    "sourceCommit": os.environ["SOURCE_COMMIT"],
    "patchSet": os.environ.get("SOURCE_PATCH_SET", ""),
    "patchHash": os.environ.get("SOURCE_PATCH_HASH", ""),
    "treeDiffHash": os.environ.get("SOURCE_TREE_DIFF_HASH", ""),
    "pystudioPackageName": os.environ.get("PYSTUDIO_PACKAGE_NAME", ""),
}
path = Path(os.environ["BUILD_METADATA_FILE"])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY

source_env_value() {
  local source_id="$1"
  local var_name="$2"
  local file="$ROOT/sources/$source_id.env"
  [[ -f "$file" ]] || die "source file not found: $file"
  (
    set -euo pipefail
    # shellcheck disable=SC1090
    source "$file"
    printf '%s' "${!var_name:-}"
  )
}

source_env_repo() {
  local source_id="$1"
  local repo
  repo="$(source_env_value "$source_id" SOURCE_REPO)"
  if [[ -z "$repo" ]]; then
    repo="$(source_env_value "$source_id" SOURCE_UPSTREAM_REPO)"
  fi
  printf '%s' "$repo"
}

package_relpath() {
  local root="$1"
  local package="$2"
  local parent
  for parent in packages root-packages x11-packages tur disabled-packages; do
    if [[ -d "$root/$parent/$package" ]]; then
      printf '%s/%s\n' "$parent" "$package"
      return 0
    fi
  done
  return 1
}

clone_fallback_source() {
  local fallback_id="$1"
  local fallback_repo fallback_dir fallback_patch_set
  fallback_repo="$(source_env_repo "$fallback_id")"
  [[ -n "$fallback_repo" ]] || die "no repository configured for fallback source '$fallback_id'"
  fallback_dir="$fallback_root/$fallback_id"
  if [[ ! -d "$fallback_dir/.git" ]]; then
    echo "Cloning fallback source '$fallback_id' -> $fallback_repo" >&2
    git clone --depth 1 "$fallback_repo" "$fallback_dir"
    fallback_patch_set="$(source_env_value "$fallback_id" SOURCE_PATCH_SET)"
    apply_source_patch_set "$fallback_dir" "$fallback_patch_set" "$fallback_id"
  fi
  printf '%s\n' "$fallback_dir"
}

overlay_missing_packages_from_fallback() {
  local fallback_id="$1"
  local fallback_dir parent package_dir package_name target_parent target_dir
  fallback_dir="$(clone_fallback_source "$fallback_id")"

  for parent in packages root-packages x11-packages; do
    [[ -d "$fallback_dir/$parent" ]] || continue
    mkdir -p "$source_dir/$parent"
    while IFS= read -r package_dir; do
      package_name="$(basename "$package_dir")"
      target_parent="$parent"
      target_dir="$source_dir/$target_parent/$package_name"
      if [[ ! -d "$target_dir" ]]; then
        cp -a "$package_dir" "$target_dir"
      fi
    done < <(find "$fallback_dir/$parent" -mindepth 1 -maxdepth 1 -type d | sort)
  done
}

copy_explicit_package_from_fallbacks() {
  local package="$1"
  local relpath fallback_id fallback_dir source_relpath target_relpath

  if relpath="$(package_relpath "$source_dir" "$package")"; then
    echo "Package '$package' found in selected source at $relpath"
    return 0
  fi

  for fallback_id in ${SOURCE_FALLBACK_ORDER:-}; do
    fallback_dir="$(clone_fallback_source "$fallback_id")"
    if source_relpath="$(package_relpath "$fallback_dir" "$package")"; then
      target_relpath="$source_relpath"
      if [[ "$source_relpath" == tur/* || "$source_relpath" == disabled-packages/* ]]; then
        target_relpath="packages/$package"
      fi
      mkdir -p "$source_dir/$(dirname "$target_relpath")"
      rm -rf "$source_dir/$target_relpath"
      cp -a "$fallback_dir/$source_relpath" "$source_dir/$target_relpath"
      echo "Package '$package' copied from '$fallback_id' at $source_relpath"
      return 0
    fi
  done

  echo "Package '$package' was not found in selected or fallback sources; letting build-package report details."
}

for fallback_id in ${SOURCE_FALLBACK_ORDER:-}; do
  overlay_missing_packages_from_fallback "$fallback_id"
done

for package in "${package_array[@]}"; do
  copy_explicit_package_from_fallbacks "$package"
done

prefetch_args=()
for reuse_set in $reuse_sets; do
  prefetch_args+=(--package-set "$reuse_set")
done
for package in "${package_array[@]}"; do
  prefetch_args+=(--requested-package "$package")
done

mkdir -p "$source_dir/output" "$docker_data_dir/data" "$reuse_cache_dir" "$(dirname "$missing_packages_file")"
chmod 0777 "$docker_data_dir/data"
python3 "$ROOT/scripts/ci/prefetch-package-reuse.py" \
  --arch "$arch" \
  --output-dir "$source_dir/output" \
  --docker-data-dir "$docker_data_dir" \
  --cache-dir "$reuse_cache_dir" \
  --missing-packages-file "$missing_packages_file" \
  --source-root "$source_dir" \
  --build-metadata "$build_metadata_file" \
  "${prefetch_args[@]}"

mapfile -t build_package_array < <(sed '/^$/d' "$missing_packages_file")

if [[ "${#build_package_array[@]}" -gt 0 ]]; then
  pushd "$source_dir"
  mkdir -p output
  build_dependency_flag="-I"
  if [[ "${FORCE_BUILD_DEPENDENCIES:-false}" == "true" ]]; then
    build_dependency_flag="-F"
  fi
  TERMUX_DOCKER_RUN_EXTRA_ARGS="--volume $docker_data_dir/data:/data ${TERMUX_DOCKER_RUN_EXTRA_ARGS:-}" \
    bash ./scripts/run-docker.sh -d ./build-package.sh \
      "$build_dependency_flag" \
      -C \
      -a "$arch" \
      "${build_package_array[@]}" \
      -o output
  popd
else
  echo "All requested packages were reused from existing PyStudio package repositories."
fi

python3 "$ROOT/scripts/ci/check-deb-prefix.py" \
  "$source_dir/output" \
  --package-name "${PYSTUDIO_PACKAGE_NAME:-com.vchangxiao.pystudio}"

first_proot_deb="$(find "$source_dir/output" -type f -name 'proot_*.deb' -print -quit)"
if [[ "$profile" == proot* && -n "$first_proot_deb" ]]; then
  python3 "$ROOT/scripts/ci/audit-proot-package.py" \
    "$source_dir/output" \
    --warn-only
fi

cp -a "$source_dir/output" "$stage_dir/output"
