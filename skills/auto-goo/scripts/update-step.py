#!/usr/bin/env python3
"""Update one AutoGoo plan step status, progress, and heartbeat."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Update .goo/plan.json step state")
    parser.add_argument("--plan", default=".goo/plan.json", help="plan.json path")
    parser.add_argument("--step-id", type=int, required=True, help="step id to update")
    parser.add_argument("--status", choices=["pending", "running", "completed", "failed", "blocked"], help="new status")
    parser.add_argument("--progress", type=int, help="progress 0-100")
    parser.add_argument("--agent-id", help="agent id/name")
    parser.add_argument("--error", help="failure summary")
    parser.add_argument("--heartbeat", action="store_true", help="update heartbeat_at")
    parser.add_argument("--start", action="store_true", help="set started_at and heartbeat_at")
    parser.add_argument("--complete", action="store_true", help="set status=completed, progress=100, completed_at")
    parser.add_argument("--fail", action="store_true", help="set status=failed, completed_at, optional error")
    parser.add_argument("--block", action="store_true", help="set status=blocked, optional approval/error summary")
    args = parser.parse_args()

    plan_path = Path(args.plan)
    data = load_json(plan_path)
    stamp = now()

    target = None
    for step in data.get("steps", []):
        if step.get("id") == args.step_id:
            target = step
            break
    if target is None:
        raise SystemExit(f"step id not found: {args.step_id}")

    if args.start:
        target["status"] = "running"
        target.setdefault("progress", 0)
        target["started_at"] = target.get("started_at") or stamp
        target["heartbeat_at"] = stamp

    if args.complete:
        target["status"] = "completed"
        target["progress"] = 100
        target["heartbeat_at"] = stamp
        target["completed_at"] = stamp

    if args.fail:
        target["status"] = "failed"
        target["completed_at"] = stamp
        target["heartbeat_at"] = stamp
        if args.error:
            target["error"] = args.error

    if args.block:
        target["status"] = "blocked"
        target["blocked_at"] = stamp
        target["heartbeat_at"] = stamp
        if args.error:
            target["error"] = args.error

    if args.status:
        target["status"] = args.status
    if args.progress is not None:
        target["progress"] = max(0, min(100, args.progress))
    if args.agent_id:
        target["agent_id"] = args.agent_id
    if args.heartbeat:
        target["heartbeat_at"] = stamp
    if target.get("status") == "running" and not target.get("heartbeat_at"):
        target["heartbeat_at"] = stamp
    if "progress" not in target:
        target["progress"] = 0 if target.get("status") != "completed" else 100

    dump_json(plan_path, data)
    print(f"updated step {args.step_id}: status={target.get('status')} progress={target.get('progress')} heartbeat={target.get('heartbeat_at')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
