#!/usr/bin/env python3
"""Summarize configured remote servers and optionally probe live resources."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REMOTE_PROBE = r"""
set -u
echo "hostname=$(hostname 2>/dev/null || true)"
echo "kernel=$(uname -sr 2>/dev/null || true)"
if command -v nproc >/dev/null 2>&1; then echo "cpu_cores=$(nproc)"; fi
awk '/MemTotal/ {print "mem_total_kb="$2} /MemAvailable/ {print "mem_available_kb="$2}' /proc/meminfo 2>/dev/null || true
df -hP . 2>/dev/null | awk 'NR==2 {print "disk="$2",used="$3",avail="$4",use="$5",mount="$6}' || true
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=index,name,memory.total,memory.used,utilization.gpu --format=csv,noheader,nounits 2>/dev/null | sed 's/^/gpu=/'
else
  echo "gpu=none"
fi
uptime 2>/dev/null | sed 's/^/load=/' || true
"""


@dataclass
class ServerRef:
    config_path: Path
    index: int
    server: dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.server.get("name") or "").strip()

    @property
    def host(self) -> str:
        return str(self.server.get("host") or self.server.get("ip") or "").strip()

    @property
    def user(self) -> str:
        return str(self.server.get("user") or "").strip()

    @property
    def port(self) -> str:
        return str(self.server.get("port") or "22").strip()

    @property
    def server_type(self) -> str:
        return str(self.server.get("type") or "").strip() or "unknown"

    @property
    def purpose(self) -> str:
        return str(self.server.get("purpose") or "").strip()

    @property
    def selector(self) -> str:
        if self.name:
            return self.name
        if self.user and self.host:
            return f"{self.user}@{self.host}:{self.port}"
        return str(self.index)


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"warning: cannot read config {path}: {exc}", file=sys.stderr)
        return None
    if not isinstance(value, dict):
        print(f"warning: config is not a JSON object: {path}", file=sys.stderr)
        return None
    return value


def default_configs() -> list[Path]:
    paths = [Path(".goo/config.json"), Path.home() / ".auto-goo/config.json"]
    seen: set[Path] = set()
    existing: list[Path] = []
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        existing.append(resolved)
    return existing


def configured_servers(configs: list[Path]) -> list[ServerRef]:
    refs: list[ServerRef] = []
    for config_path in configs:
        config = load_json(config_path)
        if not config:
            continue
        servers = config.get("servers") or config.get("compute_servers") or []
        if not isinstance(servers, list):
            continue
        for index, server in enumerate(servers):
            if isinstance(server, dict):
                refs.append(ServerRef(config_path=config_path, index=index, server=server))
    return refs


def format_kb(raw: str) -> str:
    try:
        value = int(raw)
    except ValueError:
        return raw
    gib = value / 1024 / 1024
    return f"{gib:.1f} GiB"


def parse_probe(stdout: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {"gpus": []}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key == "gpu" and value != "none":
            parts = [part.strip() for part in value.split(",")]
            parsed.setdefault("gpus", []).append(
                {
                    "index": parts[0] if len(parts) > 0 else "",
                    "name": parts[1] if len(parts) > 1 else "",
                    "memory_total_mb": parts[2] if len(parts) > 2 else "",
                    "memory_used_mb": parts[3] if len(parts) > 3 else "",
                    "utilization_gpu_percent": parts[4] if len(parts) > 4 else "",
                }
            )
        else:
            parsed[key] = value
    return parsed


def probe_server(root: Path, server_ref: ServerRef, timeout: int) -> dict[str, Any]:
    ssh_script = root / "skills/auto-goo/scripts/goo-ssh.sh"
    if not ssh_script.exists():
        return {"ok": False, "error": f"goo-ssh.sh not found: {ssh_script}"}

    cmd = [
        "bash",
        str(ssh_script),
        "--config",
        str(server_ref.config_path),
        "--server",
        server_ref.selector,
        "--",
        "sh",
        "-lc",
        REMOTE_PROBE,
    ]
    try:
        result = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout + 8,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"probe timed out after {timeout + 8}s"}

    if result.returncode != 0:
        err = result.stderr.strip().splitlines()
        return {"ok": False, "error": err[-1] if err else f"ssh exited {result.returncode}"}

    return {"ok": True, "resources": parse_probe(result.stdout)}


def summarize(ref: ServerRef, probe: dict[str, Any] | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "selector": ref.selector,
        "name": ref.name,
        "host": ref.host,
        "port": ref.port,
        "user": ref.user,
        "type": ref.server_type,
        "purpose": ref.purpose,
        "config": str(ref.config_path),
    }
    defaults = ref.server.get("defaults")
    if isinstance(defaults, dict) and defaults:
        item["defaults"] = defaults
    if probe is not None:
        item["probe"] = probe
    return item


def print_text(items: list[dict[str, Any]]) -> None:
    if not items:
        print("No remote servers configured.")
        return
    for i, item in enumerate(items, 1):
        label = item.get("name") or item.get("selector") or f"server-{i}"
        host = item.get("host") or "unknown-host"
        print(f"{i}. {label} ({item.get('type')}) {item.get('user')}@{host}:{item.get('port')}")
        if item.get("purpose"):
            print(f"   purpose: {item['purpose']}")
        defaults = item.get("defaults") or {}
        if isinstance(defaults, dict) and defaults.get("workdir"):
            print(f"   workdir:  {defaults['workdir']}")
        paths = defaults.get("paths") if isinstance(defaults, dict) else {}
        if isinstance(paths, dict) and paths:
            path_bits = [f"{key}={value}" for key, value in paths.items() if value]
            if path_bits:
                print(f"   paths:    {'; '.join(path_bits)}")
        setup = defaults.get("setup_commands") if isinstance(defaults, dict) else []
        if isinstance(setup, list) and setup:
            print(f"   setup:    {len(setup)} command(s)")
        print(f"   config:  {item.get('config')}")
        probe = item.get("probe")
        if not probe:
            continue
        if not probe.get("ok"):
            print(f"   probe:   unavailable - {probe.get('error')}")
            continue
        resources = probe.get("resources") or {}
        bits = []
        if resources.get("cpu_cores"):
            bits.append(f"cpu={resources['cpu_cores']} cores")
        if resources.get("mem_available_kb") and resources.get("mem_total_kb"):
            bits.append(f"mem={format_kb(resources['mem_available_kb'])}/{format_kb(resources['mem_total_kb'])} available")
        if resources.get("disk"):
            bits.append(f"disk={resources.get('avail', '?')} available at {resources.get('mount', '.')}")
        gpus = resources.get("gpus") or []
        if gpus:
            gpu_bits = []
            for gpu in gpus:
                gpu_bits.append(
                    f"{gpu.get('index')}:{gpu.get('name')} "
                    f"{gpu.get('memory_used_mb')}/{gpu.get('memory_total_mb')} MiB "
                    f"util={gpu.get('utilization_gpu_percent')}%"
                )
            bits.append("gpu=" + "; ".join(gpu_bits))
        elif resources.get("gpu") == "none":
            bits.append("gpu=none")
        print(f"   probe:   {'; '.join(bits) if bits else 'reachable'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", action="append", type=Path, help="Config path. Repeatable.")
    parser.add_argument("--server", help="Only show/probe one server selector.")
    parser.add_argument("--probe", action="store_true", help="Probe live CPU/memory/disk/GPU resources over SSH.")
    parser.add_argument("--timeout", type=int, default=8, help="SSH connect timeout in seconds.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3], help="AutoGoo root.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    configs = [path.expanduser().resolve() for path in args.config] if args.config else default_configs()
    servers = configured_servers(configs)
    if args.server:
        servers = [
            ref
            for ref in servers
            if args.server
            in {
                ref.selector,
                ref.name,
                ref.host,
                f"{ref.host}:{ref.port}",
                f"{ref.user}@{ref.host}",
                f"{ref.user}@{ref.host}:{ref.port}",
                str(ref.index),
            }
        ]

    items: list[dict[str, Any]] = []
    for ref in servers:
        probe = probe_server(args.root.resolve(), ref, args.timeout) if args.probe else None
        items.append(summarize(ref, probe))

    if args.json:
        print(json.dumps({"servers": items}, ensure_ascii=False, indent=2))
    else:
        print_text(items)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
