#!/usr/bin/env python3
"""Create and update AutoGoo thread metadata."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def slugify(value: str, limit: int = 42) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^\w.\-]+", "-", text, flags=re.UNICODE)
    text = re.sub(r"-{2,}", "-", text).strip("-_.")
    return (text or "thread")[:limit].strip("-_.") or "thread"


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def goo_dir_from_plan(plan_path: Path) -> Path:
    plan = plan_path.resolve()
    if plan.parent.parent.name == "threads":
        return plan.parent.parent.parent
    if plan.parent.name == ".goo":
        return plan.parent
    return Path.cwd() / ".goo"


def thread_dir(goo_dir: Path, thread_id: str) -> Path:
    return goo_dir / "threads" / thread_id


def current_thread_id(goo_dir: Path) -> str | None:
    data = load_json(goo_dir / "current_thread.json", {})
    value = data.get("thread_id")
    return str(value) if value else None


def compute_plan_status(plan: dict[str, Any]) -> str:
    if plan.get("status") == "paused":
        return "paused"
    steps = [step for step in plan.get("steps", []) if isinstance(step, dict)]
    if not steps:
        return str(plan.get("status") or "pending")
    total = len(steps)
    completed = sum(1 for step in steps if step.get("status") == "completed")
    failed = sum(1 for step in steps if step.get("status") == "failed")
    blocked = sum(1 for step in steps if step.get("status") == "blocked")
    running = sum(1 for step in steps if step.get("status") == "running")
    if completed == total:
        return "completed"
    if failed and not running:
        return "failed"
    if blocked and not running:
        return "blocked"
    if running or completed:
        return "running"
    return "pending"


def unique_thread_id(goo_dir: Path, title: str) -> str:
    base = f"tg-{stamp()}-{slugify(title)}"
    candidate = base
    index = 1
    while thread_dir(goo_dir, candidate).exists():
        index += 1
        candidate = f"{base}-{index}"
    return candidate


def ensure_index(goo_dir: Path) -> dict[str, Any]:
    path = goo_dir / "threads" / "index.json"
    return load_json(path, {"threads": []})


def write_index(goo_dir: Path, index: dict[str, Any]) -> None:
    dump_json(goo_dir / "threads" / "index.json", index)


def upsert_index(index: dict[str, Any], meta: dict[str, Any]) -> None:
    threads = [item for item in index.get("threads", []) if isinstance(item, dict)]
    compact = {
        "id": meta["id"],
        "title": meta.get("title", ""),
        "status": meta.get("status", "planning"),
        "plan_path": meta.get("plan_path", ""),
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
    }
    for pos, item in enumerate(threads):
        if item.get("id") == meta["id"]:
            threads[pos] = {**item, **compact}
            break
    else:
        threads.append(compact)
    index["threads"] = sorted(threads, key=lambda item: str(item.get("updated_at", "")), reverse=True)


def create_thread(goo_dir: Path, title: str, runtime: str = "claude-code", thread_id: str | None = None) -> dict[str, Any]:
    thread_id = thread_id or unique_thread_id(goo_dir, title)
    tdir = thread_dir(goo_dir, thread_id)
    tdir.mkdir(parents=True, exist_ok=True)
    for child in ("logs", "artifacts", "reports"):
        (tdir / child).mkdir(parents=True, exist_ok=True)
    created = now()
    meta = {
        "id": thread_id,
        "title": title,
        "status": "planning",
        "runtime": runtime,
        "created_at": created,
        "updated_at": created,
        "active_plan": "plan.json",
        "plan_path": f".goo/threads/{thread_id}/plan.json",
        "brainstorm_path": f".goo/threads/{thread_id}/brainstorm.json",
        "logs_dir": f".goo/threads/{thread_id}/logs",
        "artifacts_dir": f".goo/threads/{thread_id}/artifacts",
        "reports_dir": f".goo/threads/{thread_id}/reports",
        "archive": {},
    }
    dump_json(tdir / "thread.json", meta)
    index = ensure_index(goo_dir)
    upsert_index(index, meta)
    write_index(goo_dir, index)
    set_current(goo_dir, thread_id)
    return meta


def set_current(goo_dir: Path, thread_id: str) -> None:
    tdir = thread_dir(goo_dir, thread_id)
    if not (tdir / "thread.json").exists():
        raise SystemExit(f"thread not found: {thread_id}")
    dump_json(goo_dir / "current_thread.json", {"thread_id": thread_id, "updated_at": now()})


def resolve_thread(goo_dir: Path, thread_id: str | None, plan_path: Path | None = None) -> str | None:
    if thread_id:
        return thread_id
    if plan_path and plan_path.exists():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            plan = {}
        meta = plan.get("thread")
        if isinstance(meta, dict) and meta.get("id"):
            return str(meta["id"])
        if plan.get("thread_id"):
            return str(plan["thread_id"])
    return current_thread_id(goo_dir)


def sync_from_plan(plan_path: Path, thread_id: str | None = None) -> dict[str, Any]:
    plan = load_json(plan_path, {})
    goo_dir = goo_dir_from_plan(plan_path)
    resolved = resolve_thread(goo_dir, thread_id, plan_path)
    if not resolved:
        return {}
    tdir = thread_dir(goo_dir, resolved)
    meta = load_json(tdir / "thread.json", {})
    if not meta:
        meta = create_thread(goo_dir, plan.get("task", resolved), thread_id=resolved)
    status = compute_plan_status(plan)
    updated = now()
    meta.update(
        {
            "id": resolved,
            "title": meta.get("title") or plan.get("task", resolved),
            "status": status,
            "updated_at": updated,
            "active_plan": plan_path.name,
            "plan_path": relative_to_goo_parent(goo_dir, plan_path),
            "started_at": plan.get("started_at") or meta.get("started_at"),
            "completed_at": plan.get("completed_at") or meta.get("completed_at"),
        }
    )
    archive = plan.get("archive")
    if isinstance(archive, dict):
        meta["archive"] = {**meta.get("archive", {}), **archive}
    dump_json(tdir / "thread.json", meta)
    index = ensure_index(goo_dir)
    upsert_index(index, meta)
    write_index(goo_dir, index)
    return meta


def relative_to_goo_parent(goo_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(goo_dir.parent.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def list_threads(goo_dir: Path) -> int:
    index = ensure_index(goo_dir)
    current = current_thread_id(goo_dir)
    threads = [item for item in index.get("threads", []) if isinstance(item, dict)]
    if not threads:
        print("No AutoGoo threads found.")
        return 0
    print("AutoGoo threads")
    for item in threads:
        mark = "*" if item.get("id") == current else " "
        print(
            f"{mark} {item.get('id')} [{item.get('status', 'unknown')}] "
            f"{item.get('title', '')} · {item.get('updated_at', '')}"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage AutoGoo thread metadata")
    parser.add_argument("--goo-dir", default=".goo", help="AutoGoo state directory")
    sub = parser.add_subparsers(dest="cmd", required=True)

    create = sub.add_parser("create", help="create a thread")
    create.add_argument("--title", required=True)
    create.add_argument("--id", dest="thread_id")
    create.add_argument("--runtime", default="claude-code")

    current = sub.add_parser("set-current", help="set current thread")
    current.add_argument("--id", dest="thread_id", required=True)

    sync = sub.add_parser("sync", help="sync thread metadata from plan")
    sync.add_argument("--plan", default=".goo/plan.json")
    sync.add_argument("--id", dest="thread_id")

    sub.add_parser("list", help="list threads")

    args = parser.parse_args()
    goo_dir = Path(args.goo_dir)
    goo_dir.mkdir(parents=True, exist_ok=True)

    if args.cmd == "create":
        meta = create_thread(goo_dir, args.title, args.runtime, args.thread_id)
        print(meta["id"])
        return 0
    if args.cmd == "set-current":
        set_current(goo_dir, args.thread_id)
        print(f"current thread: {args.thread_id}")
        return 0
    if args.cmd == "sync":
        meta = sync_from_plan(Path(args.plan), args.thread_id)
        if meta:
            print(f"synced thread {meta.get('id')}: status={meta.get('status')}")
        return 0
    if args.cmd == "list":
        return list_threads(goo_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
