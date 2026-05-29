#!/bin/bash
# AutoGoo: 初始化 plan.json 模板
# Usage: ./scripts/init-plan.sh "<task_description>" [step_count] [--force-new-plan]
#   step_count: 非归档步骤数量，默认 1；脚本会自动追加最后的 Wiki 归档步骤
#   --force-new-plan: 当前 plan 未完成时仍归档旧 plan 并新建

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 \"<task_description>\" [step_count] [--force-new-plan]"
  echo "  step_count: number of non-archive steps (default: 1)"
  echo "  --force-new-plan: archive an unfinished current plan and create a new one"
  exit 1
fi

python3 - "$@" <<'PY'
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


def project_root() -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
        root = result.stdout.strip()
        if root:
            return Path(root)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return Path.cwd()


def archive_existing_plan(plan_file: Path, history_dir: Path) -> Path | None:
    if not plan_file.exists():
        return None
    history_dir.mkdir(parents=True, exist_ok=True)
    base = history_dir / f"plan-{timestamp()}.json"
    archive_file = base
    index = 1
    while archive_file.exists():
        archive_file = history_dir / f"{base.stem}-{index}.json"
        index += 1
    shutil.copy2(plan_file, archive_file)
    return archive_file


def status_of(step: dict[str, Any]) -> str:
    return str(step.get("status", "pending") or "pending")


def is_completed_plan(data: dict[str, Any]) -> bool:
    steps = data.get("steps", [])
    if not isinstance(steps, list) or not steps:
        return data.get("status") == "completed"
    steps_completed = all(isinstance(step, dict) and status_of(step) == "completed" for step in steps)
    plan_status = data.get("status")
    return steps_completed and (plan_status in (None, "", "completed"))


def summarize_unfinished_plan(data: dict[str, Any]) -> str:
    steps = [step for step in data.get("steps", []) if isinstance(step, dict)]
    unfinished = [step for step in steps if status_of(step) != "completed"]
    running = [step for step in unfinished if status_of(step) == "running"]
    failed = [step for step in unfinished if status_of(step) == "failed"]
    pending = [step for step in unfinished if status_of(step) == "pending"]
    paused = [step for step in unfinished if status_of(step) == "paused"]

    def names(items: list[dict[str, Any]]) -> str:
        return ", ".join(f"{step.get('id', '?')} {step.get('name', '(unnamed)')}" for step in items[:3])

    parts = [
        f"current plan status={data.get('status', 'unknown')}",
        f"unfinished_steps={len(unfinished)}/{len(steps)}",
    ]
    for label, items in (("running", running), ("failed", failed), ("paused", paused), ("pending", pending)):
        if items:
            parts.append(f"{label}: {names(items)}")
    return "; ".join(parts)


def guard_existing_plan(plan_file: Path, force_new_plan: bool) -> None:
    if not plan_file.exists():
        return
    try:
        data = json.loads(plan_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"current plan is not valid JSON: {plan_file}: {exc}") from exc
    if is_completed_plan(data):
        return
    if force_new_plan:
        print(f"! current plan is unfinished; --force-new-plan selected. {summarize_unfinished_plan(data)}")
        return
    raise SystemExit(
        "current .goo/plan.json is unfinished; refusing to overwrite it.\n"
        f"{summarize_unfinished_plan(data)}\n"
        "Choose one action first:\n"
        "  1. modify current plan: edit .goo/plan.json and keep existing evidence\n"
        "  2. create new plan: rerun this script with --force-new-plan to archive the old plan first"
    )


