#!/usr/bin/env python3
"""Update one AutoGoo plan step status, progress, and heartbeat."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from _paths import (
    compute_plan_status,
    dump_json,
    find_config_dir,
    load_json,
    logs_dir_from_plan,
    now,
    project_root_from_config_dir,
    project_root_from_plan,
    resolve_plan_path,
    workspace_paths,
)


def safe_name(value: Any, limit: int = 48) -> str:
    """Convert a value to a safe filename fragment."""
    text = str(value or "step").strip()
    text = re.sub(r"[^\w.\-]+", "_", text, flags=re.UNICODE).strip("_")
    return (text or "step")[:limit]



def ensure_log_path(plan_path: Path, step: dict[str, Any], stamp: str) -> Path:
    project_root = project_root_from_plan(plan_path)
    logs_dir = logs_dir_from_plan(plan_path)
    logs_dir.mkdir(parents=True, exist_ok=True)

    existing = step.get("log_path")
    if existing:
        existing_path = Path(existing)
        if not existing_path.is_absolute():
            existing_path = project_root / existing_path
        existing_path.parent.mkdir(parents=True, exist_ok=True)
        return existing_path

    timestamp = stamp.replace(":", "-").replace("Z", "")
    filename = f"{timestamp}_step-{safe_name(step.get('id'))}_{safe_name(step.get('name'))}.md"
    log_path = logs_dir / filename
    try:
        stored = log_path.relative_to(project_root).as_posix()
    except ValueError:
        stored = log_path.as_posix()
    step["log_path"] = stored
    return log_path


def log_event(plan_path: Path, step: dict[str, Any], stamp: str, action: str, detail: str | None = None) -> None:
    log_path = ensure_log_path(plan_path, step, stamp)
    is_new = not log_path.exists()
    lines: list[str] = []
    if is_new:
        lines.extend(
            [
                f"# Step {step.get('id')} - {step.get('name', '')}",
                "",
                f"- step_id: {step.get('id')}",
                f"- name: {step.get('name', '')}",
                f"- subagent: {step.get('subagent', '')}",
                f"- task_agent: {step.get('task_agent', '')}",
                f"- started_at: {stamp}",
                "",
                "## Events",
            ]
        )
    progress = step.get("progress")
    status = step.get("status")
    agent = step.get("agent_id", "")
    suffix = f" status={status}"
    if progress is not None:
        suffix += f" progress={progress}"
    if agent:
        suffix += f" agent={agent}"
    if detail:
        suffix += f" detail={detail}"
    lines.append(f"- {stamp} {action}{suffix}")
    if is_new:
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
def update_plan_status(data: dict[str, Any], stamp: str) -> None:
    new_status = compute_plan_status(data)
    old_status = data.get("status")
    if old_status == new_status:
        return
    data["status"] = new_status
    if new_status == "running" and not data.get("started_at"):
        data["started_at"] = stamp
    if new_status in {"completed", "failed"}:
        data["completed_at"] = stamp


def sync_thread(plan_path: Path) -> None:
    script = Path(__file__).with_name("thread-state.py")
    if not script.exists():
        return
    import subprocess

    subprocess.run(
        ["python3", str(script), "sync", "--plan", str(plan_path)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Update .goo/plan.json step state")
    parser.add_argument("--plan", default=".goo/plan.json", help="plan.json path")
    parser.add_argument("--step-id", required=True, help="step id to update")
    parser.add_argument("--status", choices=["pending", "running", "completed", "failed", "blocked"], help="new status")
    parser.add_argument("--progress", type=int, help="progress 0-100")
    parser.add_argument("--agent-id", help="agent id/name")
    parser.add_argument("--error", help="failure summary")
    parser.add_argument("--heartbeat", action="store_true", help="update heartbeat_at")
    parser.add_argument("--start", action="store_true", help="set started_at and heartbeat_at")
    parser.add_argument("--complete", action="store_true", help="set status=completed, progress=100, completed_at")
    parser.add_argument("--fail", action="store_true", help="set status=failed, completed_at, optional error")
    parser.add_argument("--block", action="store_true", help="set status=blocked, optional approval/error summary")
    parser.add_argument("--note", help="append a short step-log note for this update")
    args = parser.parse_args()

    # Mutually exclusive action flags
    _action_flags = [args.start, args.complete, args.fail, args.block]
    if sum(bool(f) for f in _action_flags) > 1:
        raise SystemExit(
            "only one of --start, --complete, --fail, --block may be used at a time"
        )


    plan_path = resolve_plan_path(args.plan)
    data = load_json(plan_path)
    stamp = now()

    target = None
    for step in data.get("steps", []):
        if str(step.get("id")) == args.step_id:
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

    actions = []
    if args.start:
        actions.append("start")
    if args.heartbeat:
        actions.append("heartbeat")
    if args.complete:
        actions.append("complete")
    if args.fail:
        actions.append("fail")
    if args.block:
        actions.append("block")
    if args.status and args.status not in actions:
        actions.append(f"status:{args.status}")
    if args.note and not actions:
        actions.append("note")
    if actions or target.get("status") in {"running", "completed", "failed", "blocked"}:
        log_event(plan_path, target, stamp, "+".join(actions or ["update"]), args.note or args.error)

    update_plan_status(data, stamp)
    dump_json(plan_path, data)
    sync_thread(plan_path)
    print(f"updated step {args.step_id}: status={target.get('status')} progress={target.get('progress')} heartbeat={target.get('heartbeat_at')} log={target.get('log_path', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
