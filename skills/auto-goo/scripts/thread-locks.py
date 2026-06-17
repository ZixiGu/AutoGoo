#!/usr/bin/env python3
"""Check and manage AutoGoo thread resource lock conflicts."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOCK_TYPES = ("files", "wiki", "servers", "ports")
DEFAULT_WORKSPACE_PATHS = {
    "locks_dir": ".goo/locks",
}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def project_root_from_config_dir(config_dir: Path) -> Path:
    return config_dir.resolve().parent if config_dir.name == ".goo" else Path.cwd().resolve()


def find_config_dir(start: Path) -> Path:
    resolved = start.resolve()
    for candidate in [resolved, *resolved.parents]:
        if candidate.name == ".goo":
            return candidate
        if candidate.name == ".goo" and (candidate / "config.json").exists():
            return candidate
        config_dir = candidate / ".goo"
        if (config_dir / "config.json").exists():
            return config_dir
    return Path.cwd() / ".goo"


def workspace_paths(config_dir: Path) -> dict[str, str]:
    merged = dict(DEFAULT_WORKSPACE_PATHS)
    config = load_json(config_dir / "config.json", {})
    workspace = config.get("workspace") if isinstance(config.get("workspace"), dict) else {}
    paths = workspace.get("paths") if isinstance(workspace.get("paths"), dict) else {}
    for key, value in paths.items():
        if key in merged and value:
            merged[key] = str(value)
    return merged


def workspace_path(config_dir: Path, key: str) -> Path:
    raw = Path(workspace_paths(config_dir)[key]).expanduser()
    if raw.is_absolute():
        return raw
    default = DEFAULT_WORKSPACE_PATHS.get(key)
    if default and raw.as_posix() == default and config_dir.name == ".goo" and not (config_dir / "config.json").exists():
        return config_dir.resolve() / raw.relative_to(".goo")
    return project_root_from_config_dir(config_dir) / raw


def locks_file(goo_dir: Path, lock_type: str) -> Path:
    return workspace_path(goo_dir, "locks_dir") / f"{lock_type}.json"


def lock_key(lock_type: str, resource: str) -> str:
    return f"{lock_type}:{normalize_resource(lock_type, resource)}"


def normalize_resource(lock_type: str, resource: str) -> str:
    text = str(resource or "").strip()
    if lock_type == "files":
        expanded = os.path.expanduser(text)
        return os.path.normpath(expanded)
    if lock_type == "ports":
        return text.split("/", 1)[0]
    return text.rstrip("/")


def load_locks(goo_dir: Path, lock_type: str) -> list[dict[str, Any]]:
    data = load_json(locks_file(goo_dir, lock_type), {"locks": []})
    if isinstance(data, dict) and isinstance(data.get("locks"), list):
        return [item for item in data["locks"] if isinstance(item, dict)]
    return []


def save_locks(goo_dir: Path, lock_type: str, locks: list[dict[str, Any]]) -> None:
    dump_json(locks_file(goo_dir, lock_type), {"locks": locks, "updated_at": now()})


def resources_conflict(lock_type: str, left: str, right: str) -> bool:
    left_norm = normalize_resource(lock_type, left)
    right_norm = normalize_resource(lock_type, right)
    if left_norm == right_norm:
        return True
    if lock_type != "files":
        return False
    left_parts = Path(left_norm).parts
    right_parts = Path(right_norm).parts
    return left_parts[: len(right_parts)] == right_parts or right_parts[: len(left_parts)] == left_parts


def conflict(existing: dict[str, Any], thread_id: str, lock_type: str, resource: str) -> bool:
    return (
        str(existing.get("thread_id") or "") != thread_id
        and resources_conflict(lock_type, str(existing.get("resource") or ""), resource)
    )


def acquire(goo_dir: Path, lock_type: str, resource: str, thread_id: str, step_id: str = "") -> int:
    resource = normalize_resource(lock_type, resource)
    locks = load_locks(goo_dir, lock_type)
    conflicts = [item for item in locks if conflict(item, thread_id, lock_type, resource)]
    if conflicts:
        print(json.dumps({"ok": False, "conflicts": conflicts}, ensure_ascii=False, indent=2))
        return 2
    key = lock_key(lock_type, resource)
    locks = [item for item in locks if item.get("key") != key or item.get("thread_id") != thread_id]
    locks.append(
        {
            "key": key,
            "type": lock_type,
            "resource": resource,
            "thread_id": thread_id,
            "step_id": step_id,
            "created_at": now(),
        }
    )
    save_locks(goo_dir, lock_type, locks)
    print(json.dumps({"ok": True, "lock": key}, ensure_ascii=False))
    return 0


def release(goo_dir: Path, lock_type: str, resource: str, thread_id: str) -> int:
    resource = normalize_resource(lock_type, resource)
    locks = load_locks(goo_dir, lock_type)
    key = lock_key(lock_type, resource)
    kept = [item for item in locks if not (item.get("key") == key and item.get("thread_id") == thread_id)]
    save_locks(goo_dir, lock_type, kept)
    print(json.dumps({"ok": True, "released": key}, ensure_ascii=False))
    return 0


def step_resources(step: dict[str, Any]) -> dict[str, set[str]]:
    resources: dict[str, set[str]] = {lock_type: set() for lock_type in LOCK_TYPES}
    for path in step.get("allowed_write_paths", []) if isinstance(step.get("allowed_write_paths"), list) else []:
        resources["files"].add(normalize_resource("files", str(path)))
    for path in step.get("outputs", []) if isinstance(step.get("outputs"), list) else []:
        if str(path).strip():
            resources["files"].add(normalize_resource("files", str(path)))
    output = step.get("output")
    if output:
        resources["files"].add(normalize_resource("files", str(output)))

    for field, lock_type in (
        ("wiki_resources", "wiki"),
        ("wiki_pages", "wiki"),
        ("servers", "servers"),
        ("server_resources", "servers"),
        ("ports", "ports"),
    ):
        values = step.get(field)
        if isinstance(values, list):
            for value in values:
                resources[lock_type].add(normalize_resource(lock_type, str(value)))
        elif values:
            resources[lock_type].add(normalize_resource(lock_type, str(values)))

    if step.get("remote_server"):
        resources["servers"].add(normalize_resource("servers", str(step["remote_server"])))
    if step.get("port"):
        resources["ports"].add(normalize_resource("ports", str(step["port"])))
    return {key: values for key, values in resources.items() if values}


def plan_thread_id(plan: dict[str, Any]) -> str:
    thread = plan.get("thread") if isinstance(plan.get("thread"), dict) else {}
    return str(thread.get("id") or plan.get("thread_id") or "")


def iter_plan_resources(plan: dict[str, Any]) -> list[tuple[str, str, str]]:
    items: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for step in plan.get("steps", []) if isinstance(plan.get("steps"), list) else []:
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id") or "")
        if str(step.get("status") or "pending") in {"completed", "failed"}:
            continue
        for lock_type, resources in step_resources(step).items():
            for resource in sorted(resources):
                item = (lock_type, resource, step_id)
                if item not in seen:
                    seen.add(item)
                    items.append(item)
    return items


def check_plan(goo_dir: Path, plan_path: Path) -> int:
    plan = load_json(plan_path, {})
    thread_id = plan_thread_id(plan)
    if not thread_id:
        print(json.dumps({"ok": False, "error": "plan has no thread id"}, ensure_ascii=False, indent=2))
        return 2
    conflicts: list[dict[str, Any]] = []
    resources = iter_plan_resources(plan)
    for lock_type, resource, step_id in resources:
        locks = load_locks(goo_dir, lock_type)
        for item in locks:
            if conflict(item, thread_id, lock_type, resource):
                conflicts.append({"requested": {"type": lock_type, "resource": resource, "step_id": step_id}, "lock": item})
    print(
        json.dumps(
            {
                "ok": not conflicts,
                "thread_id": thread_id,
                "checked": [
                    {"type": lock_type, "resource": resource, "step_id": step_id}
                    for lock_type, resource, step_id in resources
                ],
                "conflicts": conflicts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not conflicts else 2


def acquire_plan(goo_dir: Path, plan_path: Path) -> int:
    plan = load_json(plan_path, {})
    thread_id = plan_thread_id(plan)
    if not thread_id:
        print(json.dumps({"ok": False, "error": "plan has no thread id"}, ensure_ascii=False, indent=2))
        return 2
    resources = iter_plan_resources(plan)
    conflicts: list[dict[str, Any]] = []
    for lock_type, resource, step_id in resources:
        for item in load_locks(goo_dir, lock_type):
            if conflict(item, thread_id, lock_type, resource):
                conflicts.append({"requested": {"type": lock_type, "resource": resource, "step_id": step_id}, "lock": item})
    if conflicts:
        print(json.dumps({"ok": False, "thread_id": thread_id, "conflicts": conflicts}, ensure_ascii=False, indent=2))
        return 2
    acquired = []
    for lock_type, resource, step_id in resources:
        locks = load_locks(goo_dir, lock_type)
        key = lock_key(lock_type, resource)
        locks = [item for item in locks if item.get("key") != key or item.get("thread_id") != thread_id]
        locks.append(
            {
                "key": key,
                "type": lock_type,
                "resource": normalize_resource(lock_type, resource),
                "thread_id": thread_id,
                "step_id": step_id,
                "plan_path": str(plan_path),
                "created_at": now(),
            }
        )
        save_locks(goo_dir, lock_type, locks)
        acquired.append(key)
    print(json.dumps({"ok": True, "thread_id": thread_id, "acquired": acquired}, ensure_ascii=False, indent=2))
    return 0


def release_plan(goo_dir: Path, plan_path: Path) -> int:
    plan = load_json(plan_path, {})
    thread_id = plan_thread_id(plan)
    if not thread_id:
        print(json.dumps({"ok": False, "error": "plan has no thread id"}, ensure_ascii=False, indent=2))
        return 2
    released: list[str] = []
    for lock_type in LOCK_TYPES:
        locks = load_locks(goo_dir, lock_type)
        kept = []
        for item in locks:
            if item.get("thread_id") == thread_id:
                released.append(str(item.get("key") or ""))
            else:
                kept.append(item)
        save_locks(goo_dir, lock_type, kept)
    print(json.dumps({"ok": True, "thread_id": thread_id, "released": released}, ensure_ascii=False, indent=2))
    return 0


def list_locks(goo_dir: Path) -> int:
    data = {lock_type: load_locks(goo_dir, lock_type) for lock_type in LOCK_TYPES}
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage AutoGoo thread resource locks")
    parser.add_argument("--goo-dir", default=".goo")
    sub = parser.add_subparsers(dest="cmd", required=True)
    acquire_cmd = sub.add_parser("acquire")
    acquire_cmd.add_argument("--type", choices=LOCK_TYPES, required=True)
    acquire_cmd.add_argument("--resource", required=True)
    acquire_cmd.add_argument("--thread-id", required=True)
    acquire_cmd.add_argument("--step-id", default="")
    release_cmd = sub.add_parser("release")
    release_cmd.add_argument("--type", choices=LOCK_TYPES, required=True)
    release_cmd.add_argument("--resource", required=True)
    release_cmd.add_argument("--thread-id", required=True)
    check_cmd = sub.add_parser("check-plan")
    check_cmd.add_argument("--plan", required=True)
    acquire_plan_cmd = sub.add_parser("acquire-plan")
    acquire_plan_cmd.add_argument("--plan", required=True)
    release_plan_cmd = sub.add_parser("release-plan")
    release_plan_cmd.add_argument("--plan", required=True)
    sub.add_parser("list")
    args = parser.parse_args()
    goo_dir = find_config_dir(Path(args.goo_dir))
    if args.cmd == "acquire":
        return acquire(goo_dir, args.type, args.resource, args.thread_id, args.step_id)
    if args.cmd == "release":
        return release(goo_dir, args.type, args.resource, args.thread_id)
    if args.cmd == "check-plan":
        return check_plan(goo_dir, Path(args.plan))
    if args.cmd == "acquire-plan":
        return acquire_plan(goo_dir, Path(args.plan))
    if args.cmd == "release-plan":
        return release_plan(goo_dir, Path(args.plan))
    if args.cmd == "list":
        return list_locks(goo_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
