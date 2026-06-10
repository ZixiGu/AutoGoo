#!/usr/bin/env python3
"""Check AutoGoo thread resource lock conflicts."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOCK_TYPES = ("files", "wiki", "servers", "ports")


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


def locks_file(goo_dir: Path, lock_type: str) -> Path:
    return goo_dir / "locks" / f"{lock_type}.json"


def lock_key(lock_type: str, resource: str) -> str:
    return f"{lock_type}:{resource}"


def load_locks(goo_dir: Path, lock_type: str) -> list[dict[str, Any]]:
    data = load_json(locks_file(goo_dir, lock_type), {"locks": []})
    if isinstance(data, dict) and isinstance(data.get("locks"), list):
        return [item for item in data["locks"] if isinstance(item, dict)]
    return []


def save_locks(goo_dir: Path, lock_type: str, locks: list[dict[str, Any]]) -> None:
    dump_json(locks_file(goo_dir, lock_type), {"locks": locks, "updated_at": now()})


def conflict(existing: dict[str, Any], thread_id: str, resource: str) -> bool:
    return str(existing.get("thread_id") or "") != thread_id and str(existing.get("resource") or "") == resource


def acquire(goo_dir: Path, lock_type: str, resource: str, thread_id: str, step_id: str = "") -> int:
    locks = load_locks(goo_dir, lock_type)
    conflicts = [item for item in locks if conflict(item, thread_id, resource)]
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
    locks = load_locks(goo_dir, lock_type)
    key = lock_key(lock_type, resource)
    kept = [item for item in locks if not (item.get("key") == key and item.get("thread_id") == thread_id)]
    save_locks(goo_dir, lock_type, kept)
    print(json.dumps({"ok": True, "released": key}, ensure_ascii=False))
    return 0


def check_plan(goo_dir: Path, plan_path: Path) -> int:
    plan = load_json(plan_path, {})
    thread = plan.get("thread") if isinstance(plan.get("thread"), dict) else {}
    thread_id = str(thread.get("id") or plan.get("thread_id") or "")
    if not thread_id:
        print(json.dumps({"ok": False, "error": "plan has no thread id"}, ensure_ascii=False, indent=2))
        return 2
    conflicts: list[dict[str, Any]] = []
    file_locks = load_locks(goo_dir, "files")
    for step in plan.get("steps", []) if isinstance(plan.get("steps"), list) else []:
        if not isinstance(step, dict):
            continue
        for path in step.get("allowed_write_paths", []) if isinstance(step.get("allowed_write_paths"), list) else []:
            conflicts.extend(item for item in file_locks if conflict(item, thread_id, str(path)))
    print(json.dumps({"ok": not conflicts, "thread_id": thread_id, "conflicts": conflicts}, ensure_ascii=False, indent=2))
    return 0 if not conflicts else 2


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
    sub.add_parser("list")
    args = parser.parse_args()
    goo_dir = Path(args.goo_dir)
    if args.cmd == "acquire":
        return acquire(goo_dir, args.type, args.resource, args.thread_id, args.step_id)
    if args.cmd == "release":
        return release(goo_dir, args.type, args.resource, args.thread_id)
    if args.cmd == "check-plan":
        return check_plan(goo_dir, Path(args.plan))
    if args.cmd == "list":
        return list_locks(goo_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
