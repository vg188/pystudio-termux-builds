#!/usr/bin/env bash
set -euo pipefail

die() {
  echo "error: $*" >&2
  exit 1
}

repo_root() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "$script_dir/../.." && pwd
}

load_env_file() {
  local file="$1"
  [[ -f "$file" ]] || die "profile file not found: $file"
  set -a
  # shellcheck disable=SC1090
  source "$file"
  set +a
}

normalize_list() {
  tr ',\n' '  ' | xargs
}

safe_name() {
  tr ', /' '---' | tr -cd 'A-Za-z0-9_.+-'
}

