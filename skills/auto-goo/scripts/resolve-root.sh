#!/usr/bin/env bash
# Resolve the installed AutoGoo-Plugin root and invoke update-step.py.
set -euo pipefail

resolve_auto_goo_root() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  python3 "$script_dir/resolve-root.py"
}

goo_update_step() {
  local root
  root="$(resolve_auto_goo_root)" || exit 127
  python3 "$root/skills/auto-goo/scripts/update-step.py" "$@"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  goo_update_step "$@"
fi
