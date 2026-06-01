#!/usr/bin/env bash
# 解析 AutoGoo 安装根目录并调用 update-step.py
# 用法: source resolve-root.sh && goo_update_step <args...>
# 或直接: bash resolve-root.sh --plan .goo/plan.json --step-id 1 --start --progress 5
set -euo pipefail

resolve_auto_goo_root() {
  local root
  root="$(python3 - <<'PY' 2>/dev/null || true
import json
from pathlib import Path

home = Path.home()
matches = []

def usable(path):
    return path.exists() and not (path / ".orphaned_at").exists()

registry = home / ".claude/plugins/installed_plugins.json"
if registry.exists():
    data = json.loads(registry.read_text(encoding="utf-8"))
    for key, entries in data.get("plugins", {}).items():
        if key.split("@", 1)[0] != "auto-goo":
            continue
        for entry in entries:
            path = Path(entry.get("installPath", "")).expanduser()
            if usable(path):
                matches.append((entry.get("lastUpdated", ""), str(path)))

if not matches:
    settings = home / ".claude/settings.json"
    if settings.exists():
        data = json.loads(settings.read_text(encoding="utf-8"))
        enabled = data.get("enabledPlugins", {})
        marketplaces = data.get("extraKnownMarketplaces", {})
        for key, is_enabled in enabled.items():
            if not is_enabled or "@" not in key:
                continue
            plugin, marketplace = key.split("@", 1)
            if plugin != "auto-goo":
                continue
            source = marketplaces.get(marketplace, {}).get("source", {})
            if source.get("source") != "directory":
                continue
            path_text = source.get("path")
            if not path_text:
                continue
            path = Path(path_text).expanduser()
            if usable(path):
                matches.append(("settings:" + marketplace, str(path)))

if matches:
    print(sorted(matches)[-1][1])
PY
  )"

  if [ -z "$root" ] || [ ! -f "$root/skills/auto-goo/scripts/update-step.py" ]; then
    echo "AutoGoo root not configured; install auto-goo or enable a local directory marketplace in ~/.claude/settings.json" >&2
    return 1
  fi
  echo "$root"
}

goo_update_step() {
  local root
  root="$(resolve_auto_goo_root)" || exit 127
  python3 "$root/skills/auto-goo/scripts/update-step.py" "$@"
}

# 如果直接执行（非 source），自动调用 goo_update_step
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  goo_update_step "$@"
fi
