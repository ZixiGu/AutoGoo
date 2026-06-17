#!/usr/bin/env python3
"""Manage AutoGoo web change request state transitions."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ACTIVE_STATUSES = {"pending_model_update", "needs_revision"}
DONE_STATUSES = {"completed", "rejected", "superseded"}
VALID_STATUSES = ACTIVE_STATUSES | DONE_STATUSES | {"in_progress"}
DEFAULT_WORKSPACE_PATHS = {
    "change_requests_dir": ".goo/change-requests",
}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data: dict[str, Any]) -> None:
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
    config_path = config_dir / "config.json"
    if not config_path.exists():
        return merged
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return merged
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


def requests_dir(goo_dir: Path) -> Path:
    return workspace_path(goo_dir, "change_requests_dir")


def iter_requests(goo_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    root = requests_dir(goo_dir)
    if not root.exists():
        return []
    items: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(root.glob("*.json")):
        try:
            data = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        items.append((path, data))
    return items


def request_id(path: Path, data: dict[str, Any]) -> str:
    return str(data.get("id") or path.stem)


def matches_thread(data: dict[str, Any], thread_id: str | None) -> bool:
    if not thread_id:
        return True
    return str(data.get("thread_id") or "") == thread_id


def list_requests(goo_dir: Path, thread_id: str | None, active_only: bool) -> int:
    rows = []
    for path, data in iter_requests(goo_dir):
        status = str(data.get("status") or "pending_model_update")
        if active_only and status not in ACTIVE_STATUSES:
            continue
        if not matches_thread(data, thread_id):
            continue
        rows.append(
            {
                "id": request_id(path, data),
                "path": path.as_posix(),
                "thread_id": data.get("thread_id"),
                "status": status,
                "target_ref": data.get("target_ref") or data.get("target"),
                "title": data.get("title"),
                "claimed_by": data.get("claimed_by"),
            }
        )
    print(json.dumps({"requests": rows}, ensure_ascii=False, indent=2))
    return 0


def set_status(
    path: Path,
    status: str,
    *,
    actor: str | None = None,
    note: str | None = None,
    plan_step_id: str | None = None,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise SystemExit(f"invalid status: {status}")
    data = load_json(path)
    previous = str(data.get("status") or "pending_model_update")
    data["status"] = status
    data["updated_at"] = now()
    history = data.get("history")
    if not isinstance(history, list):
        history = []
    event: dict[str, Any] = {"at": data["updated_at"], "from": previous, "to": status}
    if actor:
        event["actor"] = actor
    if note:
        event["note"] = note
    if plan_step_id:
        data["plan_step_id"] = plan_step_id
        event["plan_step_id"] = plan_step_id
    history.append(event)
    data["history"] = history
    if status == "in_progress" and actor:
        data["claimed_by"] = actor
        data["claimed_at"] = data["updated_at"]
    if status in DONE_STATUSES:
        data["completed_at"] = data["updated_at"]
    dump_json(path, data)
    return data


def claim_requests(goo_dir: Path, thread_id: str | None, actor: str, limit: int) -> int:
    claimed = []
    for path, data in iter_requests(goo_dir):
        status = str(data.get("status") or "pending_model_update")
        if status not in ACTIVE_STATUSES or not matches_thread(data, thread_id):
            continue
        updated = set_status(path, "in_progress", actor=actor)
        claimed.append({"id": request_id(path, updated), "path": path.as_posix(), "thread_id": updated.get("thread_id")})
        if limit and len(claimed) >= limit:
            break
    print(json.dumps({"ok": True, "claimed": claimed}, ensure_ascii=False, indent=2))
    return 0


def resolve_path(goo_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.exists():
        return path
    candidate = requests_dir(goo_dir) / value
    if candidate.exists():
        return candidate
    if not value.endswith(".json"):
        candidate = requests_dir(goo_dir) / f"{value}.json"
        if candidate.exists():
            return candidate
    raise SystemExit(f"request not found: {value}")


def update_request(
    goo_dir: Path,
    request: str,
    status: str,
    actor: str | None,
    note: str | None,
    plan_step_id: str | None,
) -> int:
    path = resolve_path(goo_dir, request)
    data = set_status(path, status, actor=actor, note=note, plan_step_id=plan_step_id)
    print(
        json.dumps(
            {"ok": True, "id": request_id(path, data), "path": path.as_posix(), "status": data.get("status")},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage AutoGoo change requests")
    parser.add_argument("--goo-dir", default=".goo")
    sub = parser.add_subparsers(dest="cmd", required=True)

    list_cmd = sub.add_parser("list")
    list_cmd.add_argument("--thread-id")
    list_cmd.add_argument("--all", action="store_true")

    claim_cmd = sub.add_parser("claim")
    claim_cmd.add_argument("--thread-id")
    claim_cmd.add_argument("--actor", default="main-agent")
    claim_cmd.add_argument("--limit", type=int, default=0)

    status_cmd = sub.add_parser("status")
    status_cmd.add_argument("--request", required=True)
    status_cmd.add_argument("--status", required=True, choices=sorted(VALID_STATUSES))
    status_cmd.add_argument("--actor")
    status_cmd.add_argument("--note")
    status_cmd.add_argument("--plan-step-id")

    args = parser.parse_args()
    goo_dir = find_config_dir(Path(args.goo_dir))
    if args.cmd == "list":
        return list_requests(goo_dir, args.thread_id, not args.all)
    if args.cmd == "claim":
        return claim_requests(goo_dir, args.thread_id, args.actor, args.limit)
    if args.cmd == "status":
        return update_request(goo_dir, args.request, args.status, args.actor, args.note, args.plan_step_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
