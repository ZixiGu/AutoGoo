#!/usr/bin/env python3
"""Render a clear AutoGoo status dashboard from .goo/plan.json."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WIDTH = 88
STALE_SECONDS = 120


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def shorten(value: Any, limit: int = 34) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def bar(percent: int, width: int = 20) -> str:
    percent = max(0, min(100, percent))
    filled = round(width * percent / 100)
    return "█" * filled + "░" * (width - filled)


def output_preview(output: str | None) -> str:
    if not output:
        return "..."
    first = output.split(",")[0].strip()
    path = Path(first)
    if path.exists() and path.is_file():
        try:
            lines = sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore"))
            return f"{lines}行"
        except OSError:
            return "存在"
    return "..."


def step_id(step: dict[str, Any]) -> str:
    value = step.get("id")
    return f"#{value}" if value is not None else "#?"


def dep_names(step: dict[str, Any], steps_by_id: dict[int, dict[str, Any]]) -> str:
    missing = []
    for dep in step.get("depends_on", []):
        dep_step = steps_by_id.get(dep)
        if not dep_step or dep_step.get("status") != "completed":
            missing.append(dep_step.get("name", str(dep)) if dep_step else str(dep))
    if not missing:
        return "就绪"
    if len(missing) > 2:
        return "等待 " + " ".join(missing[:2]) + f" +{len(missing) - 2}"
    return "等待 " + " ".join(missing)


def deps_completed(step: dict[str, Any], steps_by_id: dict[int, dict[str, Any]]) -> bool:
    for dep in step.get("depends_on", []):
        dep_step = steps_by_id.get(dep)
        if not dep_step or dep_step.get("status") != "completed":
            return False
    return True


def status_of(step: dict[str, Any]) -> str:
    return str(step.get("status", "pending") or "pending")


def age_text(dt: datetime | None, now: datetime) -> str:
    if not dt:
        return "无心跳"
    seconds = max(0, int((now - dt).total_seconds()))
    if seconds < 60:
        return f"{seconds}s前"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}min前"
    return f"{minutes // 60}h{minutes % 60:02d}m前"


def print_rule(char: str = "─") -> None:
    print(char * WIDTH)


def print_step_line(prefix: str, step: dict[str, Any], detail: str) -> None:
    name = shorten(step.get("name"), 30)
    print(f"{prefix} {step_id(step):>4}  {name:<30}  {detail}")


def compute_plan_status(data: dict[str, Any], steps: list[dict[str, Any]]) -> str:
    """Compute plan status from steps if not explicitly set."""
    if data.get("status") in ("completed", "failed", "paused"):
        return data["status"]

    total = len(steps)
    if total == 0:
        return "pending"

    completed = sum(1 for s in steps if s.get("status") == "completed")
    failed = sum(1 for s in steps if s.get("status") == "failed")
    blocked = sum(1 for s in steps if s.get("status") == "blocked")
    running = sum(1 for s in steps if s.get("status") == "running")

    if completed == total:
        return "completed"
    if failed > 0 and not running:
        return "failed"
    if blocked > 0 and not running:
        return "blocked"
    if running > 0 or completed > 0:
        return "running"
    return "pending"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render AutoGoo status")
    parser.add_argument("--plan", default=".goo/plan.json", help="plan.json path")
    parser.add_argument("--update-status", action="store_true", help="auto-update plan status")
    args = parser.parse_args()

    plan_path = Path(args.plan)
    if not plan_path.exists():
        raise SystemExit(f"plan not found: {plan_path}")

    data = json.loads(plan_path.read_text(encoding="utf-8"))
    steps = data.get("steps", [])
    steps_by_id = {step.get("id"): step for step in steps if isinstance(step.get("id"), int)}
    now = datetime.now(timezone.utc)

    # Auto-update plan status if requested
    if args.update_status:
        new_status = compute_plan_status(data, steps)
        if data.get("status") != new_status:
            data["status"] = new_status
            if new_status == "running" and not data.get("started_at"):
                data["started_at"] = now.isoformat().replace("+00:00", "Z")
            if new_status in ("completed", "failed"):
                data["completed_at"] = now.isoformat().replace("+00:00", "Z")
            tmp = plan_path.with_suffix(plan_path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tmp.replace(plan_path)

    total = len(steps)
    completed = sum(1 for s in steps if s.get("status") == "completed")
    failed = sum(1 for s in steps if s.get("status") == "failed")
    approval_blocked = [s for s in steps if status_of(s) == "blocked"]
    running = [s for s in steps if status_of(s) == "running"]
    pending = [s for s in steps if status_of(s) == "pending"]
    ready = [s for s in pending if deps_completed(s, steps_by_id)]
    waiting = [s for s in pending if not deps_completed(s, steps_by_id)]
    known_statuses = {"pending", "running", "completed", "failed", "blocked"}
    other = [s for s in steps if status_of(s) not in known_statuses]
    avg = round(sum(int(s.get("progress", 100 if s.get("status") == "completed" else 0) or 0) for s in steps) / total) if total else 0
    task = data.get("task", "AutoGoo")
    plan_status = data.get("status", compute_plan_status(data, steps))
    max_concurrent = data.get("max_concurrent", data.get("execution", {}).get("max_concurrent", 6))

    status_icon = {"pending": "⏳", "running": "▶", "completed": "✅", "failed": "❌", "blocked": "⛔", "paused": "⏸"}.get(plan_status, "?")
    print("╔" + "═" * (WIDTH - 2) + "╗")
    print(f"║ {status_icon} AutoGoo [{plan_status}]  {shorten(task, WIDTH - 38):<{WIDTH - 38}} {completed}/{total:>2} {avg:>3}% ║")
    print("╚" + "═" * (WIDTH - 2) + "╝")
    other_text = f" · other {len(other)}" if other else ""
    print(f"  {bar(avg, 30)}  completed {completed} · running {len(running)} · ready {len(ready)} · waiting {len(waiting)} · blocked {len(approval_blocked)} · failed {failed}{other_text} · slots {len(running)}/{max_concurrent}")

    warnings = []
    for step in steps:
        if status_of(step) == "failed":
            warnings.append(f"{step_id(step)} {step.get('name')} failed: {step.get('error', '见日志')}")
        if status_of(step) == "blocked":
            warnings.append(f"{step_id(step)} {step.get('name')} needs approval: {step.get('error', '见日志')}")
        if status_of(step) == "running":
            hb = parse_time(step.get("heartbeat_at"))
            if not hb:
                warnings.append(f"{step_id(step)} {step.get('name')} running 但没有 heartbeat_at")
            elif (now - hb).total_seconds() >= STALE_SECONDS:
                warnings.append(f"{step_id(step)} {step.get('name')} 无心跳 {age_text(hb, now)}，可能已停止")

    print_rule()
    if warnings:
        print("Next: 先处理告警，再继续调度。")
    elif running:
        print("Next: 等待执行中步骤完成；完成后下游步骤会解锁。")
    elif ready:
        names = " / ".join(f"{step_id(s)} {shorten(s.get('name'), 18)}" for s in ready[:3])
        more = f" +{len(ready) - 3}" if len(ready) > 3 else ""
        print(f"Next: 可立即执行 {names}{more}")
    elif approval_blocked:
        print("Next: 存在权限阻塞，请由主 Agent 前台向用户申请许可。")
    elif waiting:
        print("Next: 暂无就绪步骤，等待前置依赖完成。")
    elif other:
        print("Next: 存在非标准状态步骤，请先检查或规范化 status。")
    else:
        print("Next: 所有步骤已完成。" if completed == total else "Next: 无可调度步骤，请检查 plan。")

    if running:
        print_rule()
        print(f"RUNNING ({len(running)})")
        for step in running:
            progress = int(step.get("progress", 0) or 0)
            hb = parse_time(step.get("heartbeat_at"))
            detail = f"{bar(progress, 16)} {progress:>3}% · output {output_preview(step.get('output'))} · hb {age_text(hb, now)}"
            print_step_line("▶", step, detail)

    if ready:
        print_rule()
        print(f"READY ({len(ready)})")
        for step in ready[:8]:
            detail = f"{step.get('subagent', step.get('type', 'exec'))} · output {shorten(step.get('output'), 36)}"
            print_step_line("▷", step, detail)
        if len(ready) > 8:
            print(f"    ... {len(ready) - 8} more ready")

    if approval_blocked:
        print_rule()
        print(f"NEEDS APPROVAL ({len(approval_blocked)})")
        for step in approval_blocked[:8]:
            detail = shorten(step.get("error", "等待用户授权"), 76)
            print_step_line("⛔", step, detail)
        if len(approval_blocked) > 8:
            print(f"    ... {len(approval_blocked) - 8} more blocked")

    if waiting:
        print_rule()
        print(f"WAITING ({len(waiting)})")
        for step in waiting[:8]:
            print_step_line("⏳", step, dep_names(step, steps_by_id))
        if len(waiting) > 8:
            print(f"    ... {len(waiting) - 8} more waiting")

    done = [s for s in steps if status_of(s) == "completed"]
    if done:
        print_rule()
        print(f"DONE ({len(done)})")
        recent = done[-6:]
        print("  " + " · ".join(f"{step_id(s)} {shorten(s.get('name'), 18)}" for s in recent))
        if len(done) > len(recent):
            print(f"  ... earlier {len(done) - len(recent)} completed")

    if other:
        print_rule()
        print(f"OTHER STATUS ({len(other)})")
        for step in other[:8]:
            detail = f"status={status_of(step)} · {dep_names(step, steps_by_id)}"
            print_step_line("?", step, detail)
        if len(other) > 8:
            print(f"    ... {len(other) - 8} more with non-standard status")

    if warnings:
        print_rule()
        print(f"WARNINGS ({len(warnings)})")
        for item in warnings:
            print(f"  ! {item}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