def make_step(step_id: int) -> dict[str, Any]:
    output = f".goo/artifacts/step-{step_id}-output.md"
    return {
        "id": step_id,
        "goal_id": "g1",
        "tier": 1,
        "name": f"步骤{step_id}",
        "description": (
            f"步骤{step_id} 描述。请在执行前把本步骤改写为自包含描述，"
            "包含输入、边界、输出和验收点。"
        ),
        "depends_on": [],
        "type": "exec",
        "subagent": "implementer",
        "available_skills": [],
        "status": "pending",
        "progress": 0,
        "output": output,
        "inputs": [],
        "outputs": [output],
        "allowed_read_paths": ["."],
        "allowed_write_paths": [".goo/artifacts/"],
        "validation": "产物存在且满足本步骤描述中的验收点",
        "risk_level": "low",
        "requires_user_confirm": False,
        "agent_id": None,
        "heartbeat_at": None,
        "started_at": None,
        "completed_at": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an AutoGoo .goo/plan.json template")
    parser.add_argument("task", help="task description")
    parser.add_argument("step_count", nargs="?", default="1", help="number of non-archive steps")
    parser.add_argument(
        "--force-new-plan",
        action="store_true",
        help="archive an unfinished current plan and create a new one",
    )
    args = parser.parse_args(sys.argv[1:])

    task = args.task
    try:
        count = int(args.step_count)
    except ValueError as exc:
        raise SystemExit(f"step_count must be an integer: {args.step_count}") from exc
    if count < 1:
        raise SystemExit("step_count must be >= 1")

    root = project_root()
    goo_dir = root / ".goo"
    plan_file = goo_dir / "plan.json"
    history_dir = goo_dir / "plans" / "history"
    goo_dir.mkdir(parents=True, exist_ok=True)

    guard_existing_plan(plan_file, args.force_new_plan)
    archived = archive_existing_plan(plan_file, history_dir)
    if archived:
        print(f"✓ previous plan archived at {archived}")

    steps = [make_step(i) for i in range(1, count + 1)]
    archive_id = count + 1
    archive_output = ".goo/obsidian/<project-slug>/"
    steps.append(
        {
            "id": archive_id,
            "goal_ids": ["g1"],
            "tier": 2,
            "name": "归档到 Goo-wiki",
            "description": (
                "将任务目标、计划、关键证据、产物路径、验证结果、决策和可复用经验"
                "归档到 Goo-wiki；必须补齐任务页、项目入口 <project-slug>.md、log.md、复用知识页"
                "和新增经验页之间的 Wikilink/backlink 关系，防止 Obsidian 连接图谱断裂；"
                "Goo-wiki 不可用时写入 .goo/obsidian/ fallback"
            ),
            "depends_on": [step["id"] for step in steps],
            "type": "archive",
            "subagent": "recorder",
            "available_skills": [],
            "status": "pending",
            "progress": 0,
            "output": archive_output,
            "inputs": [step["output"] for step in steps],
            "outputs": [archive_output],
            "allowed_read_paths": [".goo/plan.json", ".goo/logs/", ".goo/artifacts/"],
            "allowed_write_paths": [".goo/obsidian/"],
            "validation": (
                "归档页或 fallback 笔记存在；任务页链接项目入口、复用的 wiki_context/context_artifacts "
                "和关键概念/问题/指标/历史任务页；项目 <project-slug>.md 与 log.md 反向链接任务页；"
                "新增 concept/lessons/metrics 页也链接回任务页或项目入口；记录产物路径、验证结果和可复用经验"
            ),
            "risk_level": "low",
            "requires_user_confirm": False,
            "agent_id": None,
            "heartbeat_at": None,
            "started_at": None,
            "completed_at": None,
        }
    )

    plan = {
        "task": task,
        "goals": [
            {
                "id": "g1",
                "name": task,
                "description": "默认目标。若任务包含多个交付目标，goo-plan 应改写为多个 goals 并为步骤绑定 goal_id 或 goal_ids。",
                "priority": 1,
                "status": "pending",
                "acceptance_criteria": [],
                "outputs": [],
                "depends_on": [],
            }
        ],
        "status": "pending",
        "created_at": timestamp(),
        "started_at": None,
        "completed_at": None,
        "max_concurrent": 6,
        "wiki_context": {
            "found": False,
            "sources": [],
            "reused_knowledge": [],
        },
        "context_digest": {
            "found": False,
            "decisions": [],
            "constraints": [],
            "acceptance_criteria": [],
            "open_questions": [],
            "post_plan_updates": [],
        },
        "context_artifacts": [],
        "steps": steps,
    }

    plan_file.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✓ plan.json created at {plan_file} ({count} steps + wiki archive)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
