#!/usr/bin/env python3
"""Validate AutoGoo brainstorm JSON artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_TOP_LEVEL = (
    "task",
    "thread",
    "status",
    "wiki_context",
    "global_prerequisites",
    "divergence_axes",
    "candidate_goals",
    "self_check",
    "recommended_goal_ids",
    "decision_needed",
    "review",
    "next_action",
    "archive",
)

REQUIRED_THREAD_FIELDS = ("id", "brainstorm_path", "plan_path", "logs_dir")
REQUIRED_WIKI_FIELDS = ("sources", "signals")
REQUIRED_GOAL_FIELDS = (
    "id",
    "name",
    "why",
    "expected_output",
    "acceptance_criteria",
    "evidence",
    "risk",
    "prerequisites",
    "readiness_checklist",
    "first_step",
    "priority_hint",
)
REQUIRED_SELF_CHECK_FIELDS = (
    "coverage",
    "deduped_or_merged",
    "evidence_gaps",
    "risk_calibration",
    "recommendation_rationale",
)


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"brainstorm file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON: {path}: {exc}") from None
    if not isinstance(data, dict):
        raise SystemExit("brainstorm root must be a JSON object")
    return data


def non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def require_object(errors: list[str], data: dict[str, Any], field: str) -> dict[str, Any]:
    value = data.get(field)
    if not isinstance(value, dict):
        errors.append(f"{field} must be an object")
        return {}
    return value


def require_list(errors: list[str], data: dict[str, Any], field: str) -> list[Any]:
    value = data.get(field)
    if not isinstance(value, list):
        errors.append(f"{field} must be a list")
        return []
    return value


def validate_required_fields(errors: list[str], prefix: str, data: dict[str, Any], required: tuple[str, ...]) -> None:
    for field in required:
        if field not in data:
            errors.append(f"{prefix}.{field} is missing")
        elif not non_empty(data[field]):
            errors.append(f"{prefix}.{field} must not be empty")


def validate_present_fields(errors: list[str], prefix: str, data: dict[str, Any], required: tuple[str, ...]) -> None:
    for field in required:
        if field not in data:
            errors.append(f"{prefix}.{field} is missing")


def validate_candidate_goals(errors: list[str], goals: list[Any]) -> set[str]:
    if not 3 <= len(goals) <= 7:
        errors.append("candidate_goals must contain 3 to 7 final goals")
    goal_ids: set[str] = set()
    for index, raw_goal in enumerate(goals):
        label = f"candidate_goals[{index}]"
        if not isinstance(raw_goal, dict):
            errors.append(f"{label} must be an object")
            continue
        validate_required_fields(errors, label, raw_goal, REQUIRED_GOAL_FIELDS)
        goal_id = str(raw_goal.get("id") or "").strip()
        if not goal_id:
            continue
        if goal_id in goal_ids:
            errors.append(f"{label}.id duplicates goal id {goal_id!r}")
        goal_ids.add(goal_id)
        for list_field in ("acceptance_criteria", "evidence", "prerequisites", "readiness_checklist"):
            if not isinstance(raw_goal.get(list_field), list):
                errors.append(f"{label}.{list_field} must be a list")
    return goal_ids


def validate_divergence_axes(errors: list[str], axes: list[Any], goal_ids: set[str]) -> None:
    if len(axes) < 5:
        errors.append("divergence_axes must cover at least 5 axes")
    used_goal_ids: set[str] = set()
    for index, raw_axis in enumerate(axes):
        label = f"divergence_axes[{index}]"
        if not isinstance(raw_axis, dict):
            errors.append(f"{label} must be an object")
            continue
        validate_required_fields(errors, label, raw_axis, ("axis", "signals", "candidate_goal_ids"))
        if not isinstance(raw_axis.get("signals"), list):
            errors.append(f"{label}.signals must be a list")
        axis_goal_ids = raw_axis.get("candidate_goal_ids")
        if not isinstance(axis_goal_ids, list):
            errors.append(f"{label}.candidate_goal_ids must be a list")
            continue
        for goal_id in axis_goal_ids:
            goal_id_text = str(goal_id)
            used_goal_ids.add(goal_id_text)
            if goal_id_text not in goal_ids:
                errors.append(f"{label}.candidate_goal_ids references unknown goal id {goal_id_text!r}")
    missing = sorted(goal_ids - used_goal_ids)
    if missing:
        errors.append("divergence_axes do not reference candidate goal ids: " + ", ".join(missing))


def validate_recommendations(errors: list[str], recommended: list[Any], goal_ids: set[str]) -> None:
    if not recommended:
        errors.append("recommended_goal_ids must not be empty")
    seen: set[str] = set()
    for raw_goal_id in recommended:
        goal_id = str(raw_goal_id)
        if goal_id in seen:
            errors.append(f"recommended_goal_ids duplicates goal id {goal_id!r}")
        seen.add(goal_id)
        if goal_id not in goal_ids:
            errors.append(f"recommended_goal_ids references unknown goal id {goal_id!r}")


def validate_self_check(errors: list[str], self_check: dict[str, Any], goal_ids: set[str]) -> None:
    validate_present_fields(errors, "self_check", self_check, REQUIRED_SELF_CHECK_FIELDS)
    for field in ("coverage", "recommendation_rationale"):
        if field in self_check and not non_empty(self_check[field]):
            errors.append(f"self_check.{field} must not be empty")
    for list_field in ("deduped_or_merged", "evidence_gaps", "risk_calibration"):
        if not isinstance(self_check.get(list_field), list):
            errors.append(f"self_check.{list_field} must be a list")
    coverage = self_check.get("coverage")
    if not isinstance(coverage, (list, dict, str)):
        errors.append("self_check.coverage must summarize covered axes")
    for field in ("evidence_gaps", "risk_calibration"):
        for index, item in enumerate(self_check.get(field, []) if isinstance(self_check.get(field), list) else []):
            if not isinstance(item, dict):
                continue
            goal_id = item.get("goal_id")
            if goal_id and str(goal_id) not in goal_ids:
                errors.append(f"self_check.{field}[{index}].goal_id references unknown goal id {goal_id!r}")


def validate_review_and_archive(errors: list[str], data: dict[str, Any], mode: str) -> None:
    review = require_object(errors, data, "review")
    archive = require_object(errors, data, "archive")
    review_status = str(review.get("status") or "")
    archive_status = str(archive.get("status") or "")

    if mode == "draft":
        if data.get("status") != "pending_decision":
            errors.append("status must be pending_decision in draft mode")
        if data.get("decision_needed") is not True:
            errors.append("decision_needed must be true in draft mode")
        if review_status != "pending_user_review":
            errors.append("review.status must be pending_user_review in draft mode")
        if archive_status == "completed":
            errors.append("archive.status must not be completed before user confirmation")
    elif mode == "confirmed":
        if review_status != "confirmed":
            errors.append("review.status must be confirmed in confirmed mode")
        if archive_status not in {"pending", "completed", "failed"}:
            errors.append("archive.status must be pending, completed, or failed in confirmed mode")
    elif review_status == "pending_user_review" and archive_status == "completed":
        errors.append("archive.status must not be completed while review.status is pending_user_review")


def validate_brainstorm(data: dict[str, Any], mode: str) -> list[str]:
    errors: list[str] = []
    validate_required_fields(errors, "brainstorm", data, REQUIRED_TOP_LEVEL)

    thread = require_object(errors, data, "thread")
    validate_required_fields(errors, "thread", thread, REQUIRED_THREAD_FIELDS)

    wiki_context = require_object(errors, data, "wiki_context")
    validate_required_fields(errors, "wiki_context", wiki_context, REQUIRED_WIKI_FIELDS)

    if not isinstance(data.get("global_prerequisites"), list):
        errors.append("global_prerequisites must be a list")

    goals = require_list(errors, data, "candidate_goals")
    goal_ids = validate_candidate_goals(errors, goals)

    axes = require_list(errors, data, "divergence_axes")
    validate_divergence_axes(errors, axes, goal_ids)

    recommended = require_list(errors, data, "recommended_goal_ids")
    validate_recommendations(errors, recommended, goal_ids)

    self_check = require_object(errors, data, "self_check")
    validate_self_check(errors, self_check, goal_ids)

    validate_review_and_archive(errors, data, mode)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate AutoGoo brainstorm JSON.")
    parser.add_argument("path", nargs="?", default=".goo/brainstorm.json", help="brainstorm JSON path")
    parser.add_argument("--mode", choices=("draft", "confirmed", "any"), default="any")
    parser.add_argument("--json", action="store_true", help="print machine-readable validation result")
    args = parser.parse_args()

    path = Path(args.path)
    data = load_json(path)
    errors = validate_brainstorm(data, args.mode)
    result = {"ok": not errors, "path": path.as_posix(), "mode": args.mode, "errors": errors}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif errors:
        print(f"brainstorm invalid: {path}")
        for error in errors:
            print(f"- {error}")
    else:
        print(f"brainstorm valid: {path}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
