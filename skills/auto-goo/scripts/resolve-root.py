#!/usr/bin/env python3
"""Resolve AutoGoo-Plugin from Claude Code or Codex installation records."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path


def usable(path: Path) -> bool:
    return path.exists() and not (path / ".orphaned_at").exists() and (
        path / "skills/auto-goo/scripts/update-step.py"
    ).is_file()


def claude_candidates(home: Path) -> list[tuple[str, Path]]:
    matches: list[tuple[str, Path]] = []
    registry = home / ".claude/plugins/installed_plugins.json"
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    for key, entries in data.get("plugins", {}).items():
        if key.split("@", 1)[0] != "autogoo-plugin":
            continue
        for entry in entries if isinstance(entries, list) else []:
            path = Path(str(entry.get("installPath", ""))).expanduser()
            if usable(path):
                matches.append((str(entry.get("lastUpdated", "")), path))

    settings = home / ".claude/settings.json"
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    enabled = data.get("enabledPlugins", {})
    markets = data.get("extraKnownMarketplaces", {})
    for key, is_enabled in enabled.items():
        if not is_enabled or key.split("@", 1)[0] != "autogoo-plugin":
            continue
        marketplace = key.split("@", 1)[1] if "@" in key else ""
        source = markets.get(marketplace, {}).get("source", {})
        if source.get("source") != "directory" or not source.get("path"):
            continue
        path = Path(str(source["path"])).expanduser()
        if usable(path):
            matches.append((f"settings:{marketplace}", path))
    return matches


def codex_candidates(home: Path) -> list[tuple[str, Path]]:
    config_path = home / ".codex/config.toml"
    market_path = home / ".agents/plugins/marketplace.json"
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        market = json.loads(market_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return []
    enabled = {
        key
        for key, value in config.get("plugins", {}).items()
        if isinstance(value, dict) and value.get("enabled", True)
    }
    market_name = str(market.get("name") or "personal")
    matches: list[tuple[str, Path]] = []
    for item in market.get("plugins", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        plugin_id = f"{name}@{market_name}"
        if name not in {"autogoo-plugin", "auto-goo"} or plugin_id not in enabled:
            continue
        source = item.get("source", {})
        path_text = source.get("path") if isinstance(source, dict) else None
        if not path_text:
            continue
        raw = Path(str(path_text)).expanduser()
        candidates = [raw] if raw.is_absolute() else [home / raw, market_path.parent / raw]
        for path in candidates:
            if usable(path):
                matches.append((f"codex:{plugin_id}", path.resolve()))
                break
    return matches


def resolve_root(home: Path | None = None) -> Path | None:
    base = home or Path.home()
    candidates = claude_candidates(base) + codex_candidates(base)
    return sorted(candidates, key=lambda item: item[0])[-1][1] if candidates else None


def main() -> int:
    root = resolve_root()
    if root is None:
        print(
            "AutoGoo-Plugin root not configured; enable it in Claude Code or Codex local plugin marketplace",
            file=__import__("sys").stderr,
        )
        return 1
    print(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
