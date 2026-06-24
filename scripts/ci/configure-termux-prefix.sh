#!/usr/bin/env bash
set -euo pipefail

source_dir="${1:-}"
package_name="${2:-${PYSTUDIO_PACKAGE_NAME:-com.vchangxiao.pystudio}}"

if [[ -z "$source_dir" ]]; then
  echo "usage: $0 <termux-packages-source-dir> [android-package-name]" >&2
  exit 2
fi

if [[ ! "$package_name" =~ ^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$ ]]; then
  echo "invalid Android package name: $package_name" >&2
  exit 2
fi

properties="$source_dir/scripts/properties.sh"
if [[ ! -f "$properties" ]]; then
  echo "Termux properties file not found: $properties" >&2
  exit 1
fi

python3 - "$properties" "$package_name" <<'PY'
from __future__ import annotations

import pathlib
import sys

path = pathlib.Path(sys.argv[1])
package_name = sys.argv[2]
data_dir = f"/data/data/{package_name}"
prefix = f"{data_dir}/files/usr"
required_replacements = {
    "TERMUX_APP__PACKAGE_NAME": package_name,
    "TERMUX_APP__DATA_DIR": data_dir,
    "TERMUX_REPO_APP__PACKAGE_NAME": package_name,
    "TERMUX_REPO_APP__DATA_DIR": data_dir,
    "TERMUX_REPO__CORE_DIR": f"{data_dir}/termux/core",
    "TERMUX_REPO__APPS_DIR": f"{data_dir}/termux/app",
    "TERMUX_REPO__ROOTFS": f"{data_dir}/files",
    "TERMUX_REPO__HOME": f"{data_dir}/files/home",
    "TERMUX_REPO__PREFIX": prefix,
}
optional_replacements = {
    "CGCT_DEFAULT_PREFIX": f"{prefix}/glibc",
    "CGCT_DIR": f"{data_dir}/cgct",
}
replacements = required_replacements | optional_replacements


def replace_assignment(line: str, key: str, value: str) -> str | None:
    stripped = line.lstrip()
    if not stripped or stripped.startswith("#"):
        return None

    indent = line[: len(line) - len(stripped)]
    export_prefix = ""
    assignment = stripped
    if assignment.startswith("export "):
        export_prefix = "export "
        assignment = assignment[len("export ") :]

    if not assignment.startswith(f"{key}="):
        return None

    newline = "\n" if line.endswith("\n") else ""
    return f'{indent}{export_prefix}{key}="{value}"{newline}'

lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
seen: set[str] = set()
for index, line in enumerate(lines):
    for key, value in replacements.items():
        replaced = replace_assignment(line, key, value)
        if replaced is not None:
            lines[index] = replaced
            seen.add(key)
            break

missing = sorted(set(required_replacements) - seen)
if missing:
    raise SystemExit(f"missing expected properties assignments: {', '.join(missing)}")

path.write_text("".join(lines), encoding="utf-8")
PY

echo "Configured Termux package prefix for $package_name"
