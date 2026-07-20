#!/usr/bin/env python3
"""Publish AutoGoo local workflow state as a static HTML site."""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import math
import re
import socket
import webbrowser
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote


STATUS_CLASS = {
    "completed": "done",
    "running": "running",
    "failed": "failed",
    "paused": "paused",
    "pending": "pending",
    "blocked": "blocked",
}

STATUS_LABEL = {
    "completed": "已完成",
    "running": "运行中",
    "failed": "失败",
    "paused": "已暂停",
    "pending": "待处理",
    "pending_decision": "待决策",
    "blocked": "已阻塞",
}

TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)

DEFAULT_PUBLISH_CONFIG = {
    "enabled": True,
    "site_dir": ".goo/site",
    "index_file": ".goo/site/index.html",
    "host": "127.0.0.1",
    "port": 9877,
    "open_browser": True,
    "include_workflow_activity": True,
    "include_dag": True,
}
DEFAULT_WORKSPACE_PATHS = {
    "threads_dir": ".goo/threads",
    "current_thread_file": ".goo/current_thread.json",
    "compat_plan_file": ".goo/plan.json",
    "compat_brainstorm_file": ".goo/brainstorm.json",
    "plans_history_dir": ".goo/plans/history",
    "brainstorms_history_dir": ".goo/brainstorms/history",
    "logs_dir": ".goo/logs",
    "artifacts_dir": ".goo/artifacts",
    "reports_dir": ".goo/reports",
    "change_requests_dir": ".goo/change-requests",
    "obsidian_dir": ".goo/obsidian",
    "site_dir": ".goo/site",
    "locks_dir": ".goo/locks",
}


def load_observe_module():
    path = Path(__file__).with_name("goo-observe.py")
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("autogoo_plugin_observe", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def parse_time(value: Any, fallback: datetime | None = None) -> datetime | None:
    if not value:
        return fallback
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).astimezone()
    if not isinstance(value, str):
        return fallback
    text = value.strip()
    if not text:
        return fallback
    for candidate in (text, text.replace("Z", "+00:00"), text.replace("_", "T")):
        try:
            return datetime.fromisoformat(candidate).astimezone()
        except ValueError:
            pass
    for fmt in ("%Y-%m-%dT%H-%M-%S", "%Y%m%d-%H%M%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text[: len(fmt)], fmt)
            return parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
        except ValueError:
            pass
    return fallback


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def slug(value: Any, fallback: str = "item") -> str:
    text = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or fallback)).strip("-").lower()
    return text or fallback


def shorten(value: Any, size: int = 96) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= size else text[: size - 1].rstrip() + "..."


def has_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def status_label(value: Any) -> str:
    text = str(value or "pending")
    return STATUS_LABEL.get(text, text)


def render_value(value: Any) -> str:
    if isinstance(value, list):
        if not value:
            return '<span class="muted">无</span>'
        items = "".join(f"<li>{render_value(item)}</li>" for item in value)
        return f'<ul class="detail-list">{items}</ul>'
    if isinstance(value, dict):
        if not value:
            return '<span class="muted">无</span>'
        rows = "".join(
            f"<dt>{esc(key)}</dt><dd>{render_value(item)}</dd>"
            for key, item in value.items()
            if has_value(item)
        )
        empty = '<dd class="muted">无</dd>'
        return f'<dl class="detail-grid nested">{rows or empty}</dl>'
    return esc(value)


def inline_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "无"
    if isinstance(value, dict):
        return ", ".join(str(key) for key in value) if value else "无"
    return str(value) if has_value(value) else "无"


def step_anchor(step_id: Any) -> str:
    return f"step-detail-{slug(step_id, 'step')}"


def step_href(step_id: Any) -> str:
    return f"plan.html#{step_anchor(step_id)}"


def artifact_href(path: Path, root: Path) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return ""
    return f"file/{quote(rel, safe='/._-')}"


def file_href(rel_text: Any) -> str:
    text = str(rel_text or "").strip()
    return f"file/{quote(text, safe='/._-')}" if text else ""


def first_text(value: Any, limit: int = 900) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, indent=2)
    else:
        text = str(value or "")
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "\n..."


def render_fields(data: dict[str, Any], fields: list[tuple[str, str]]) -> str:
    rows = []
    for key, label in fields:
        value = data.get(key)
        if has_value(value):
            display = esc(status_label(value)) if key == "status" else render_value(value)
            rows.append(f"<dt>{esc(label)}</dt><dd>{display}</dd>")
    return f'<dl class="detail-grid">{"".join(rows)}</dl>' if rows else ""


def render_json_section(title: str, value: Any) -> str:
    if not has_value(value):
        return ""
    return f"""
    <section class="detail-section">
      <h3>{esc(title)}</h3>
      {render_value(value)}
    </section>
    """


def fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def load_config(root: Path) -> dict[str, Any]:
    data = read_json(root / ".goo" / "config.json")
    return data if isinstance(data, dict) else {}


def workspace_paths(config: dict[str, Any]) -> dict[str, str]:
    merged = dict(DEFAULT_WORKSPACE_PATHS)
    workspace = config.get("workspace") if isinstance(config.get("workspace"), dict) else {}
    paths = workspace.get("paths") if isinstance(workspace.get("paths"), dict) else {}
    for key, value in paths.items():
        if key in merged and value:
            merged[key] = str(value)
    return merged


def workspace_path(root: Path, config: dict[str, Any], key: str) -> Path:
    raw = Path(workspace_paths(config)[key]).expanduser()
    if raw.is_absolute():
        return raw
    return root / raw


def relative_output_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def publish_config(config: dict[str, Any]) -> dict[str, Any]:
    publish = config.get("publish") if isinstance(config.get("publish"), dict) else {}
    merged = DEFAULT_PUBLISH_CONFIG.copy()
    merged.update(publish)
    return merged


def as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def as_int(value: Any, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def plugin_root() -> Path:
    return Path(__file__).resolve().parents[3]


def publish_template_dir() -> Path:
    return plugin_root() / "skills" / "auto-goo" / "templates" / "publish"


def read_publish_template(name: str) -> str:
    path = publish_template_dir() / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def render_template(name: str, values: dict[str, str]) -> str:
    text = read_publish_template(name)
    if not text:
        raise SystemExit(f"required publish template not found: {name}")
    placeholders = set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", text))
    missing = sorted(placeholders - values.keys())
    if missing:
        raise SystemExit(f"missing values for {name}: {', '.join(missing)}")
    for key in placeholders:
        text = text.replace("{{" + key + "}}", values[key])
    return text


def collect_artifacts(root: Path, config: dict[str, Any], limit: int = 24) -> list[Path]:
    candidates: list[Path] = []
    for key in ("artifacts_dir", "reports_dir", "obsidian_dir", "logs_dir"):
        folder = workspace_path(root, config, key)
        if folder.exists():
            candidates.extend(path for path in folder.rglob("*") if path.is_file())
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[:limit]


def thread_root(root: Path, config: dict[str, Any]) -> Path:
    return workspace_path(root, config, "threads_dir")


def thread_plan_path(root: Path, config: dict[str, Any], thread: dict[str, Any]) -> Path:
    plan_path = thread.get("plan_path")
    if plan_path:
        candidate = root / str(plan_path)
        if candidate.exists():
            return candidate
    thread_id = str(thread.get("id") or "")
    return thread_root(root, config) / thread_id / "plan.json"


def collect_threads(root: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    threads_dir = thread_root(root, config)
    index = read_json(threads_dir / "index.json")
    current = read_json(workspace_path(root, config, "current_thread_file"))
    current_id = current.get("thread_id") if isinstance(current, dict) else None
    rows: list[dict[str, Any]] = []
    if isinstance(index, dict) and isinstance(index.get("threads"), list):
        for item in index["threads"]:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            thread_id = str(item["id"])
            meta = read_json(threads_dir / thread_id / "thread.json")
            thread = meta if isinstance(meta, dict) else item.copy()
            thread.setdefault("id", thread_id)
            thread["is_current"] = thread_id == current_id
            plan = read_json(thread_plan_path(root, config, thread))
            if isinstance(plan, dict):
                thread["plan"] = plan
                thread["plan_stats"] = plan_stats(plan)
            rows.append(thread)
    if not rows:
        plan = read_json(workspace_path(root, config, "compat_plan_file"))
        if isinstance(plan, dict):
            thread_meta = plan.get("thread") if isinstance(plan.get("thread"), dict) else {}
            compat_plan_path = workspace_path(root, config, "compat_plan_file")
            logs_dir = workspace_path(root, config, "logs_dir")
            rows.append(
                {
                    "id": thread_meta.get("id") or "legacy-current",
                    "title": plan.get("task") or plan.get("task_name") or "当前计划",
                    "status": plan.get("status", "pending"),
                    "plan_path": relative_output_path(root, compat_plan_path),
                    "logs_dir": relative_output_path(root, logs_dir),
                    "is_current": True,
                    "plan": plan,
                    "plan_stats": plan_stats(plan),
                }
            )
    rows.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
    return rows


def current_thread_plan(root: Path, config: dict[str, Any]) -> tuple[dict[str, Any] | None, Path | None, dict[str, Any] | None]:
    threads = collect_threads(root, config)
    current = next((item for item in threads if item.get("is_current")), None)
    if current and isinstance(current.get("plan"), dict):
        return current["plan"], thread_plan_path(root, config, current), current
    compat_plan_path = workspace_path(root, config, "compat_plan_file")
    plan = read_json(compat_plan_path)
    if isinstance(plan, dict):
        return plan, compat_plan_path, None
    return None, None, current


def collect_change_requests(root: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    folder = workspace_path(root, config, "change_requests_dir")
    rows: list[dict[str, Any]] = []
    for path in collect_json_files(folder):
        data = read_json(path)
        if isinstance(data, dict):
            data["_path"] = path
            rows.append(data)
    rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return rows


def save_change_request(root: Path, config: dict[str, Any], data: dict[str, Any]) -> Path:
    request = str(data.get("request") or "").strip()
    if not request:
        raise ValueError("request is required")
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    title = shorten(data.get("title") or "change-request", 80)
    payload = {
        "thread_id": str(data.get("thread_id") or ""),
        "target": str(data.get("target") or "plan"),
        "target_ref": str(data.get("target_ref") or ""),
        "title": title,
        "request": request,
        "status": "pending_model_update",
        "source": "autogoo-plugin-publish-web",
        "created_at": created,
    }
    folder = workspace_path(root, config, "change_requests_dir")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{created.replace(':', '-')}_{slug(title, 'request')}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def change_request_path(root: Path, config: dict[str, Any], rel_text: Any) -> Path:
    text = str(rel_text or "").strip()
    if not text:
        raise ValueError("path is required")
    folder = workspace_path(root, config, "change_requests_dir").resolve()
    path = (root / text).resolve() if not Path(text).is_absolute() else Path(text).resolve()
    try:
        path.relative_to(folder)
    except ValueError as exc:
        raise ValueError(f"path must stay inside {relative_output_path(root, folder)}") from exc
    if path.suffix != ".json" or not path.is_file():
        raise ValueError("change request file not found")
    return path


def update_change_request_status(root: Path, config: dict[str, Any], data: dict[str, Any]) -> Path:
    allowed = {"pending_model_update", "needs_revision", "in_progress", "completed", "rejected", "superseded"}
    status = str(data.get("status") or "").strip()
    if status not in allowed:
        raise ValueError(f"status must be one of: {', '.join(sorted(allowed))}")
    path = change_request_path(root, config, data.get("path"))
    item = read_json(path)
    if not isinstance(item, dict):
        raise ValueError("change request json is invalid")
    previous = str(item.get("status") or "")
    transitions = {
        "pending_model_update": {"in_progress", "rejected", "superseded"},
        "needs_revision": {"in_progress", "rejected", "superseded"},
        "in_progress": {"pending_model_update", "needs_revision", "completed", "rejected", "superseded"},
        "completed": set(),
        "rejected": set(),
        "superseded": set(),
    }
    allowed_next = transitions.get(previous, allowed)
    if status not in allowed_next:
        raise ValueError(f"invalid transition: {previous} -> {status}")
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    item["status"] = status
    note = str(data.get("note") or "").strip()
    if note:
        item["status_note"] = note
    item["updated_at"] = now
    history = item.get("history", [])
    if isinstance(history, list):
        history.append({"from": previous, "to": status, "at": now, "note": note or None})
        item["history"] = history
    path.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def collect_json_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(folder.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)


def load_current_or_latest(root: Path, config: dict[str, Any], current_key: str, history_key: str) -> tuple[dict[str, Any] | None, Path | None]:
    current_path = workspace_path(root, config, current_key)
    data = read_json(current_path)
    if isinstance(data, dict):
        return data, current_path
    for path in collect_json_files(workspace_path(root, config, history_key)):
        data = read_json(path)
        if isinstance(data, dict):
            return data, path
    return None, None


def activity_time(path: Path, data: dict[str, Any] | None = None) -> datetime:
    data = data or {}
    for key in ("completed_at", "updated_at", "started_at", "created_at"):
        parsed = parse_time(data.get(key))
        if parsed:
            return parsed
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone()


def add_plan_events(events: list[dict[str, Any]], path: Path, label: str) -> None:
    data = read_json(path)
    if not isinstance(data, dict):
        return
    task = data.get("task") or path.name
    created = activity_time(path, data)
    events.append(
        {
            "time": created,
            "type": label,
            "title": shorten(task),
            "detail": f"{path} · status={data.get('status', 'unknown')}",
            "status": data.get("status", "pending"),
            "path": path,
        }
    )
    for step in data.get("steps", []) if isinstance(data.get("steps"), list) else []:
        if not isinstance(step, dict):
            continue
        when = parse_time(step.get("completed_at") or step.get("started_at") or step.get("heartbeat_at"), created)
        events.append(
            {
                "time": when or created,
                "type": "step",
                "title": f"#{step.get('id', '?')} {shorten(step.get('name'), 72)}",
                "detail": f"{step.get('type', 'step')} · {step.get('output') or ''}",
                "status": step.get("status", "pending"),
                "path": path,
            }
        )


def add_brainstorm_events(events: list[dict[str, Any]], path: Path, label: str) -> None:
    data = read_json(path)
    if not isinstance(data, dict):
        return
    when = activity_time(path, data)
    goals = data.get("candidate_goals") or data.get("goals") or []
    events.append(
        {
            "time": when,
            "type": label,
            "title": shorten(data.get("direction") or data.get("topic") or path.name),
            "detail": f"{path} · {len(goals) if isinstance(goals, list) else 0} candidate goals",
            "status": data.get("status", "pending_decision"),
            "path": path,
        }
    )


def resolve_user_turn(parent_uuid: Any, nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    current = str(parent_uuid or "")
    while current and current not in seen:
        seen.add(current)
        node = nodes.get(current)
        if not node:
            break
        if node.get("type") == "user" and str(node.get("content") or "").strip():
            return node
        current = str(node.get("parentUuid") or "")
    return {}


def message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
    return " ".join(part for part in parts if part)


def usage_token_total(row: dict[str, Any]) -> int:
    return sum(int(row.get(field) or 0) for field in TOKEN_FIELDS)


def collect_token_activity(root: Path, limit: int = 120) -> list[dict[str, Any]]:
    usage_root = Path.home() / ".claude" / "projects"
    if not usage_root.exists():
        return []
    root_resolved = root.resolve()
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(usage_root.glob("**/*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True):
        nodes: dict[str, dict[str, Any]] = {}
        try:
            handle = path.open(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with handle:
            for line in handle:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                uuid = obj.get("uuid")
                if uuid:
                    nodes[str(uuid)] = {
                        "uuid": str(uuid),
                        "parentUuid": obj.get("parentUuid") or "",
                        "type": obj.get("type") or "",
                        "timestamp": obj.get("timestamp") or "",
                        "content": message_text(obj.get("message")),
                    }
                message = obj.get("message") or {}
                usage = message.get("usage") or {}
                if not isinstance(usage, dict) or not usage:
                    continue
                cwd_text = str(obj.get("cwd") or "")
                if not cwd_text:
                    continue
                try:
                    if Path(cwd_text).expanduser().resolve() != root_resolved:
                        continue
                except OSError:
                    continue
                when = parse_time(obj.get("timestamp"))
                if not when:
                    continue
                user_turn = resolve_user_turn(obj.get("parentUuid"), nodes)
                work_content = str(user_turn.get("content") or "").strip()
                work_title = shorten(work_content, 120)
                turn_id = str(user_turn.get("uuid") or obj.get("parentUuid") or obj.get("uuid") or when.isoformat())
                session_id = str(obj.get("sessionId") or "")
                key = (session_id, turn_id)
                row = grouped.setdefault(
                    key,
                    {
                        "time": when,
                        "type": "token-usage",
                        "title": work_title or "Claude Code 工作记录",
                        "detail": "",
                        "work_content": work_content,
                        "status": "completed",
                        "path": root,
                        "tokens": 0,
                        "models": Counter(),
                        "records": 0,
                    },
                )
                if when > row["time"]:
                    row["time"] = when
                total = 0
                for field in TOKEN_FIELDS:
                    amount = _safe_int(usage.get(field))
                    row[field] = int(row.get(field) or 0) + amount
                    total += amount
                row["tokens"] = int(row.get("tokens") or 0) + total
                row["records"] = int(row.get("records") or 0) + 1
                model = str(message.get("model") or "unknown")
                row["models"][model] += total
    events = []
    for row in grouped.values():
        if int(row.get("tokens") or 0) <= 0:
            continue
        models = row.pop("models")
        top_models = ", ".join(name for name, _ in models.most_common(2))
        pieces = [f"{fmt_int(row.get('tokens'))} tokens"]
        if top_models:
            pieces.append(top_models)
        pieces.append(f"{row.get('records', 0)} 条记录")
        usage_detail = " · ".join(pieces)
        row["detail"] = usage_detail
        events.append(row)
    events.sort(key=lambda event: event["time"], reverse=True)
    return events[:limit]


def collect_activity(root: Path, config: dict[str, Any], artifacts: list[Path]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current_plan = workspace_path(root, config, "compat_plan_file")
    current_brainstorm = workspace_path(root, config, "compat_brainstorm_file")
    add_plan_events(events, current_plan, "current-plan")
    add_brainstorm_events(events, current_brainstorm, "current-brainstorm")
    threads_dir = thread_root(root, config)
    for thread in collect_threads(root, config):
        plan_path = thread_plan_path(root, config, thread)
        add_plan_events(events, plan_path, "thread-plan")
        brainstorm_path = threads_dir / str(thread.get("id")) / "brainstorm.json"
        add_brainstorm_events(events, brainstorm_path, "thread-brainstorm")
    for path in collect_json_files(workspace_path(root, config, "plans_history_dir")):
        add_plan_events(events, path, "plan-history")
    for path in collect_json_files(workspace_path(root, config, "brainstorms_history_dir")):
        add_brainstorm_events(events, path, "brainstorm-history")
    for path in artifacts:
        events.append(
            {
                "time": datetime.fromtimestamp(path.stat().st_mtime).astimezone(),
                "type": "artifact",
                "title": path.name,
                "detail": str(path),
                "status": "completed",
                "path": path,
            }
        )
    events.extend(collect_token_activity(root))
    events.sort(key=lambda event: event["time"], reverse=True)
    return events


def plan_stats(plan: dict[str, Any]) -> dict[str, Any]:
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    counter = Counter(step.get("status", "pending") for step in steps if isinstance(step, dict))
    total = len(steps)
    done = counter.get("completed", 0)
    progress = round(done / total * 100) if total else 0
    return {"total": total, "done": done, "progress": progress, "counter": counter}


def token_daily_totals(events: list[dict[str, Any]]) -> dict[date, dict[str, int]]:
    totals: dict[date, dict[str, int]] = defaultdict(lambda: {"tokens": 0, "records": 0, **{field: 0 for field in TOKEN_FIELDS}})
    for event in events:
        if event.get("type") != "token-usage":
            continue
        when = event.get("time")
        if not isinstance(when, datetime):
            continue
        bucket = totals[when.date()]
        bucket["tokens"] += int(event.get("tokens") or 0)
        bucket["records"] += int(event.get("records") or 0)
        for field in TOKEN_FIELDS:
            bucket[field] += int(event.get(field) or 0)
    return totals


def token_summary(events: list[dict[str, Any]]) -> dict[str, int]:
    total = {"tokens": 0, "records": 0}
    for event in events:
        if event.get("type") != "token-usage":
            continue
        total["tokens"] += int(event.get("tokens") or 0)
        total["records"] += int(event.get("records") or 0)
    return total


def token_title(label: str, data: dict[str, int]) -> str:
    parts = [f"{label}: {fmt_int(data.get('tokens'))} tokens", f"{fmt_int(data.get('records'))} 条记录"]
    input_total = int(data.get("input_tokens") or 0) + int(data.get("cache_creation_input_tokens") or 0)
    output_total = int(data.get("output_tokens") or 0)
    cache_read = int(data.get("cache_read_input_tokens") or 0)
    if input_total or output_total or cache_read:
        parts.append(f"输入 {fmt_int(input_total)}")
        parts.append(f"输出 {fmt_int(output_total)}")
        parts.append(f"缓存读取 {fmt_int(cache_read)}")
    return " · ".join(parts)


def token_cell_level(value: int, max_value: int) -> int:
    if value <= 0:
        return 0
    return min(4, max(1, math.ceil(value / max(1, max_value) * 4)))


def activity_date_label(value: date, *, include_year: bool = True) -> str:
    prefix = f"{value.year}年" if include_year else ""
    return f"{prefix}{value.month}月{value.day}日"


def render_token_heatmap(events: list[dict[str, Any]], today: date, *, include_workflow_activity: bool = True) -> str:
    daily = token_daily_totals(events)
    if not daily:
        return """
        <section class="panel token-activity-panel">
          <div class="token-activity-head">
            <h2>Token 活动</h2>
            <span class="muted">当前项目暂无 token 使用记录。</span>
          </div>
        </section>
        """
    start = today - timedelta(days=364)
    start -= timedelta(days=(start.weekday() + 1) % 7)
    days: list[date] = []
    day = start
    while day <= today:
        days.append(day)
        day += timedelta(days=1)
    weekly: dict[date, dict[str, int]] = defaultdict(lambda: {"tokens": 0, "records": 0, **{field: 0 for field in TOKEN_FIELDS}})
    cumulative: dict[date, dict[str, int]] = {}
    running = {"tokens": 0, "records": 0, **{field: 0 for field in TOKEN_FIELDS}}
    for current in days:
        week_start = current - timedelta(days=(current.weekday() + 1) % 7)
        source = daily.get(current, {})
        for field in ("tokens", "records", *TOKEN_FIELDS):
            weekly[week_start][field] += int(source.get(field) or 0)
            running[field] += int(source.get(field) or 0)
        cumulative[current] = running.copy()
    max_daily = max((item["tokens"] for item in daily.values()), default=0)
    max_weekly = max((item["tokens"] for item in weekly.values()), default=0)
    max_cumulative = max((item["tokens"] for item in cumulative.values()), default=0)
    work_by_day: dict[date, list[str]] = defaultdict(list)
    for event in events:
        if event.get("type") != "token-usage" or not isinstance(event.get("time"), datetime):
            continue
        work = " ".join(str(event.get("work_content") or "").split()).lstrip("# ").strip()
        work = work.split("➜", 1)[0].strip()
        lowered = work.lower()
        if not work or lowered.startswith("<task-notification>") or lowered.startswith("/auto-goo:"):
            continue
        if lowered.startswith("html的路径给我一下"):
            work = "确认生成 HTML 的访问路径"
        elif work.startswith("原始参考数据在这"):
            work = "提供原始参考数据用于对照"
        elif work.startswith("我全量生成了数据"):
            work = "完成全量数据生成并记录到 Goo-wiki"
        elif lowered.startswith("整理归档到goo wiki"):
            work = "整理并归档到 Goo-wiki"
        work = work.rstrip("，,；;：: ")
        work = shorten(work, 58)
        if work and work not in work_by_day[event["time"].date()]:
            work_by_day[event["time"].date()].append(work)

    def work_detail(start_day: date, end_day: date) -> list[str]:
        items = []
        current = end_day
        while current >= start_day:
            for work in work_by_day.get(current, []):
                if work not in items:
                    items.append(work)
            current -= timedelta(days=1)
        if not items:
            return ["未从当前项目的 Claude Code 使用记录中识别到具体工作内容。"]
        visible = items[:4]
        if len(items) > 4:
            visible.append(f"另有 {len(items) - 4} 项工作")
        return visible

    def token_cell(
        label: str,
        data: dict[str, int],
        max_value: int,
        work_start: date,
        work_end: date,
    ) -> str:
        level = token_cell_level(int(data.get("tokens") or 0), max_value)
        title = token_title(label, data)
        work_items = json.dumps(work_detail(work_start, work_end), ensure_ascii=False)
        return (
            f'<button type="button" class="token-day l{level}" '
            f'aria-label="{esc(title)}" data-token-detail="{esc(title)}" '
            f'data-token-work-title="{esc(label)}" data-token-work-items="{esc(work_items)}"></button>'
        )

    def daily_cells() -> str:
        output = []
        for current in days:
            output.append(token_cell(activity_date_label(current), daily.get(current, {}), max_daily, current, current))
        weeks = []
        for index in range(0, len(output), 7):
            weeks.append('<div class="token-week">' + "".join(output[index:index + 7]) + "</div>")
        return "".join(weeks)

    def period_cells(mode: str) -> str:
        output = []
        for week_start in days[::7]:
            week_end = min(week_start + timedelta(days=6), today)
            if mode == "weekly":
                data = weekly.get(week_start, {})
                label = f"{activity_date_label(week_start)} - {activity_date_label(week_end, include_year=False)}"
                max_value = max_weekly
            else:
                data = cumulative.get(week_end, {})
                label = f"截至 {activity_date_label(week_end)}"
                max_value = max_cumulative
            work_start = week_start if mode == "weekly" else days[0]
            output.append(token_cell(label, data, max_value, work_start, week_end))
        return "".join(output)

    month_labels = []
    seen: set[tuple[int, int]] = set()
    for index, current in enumerate(days[::7]):
        key = (current.year, current.month)
        if current.day <= 7 and key not in seen:
            seen.add(key)
            month_labels.append(f'<span style="grid-column:{index + 1}">{current.month}月</span>')
    totals = token_summary(events)
    workflow_activity = """
      <section class="panel token-work-panel" data-token-work-panel aria-live="polite">
        <div class="section-head"><h2>工作流活动</h2><time class="token-work-range" data-token-work-range>尚未选择时间段</time></div>
        <ul class="token-work-list" data-token-work-list><li>选择上方 Token 活动格子，查看这段时间实际完成的工作。</li></ul>
      </section>
    """ if include_workflow_activity else ""
    return f"""
    <div data-token-work-widget>
    <section class="panel token-activity-panel" data-token-activity data-active-view="daily">
      <div class="token-activity-head">
        <h2>Token 活动</h2>
        <div class="token-tabs" role="tablist" aria-label="Token 活动视图">
          <button type="button" class="active" data-token-view="daily">每日</button>
          <button type="button" data-token-view="weekly">每周</button>
          <button type="button" data-token-view="cumulative">累计</button>
        </div>
      </div>
      <div class="token-activity-total"><strong>{fmt_int(totals.get('tokens'))}</strong><span>tokens · {fmt_int(totals.get('records'))} 条使用记录</span></div>
      <div class="token-months">{"".join(month_labels)}</div>
      <div class="token-heat-body">
        <div class="token-days"><span>周一</span><span>周三</span><span>周五</span></div>
        <div class="token-views">
          <div class="token-grid active" data-token-panel="daily">{daily_cells()}</div>
          <div class="token-grid token-grid-period" data-token-panel="weekly">{period_cells("weekly")}</div>
          <div class="token-grid token-grid-period" data-token-panel="cumulative">{period_cells("cumulative")}</div>
        </div>
      </div>
      <div class="activity-tooltip" data-token-tooltip role="tooltip" hidden></div>
      <div class="token-legend"><span>少</span><span class="token-day l0"></span><span class="token-day l1"></span><span class="token-day l2"></span><span class="token-day l3"></span><span class="token-day l4"></span><span>多</span></div>
    </section>
    {workflow_activity}
    </div>
    """


def render_dag(plan: dict[str, Any]) -> str:
    steps = [step for step in plan.get("steps", []) if isinstance(step, dict)]
    if not steps:
        return '<section class="panel"><h2>DAG</h2><p class="muted">暂无计划步骤。</p></section>'
    by_id = {str(step.get("id")): step for step in steps}
    visual_tiers = visual_step_tiers(steps)
    tiers: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for step in steps:
        tier = visual_tiers.get(str(step.get("id")), 1)
        tiers[tier].append(step)
    cards = []
    for tier in sorted(tiers):
        items = []
        for step in tiers[tier]:
            deps = step.get("depends_on") if isinstance(step.get("depends_on"), list) else []
            dep_names = [shorten(by_id.get(str(dep), {}).get("name") or dep, 24) for dep in deps]
            status = step.get("status", "pending")
            href = step_href(step.get("id"))
            items.append(
                f"""
                <a class="dag-node {esc(STATUS_CLASS.get(status, 'pending'))}" href="{esc(href)}" aria-label="在计划中查看步骤 #{esc(step.get('id'))}">
                  <div class="node-top"><strong>#{esc(step.get('id'))}</strong><span>{esc(status_label(status))}</span></div>
                  <h3>{esc(shorten(step.get('name'), 64))}</h3>
                  <p>{esc(shorten(step.get('description'), 110))}</p>
                  <small>{esc(step.get('type', 'step'))} · 依赖：{esc(", ".join(dep_names) or "无")}</small>
                </a>
                """
            )
        cards.append(f'<div class="dag-tier"><h3>层级 {tier}</h3>{"".join(items)}</div>')
    return f'<section class="panel"><div class="section-head"><h2>DAG</h2><span>{len(steps)} 个步骤</span></div><div class="dag">{"".join(cards)}</div></section>'


def wrap_svg_text(text: Any, limit: int = 20, lines: int = 3) -> list[str]:
    raw = " ".join(str(text or "").split())
    if not raw:
        return [""]
    chunks: list[str] = []
    current = ""
    for char in raw:
        current += char
        if len(current) >= limit:
            chunks.append(current)
            current = ""
            if len(chunks) == lines:
                break
    if current and len(chunks) < lines:
        chunks.append(current)
    if len(raw) > limit * lines and chunks:
        chunks[-1] = chunks[-1].rstrip(". ") + "..."
    return chunks


def visual_step_tiers(steps: list[dict[str, Any]]) -> dict[str, int]:
    """Compute display tiers that never place a dependency after its dependent."""
    by_id = {str(step.get("id")): step for step in steps}
    tiers: dict[str, int] = {}
    for step in steps:
        step_id = str(step.get("id"))
        tier = step.get("tier")
        if not isinstance(tier, int) or tier < 1:
            deps = step.get("depends_on") if isinstance(step.get("depends_on"), list) else []
            tier = len(deps) + 1
        tiers[step_id] = tier
    for _ in range(max(1, len(steps))):
        changed = False
        for step in steps:
            step_id = str(step.get("id"))
            deps = step.get("depends_on") if isinstance(step.get("depends_on"), list) else []
            dep_tiers = [tiers[str(dep)] for dep in deps if str(dep) in by_id and str(dep) in tiers]
            if not dep_tiers:
                continue
            next_tier = max(tiers.get(step_id, 1), max(dep_tiers) + 1)
            if next_tier != tiers.get(step_id):
                tiers[step_id] = next_tier
                changed = True
        if not changed:
            break
    return tiers


def render_flow_graph(plan: dict[str, Any] | None) -> str:
    if not plan:
        return '<section class="panel"><h2>任务流程</h2><p class="muted">暂无计划步骤。</p></section>'
    steps = [step for step in plan.get("steps", []) if isinstance(step, dict)]
    if not steps:
        return '<section class="panel"><h2>任务流程</h2><p class="muted">暂无计划步骤。</p></section>'

    visual_tiers = visual_step_tiers(steps)
    tiers: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for step in steps:
        tier = visual_tiers.get(str(step.get("id")), 1)
        tiers[tier].append(step)

    node_w, node_h = 96, 44
    x_gap, y_gap = 18, 10
    margin = 8
    max_rows = max(len(items) for items in tiers.values())
    width = margin * 2 + len(tiers) * node_w + (len(tiers) - 1) * x_gap
    height = margin * 2 + max_rows * node_h + (max_rows - 1) * y_gap

    positions: dict[str, tuple[int, int]] = {}
    tier_numbers = sorted(tiers)
    for tier_index, tier in enumerate(tier_numbers):
        items = tiers[tier]
        column_height = len(items) * node_h + (len(items) - 1) * y_gap
        y_start = margin + max(0, (height - margin * 2 - column_height) // 2)
        x = margin + tier_index * (node_w + x_gap)
        for row, step in enumerate(items):
            positions[str(step.get("id"))] = (x, y_start + row * (node_h + y_gap))

    lines = []
    nodes = []
    for step in steps:
        step_id = str(step.get("id"))
        x, y = positions.get(step_id, (margin, margin))
        deps = step.get("depends_on") if isinstance(step.get("depends_on"), list) else []
        for dep in deps:
            dep_pos = positions.get(str(dep))
            if not dep_pos:
                continue
            x1, y1 = dep_pos[0] + node_w, dep_pos[1] + node_h // 2
            x2, y2 = x, y + node_h // 2
            mid = x1 + max(24, (x2 - x1) // 2)
            lines.append(
                f'<path class="flow-edge" d="M{x1},{y1} C{mid},{y1} {mid},{y2} {x2 - 9},{y2}" '
                'fill="none" marker-end="url(#arrow)" />'
            )
        status = step.get("status", "pending")
        cls_color = {
            "completed": "#30a14e",
            "running": "#0969da",
            "failed": "#cf222e",
            "paused": "#bc4c00",
        }.get(str(status), "#8c959f")
        href = step_href(step_id)
        title_lines = wrap_svg_text(step.get("name"), 11, 2)
        text_lines = "".join(
            f'<text x="{x + 7}" y="{y + 20 + index * 9}" class="flow-title">{esc(line)}</text>'
            for index, line in enumerate(title_lines)
        )
        nodes.append(
            f"""
            <a class="flow-node-link" href="{esc(href)}" aria-label="查看步骤 #{esc(step.get('id'))} 详情">
              <g class="flow-node {esc(STATUS_CLASS.get(status, 'pending'))}">
                <rect x="{x}" y="{y}" width="{node_w}" height="{node_h}" rx="5" fill="#ffffff" stroke="#d0d7de" />
                <rect x="{x}" y="{y}" width="4" height="{node_h}" rx="2" fill="{cls_color}" />
                <text x="{x + 7}" y="{y + 11}" class="flow-meta">#{esc(step.get('id'))} · {esc(status_label(status))}</text>
                {text_lines}
                <text x="{x + 7}" y="{y + node_h - 5}" class="flow-meta">{esc(step.get('type', 'step'))}</text>
              </g>
            </a>
            """
        )

    thread = plan.get("thread") if isinstance(plan.get("thread"), dict) else {}
    thread_label = thread.get("id") or plan.get("thread_id") or "current"
    return f"""
    <section class="panel flow-panel">
      <div class="section-head"><h2>任务流程</h2><span>{esc(thread_label)} · {len(steps)} 个步骤</span></div>
      <div class="flow-scroll">
        <svg class="flow-svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="AutoGoo 任务流程图">
          <defs>
            <marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="4" orient="auto" markerUnits="strokeWidth">
              <path class="flow-arrow" d="M0,0 L0,8 L11,4 z" />
            </marker>
          </defs>
          {''.join(lines)}
          {''.join(nodes)}
        </svg>
      </div>
    </section>
    """


def render_plan(plan: dict[str, Any] | None, *, include_dag: bool = True) -> str:
    if not plan:
        return '<section class="panel"><h2>当前计划</h2><p class="muted">未找到 .goo/plan.json。</p></section>'
    stats = plan_stats(plan)
    counter = stats["counter"]
    status = plan.get("status", "pending")
    chips = "".join(
        f'<span class="chip {esc(STATUS_CLASS.get(name, "pending"))}">{esc(status_label(name))} {count}</span>'
        for name, count in sorted(counter.items())
    )
    goals = plan.get("goals") if isinstance(plan.get("goals"), list) else []
    goal_cards = []
    for goal in goals:
        if not isinstance(goal, dict):
            continue
        goal_anchor = f"goal-{slug(goal.get('id') or goal.get('name'), 'goal')}"
        goal_cards.append(
            f"""
            <article id="{esc(goal_anchor)}" class="detail-card">
              <div class="node-top"><strong>{esc(goal.get("id", "goal"))}</strong><span>{esc(goal.get("priority") or goal.get("priority_hint") or "")}</span></div>
              <h3>{esc(goal.get("name") or goal.get("description") or "目标")}</h3>
              {render_fields(goal, [
                  ("description", "说明"),
                  ("why", "原因"),
                  ("expected_output", "预期输出"),
                  ("outputs", "输出"),
                  ("acceptance_criteria", "验收标准"),
                  ("evidence", "证据"),
                  ("risk", "风险"),
                  ("prerequisites", "前置条件"),
                  ("readiness_checklist", "准备清单"),
                  ("first_step", "第一步"),
              ])}
            </article>
            """
        )
    step_cards = []
    steps = [step for step in plan.get("steps", []) if isinstance(step, dict)]
    for step in steps:
        step_id = step.get("id")
        step_status = step.get("status", "pending")
        anchor = step_anchor(step_id)
        goal_ref = step.get("goal_id") or step.get("goal_ids")
        agent = " / ".join(str(item) for item in (step.get("subagent"), step.get("task_agent")) if item)
        step_cards.append(
            f"""
            <article id="{esc(anchor)}" class="step-detail {esc(STATUS_CLASS.get(step_status, 'pending'))}">
              <div class="node-top"><strong>#{esc(step_id)} {esc(step.get("name", "步骤"))}</strong><span class="status {esc(STATUS_CLASS.get(step_status, "pending"))}">{esc(status_label(step_status))}</span></div>
              <p>{esc(step.get("description", ""))}</p>
              <div class="step-meta">
                <span><strong>目标</strong> {esc(inline_value(goal_ref))}</span>
                <span><strong>代理</strong> {esc(agent or "未分配")}</span>
                <span><strong>进度</strong> {esc(step.get("progress", 0))}%</span>
                <span><strong>依赖</strong> {esc(inline_value(step.get("depends_on")))}</span>
              </div>
              {render_fields(step, [
                  ("agent_id", "代理 ID"),
                  ("type", "类型"),
                  ("available_skills", "可用技能"),
                  ("inputs", "输入"),
                  ("outputs", "输出"),
                  ("allowed_read_paths", "允许读取路径"),
                  ("allowed_write_paths", "允许写入路径"),
                  ("validation", "验证"),
                  ("requires_user_confirm", "需要用户确认"),
                  ("started_at", "开始时间"),
                  ("heartbeat_at", "心跳时间"),
                  ("completed_at", "完成时间"),
                  ("blocked_at", "阻塞时间"),
                  ("error", "错误"),
                  ("block_reason", "阻塞原因"),
                  ("approval_request", "审批请求"),
                  ("notes", "备注"),
              ])}
            </article>
            """
        )
    top_fields = render_fields(
        plan,
        [
            ("thread", "Thread"),
            ("version", "版本"),
            ("task_name", "任务名称"),
            ("task", "任务"),
            ("status", "状态"),
            ("started_at", "开始时间"),
            ("updated_at", "更新时间"),
            ("completed_at", "完成时间"),
        ],
    )
    return f"""
    <section class="panel">
      <div class="section-head"><h2>当前计划</h2><span class="status {esc(STATUS_CLASS.get(status, "pending"))}">{esc(status_label(status))}</span></div>
      <h3>{esc(plan.get("task") or plan.get("task_name") or "未命名 AutoGoo 任务")}</h3>
      <div class="progress"><span style="width:{stats['progress']}%"></span></div>
      <p class="muted">已完成 {stats['done']}/{stats['total']} 个步骤 · {stats['progress']}%</p>
      <div class="chips">{chips}</div>
      {top_fields}
      {render_json_section("上下文摘要", plan.get("context_digest"))}
      {render_json_section("Wiki 上下文", plan.get("wiki_context"))}
      {render_json_section("上下文产物", plan.get("context_artifacts"))}
      {render_json_section("审阅", plan.get("review"))}
      {render_json_section("归档", plan.get("archive"))}
    </section>
    <section class="panel">
      <div class="section-head"><h2>目标</h2><span>{len(goal_cards)} 个目标</span></div>
      <div class="detail-card-grid">{''.join(goal_cards) or '<p class="muted">暂无目标记录。</p>'}</div>
    </section>
    <section class="panel">
      <div class="section-head"><h2>计划步骤</h2><span>{len(step_cards)} 个步骤</span></div>
      <div class="step-detail-list">{''.join(step_cards) or '<p class="muted">暂无计划步骤。</p>'}</div>
    </section>
    {render_flow_graph(plan)}
    {render_dag(plan) if include_dag else ""}
    """


def render_status(plan: dict[str, Any] | None, _events: list[dict[str, Any]]) -> str:
    if not plan:
        return '<section class="panel"><h2>运行状态</h2><p class="muted">未找到 .goo/plan.json。</p></section>'
    stats = plan_stats(plan)
    steps = [step for step in plan.get("steps", []) if isinstance(step, dict)]
    chips = "".join(
        f'<a class="status-card pixel-card" href="plan.html"><span>{esc(status_label(name))}</span><strong>{count}</strong></a>'
        for name, count in sorted(stats["counter"].items())
    )
    pixel_cells = "".join(
        f'<a class="pixel-step {esc(STATUS_CLASS.get(step.get("status"), "pending"))}" href="{esc(step_href(step.get("id")))}" title="Step #{esc(step.get("id"))} · {esc(step.get("name"))}"><span>{esc(step.get("id"))}</span></a>'
        for step in steps
    )
    rows = []
    for step in steps:
        status = step.get("status", "pending")
        href = step_href(step.get("id"))
        when = step.get("heartbeat_at") or step.get("started_at") or step.get("completed_at") or ""
        rows.append(
            f"""
            <a class="status-row pixel-row" href="{esc(href)}">
              <span class="dot {esc(STATUS_CLASS.get(status, 'pending'))}"></span>
              <strong>#{esc(step.get('id'))} {esc(shorten(step.get('name'), 72))}</strong>
              <span>{esc(status_label(status))}</span>
              <code>{esc(when or step.get('type', 'step'))}</code>
            </a>
            """
        )
    return f"""
    <section class="panel pixel-status-panel">
      <div class="section-head"><h2>运行状态</h2><span>已完成 {stats['done']}/{stats['total']} · {stats['progress']}%</span></div>
      <div class="pixel-progress" aria-label="计划进度 {stats['progress']}%">
        <span style="width:{stats['progress']}%"></span>
      </div>
      <div class="pixel-board" aria-label="步骤状态格子">{pixel_cells or '<span class="muted">暂无步骤。</span>'}</div>
      <div class="status-grid">{chips or '<span class="muted">暂无步骤状态记录。</span>'}</div>
      <div class="status-list">{''.join(rows) or '<p class="muted">暂无计划步骤。</p>'}</div>
    </section>
    """


def render_observe(observe: dict[str, Any]) -> str:
    running = observe.get("running") if isinstance(observe.get("running"), list) else []
    blocked = observe.get("blocked") if isinstance(observe.get("blocked"), list) else []
    failed = observe.get("failed") if isinstance(observe.get("failed"), list) else []
    shell_logs = observe.get("shell_logs") if isinstance(observe.get("shell_logs"), list) else []
    commands = observe.get("commands") if isinstance(observe.get("commands"), dict) else {}

    def step_card(item: dict[str, Any]) -> str:
        status = str(item.get("status") or "pending")
        tail_lines = item.get("log_tail") if isinstance(item.get("log_tail"), list) else []
        tail_html = "".join(f"<li>{esc(shorten(line, 150))}</li>" for line in tail_lines[-6:])
        return f"""
        <article class="observe-step {esc(STATUS_CLASS.get(status, 'pending'))}">
          <div class="node-top">
            <strong>#{esc(item.get('id'))} {esc(shorten(item.get('name'), 72))}</strong>
            <span class="chip {esc(STATUS_CLASS.get(status, 'pending'))}">{esc(status_label(status))}</span>
          </div>
          <div class="progress"><span style="width:{esc(item.get('progress') or 0)}%"></span></div>
          <div class="step-meta">
            <span><strong>进度</strong>{esc(item.get('progress') or 0)}%</span>
            <span><strong>Heartbeat</strong>{esc(item.get('heartbeat_age') or '无心跳')}</span>
            <span><strong>Agent</strong>{esc(item.get('subagent') or '未指定')} / {esc(item.get('task_agent') or '未指定')}</span>
            <span><strong>Agent ID</strong><code>{esc(item.get('agent_id') or '无')}</code></span>
            <span><strong>Log</strong><code>{esc(item.get('log_path') or '无')}</code></span>
            <span><strong>Output</strong><code>{esc(item.get('output') or '无')}</code></span>
          </div>
          <div class="observe-log-tail">
            <strong>最近日志</strong>
            <ul>{tail_html or '<li class="muted">暂无日志尾部。</li>'}</ul>
          </div>
        </article>
        """

    attention = blocked + failed
    shell_items = []
    for item in shell_logs[:8]:
        lines = item.get("tail") if isinstance(item.get("tail"), list) else []
        shell_items.append(
            f"""
            <article class="observe-shell-log">
              <div class="node-top"><strong><code>{esc(item.get('path'))}</code></strong><span>{len(lines)} 行尾部</span></div>
              <ul>{''.join(f'<li>{esc(shorten(line, 150))}</li>' for line in lines) or '<li class="muted">暂无输出。</li>'}</ul>
            </article>
            """
        )

    return f"""
    <section class="panel observe-hero">
      <div class="section-head"><h2>后台观察</h2><span>Agent View + AutoGoo step heartbeat</span></div>
      <div class="observe-grid">
        <div class="observe-card">
          <span class="muted">Claude Code</span>
          <strong>{esc(observe.get('claude_version') or '未检测到')}</strong>
          <p>使用 <code>{esc(commands.get('agent_view') or 'claude agents')}</code> 查看后台 session / shell job。</p>
        </div>
        <div class="observe-card">
          <span class="muted">当前 Thread</span>
          <strong>{esc((observe.get('current_thread') or {}).get('id') or 'legacy/current')}</strong>
          <p><code>{esc(observe.get('plan_path') or '未找到 plan')}</code></p>
        </div>
        <div class="observe-card">
          <span class="muted">运行中 Step</span>
          <strong>{len(running)}</strong>
          <p>内部 subagent 不会单独出现在 Agent View 行里，细节看这里。</p>
        </div>
        <div class="observe-card">
          <span class="muted">需处理</span>
          <strong>{len(attention)}</strong>
          <p>blocked / failed step。</p>
        </div>
      </div>
    </section>
    <section class="panel observe-command-panel">
      <div class="section-head"><h2>Agent View 与 Shell</h2><span>快速入口</span></div>
      <div class="observe-command-grid">
        <div><strong>后台会话</strong><code>{esc(commands.get('agent_view') or 'claude agents')}</code><p>Space peek，Enter/Right attach。</p></div>
        <div><strong>AutoGoo 状态</strong><code>{esc(commands.get('status') or '/auto-goo:goo-status')}</code><p>查看 per-step progress、heartbeat 和告警。</p></div>
        <div><strong>Live 发布</strong><code>{esc(commands.get('publish_live') or '/auto-goo:goo-publish --live')}</code><p>刷新页面时重新扫描 .goo 状态。</p></div>
        <div><strong>Shell 留痕</strong><code>{esc(commands.get('shell_template') or '')}</code><p>长任务输出写入 shell log，避免 Agent View 临时输出被清理。</p></div>
      </div>
    </section>
    <section class="panel">
      <div class="section-head"><h2>Running Steps</h2><span>{len(running)} 个</span></div>
      <div class="observe-step-list">{''.join(step_card(item) for item in running) or '<p class="muted">暂无运行中的 AutoGoo step。</p>'}</div>
    </section>
    <section class="panel">
      <div class="section-head"><h2>Blocked / Failed</h2><span>{len(attention)} 个</span></div>
      <div class="observe-step-list">{''.join(step_card(item) for item in attention) or '<p class="muted">暂无阻塞或失败。</p>'}</div>
    </section>
    <section class="panel">
      <div class="section-head"><h2>Shell Logs</h2><span>{len(shell_logs)} 个</span></div>
      <p class="muted">Shell 日志目录：<code>{esc(observe.get('shell_log_dir') or '')}</code></p>
      <div class="observe-shell-list">{''.join(shell_items) or '<p class="muted">暂无 shell 日志。</p>'}</div>
    </section>
    """


def render_threads(threads: list[dict[str, Any]], root: Path) -> str:
    cards = []
    for thread in threads:
        stats = thread.get("plan_stats") if isinstance(thread.get("plan_stats"), dict) else {"total": 0, "done": 0, "progress": 0}
        status = str(thread.get("status") or (thread.get("plan") or {}).get("status") or "pending")
        current = '<span class="chip running">当前</span>' if thread.get("is_current") else ""
        thread_id = str(thread.get("id") or "")
        plan_href = "plan.html" if thread.get("is_current") else file_href(thread.get("plan_path"))
        plan = thread.get("plan") if isinstance(thread.get("plan"), dict) else {}
        step_links = []
        for step in plan.get("steps", []) if isinstance(plan.get("steps"), list) else []:
            if not isinstance(step, dict):
                continue
            step_status = str(step.get("status") or "pending")
            href = step_href(step.get("id")) if thread.get("is_current") else plan_href
            step_links.append(
                f"""
                <a class="thread-step {esc(STATUS_CLASS.get(step_status, 'pending'))}" href="{esc(href)}" title="Step #{esc(step.get('id'))} · {esc(step.get('name'))}">
                  <span>{esc(step.get('id'))}</span>
                </a>
                """
            )
        cards.append(
            f"""
            <article class="thread-card {esc(STATUS_CLASS.get(status, 'pending'))}">
              <div class="node-top"><strong>{esc(thread.get('title') or thread_id)}</strong><span>{current}<a class="thread-plan-link" href="{esc(plan_href)}">打开 plan</a></span></div>
              <p><code>{esc(thread_id)}</code></p>
              <div class="progress"><span style="width:{esc(stats.get('progress', 0))}%"></span></div>
              <div class="thread-step-strip">{''.join(step_links) or '<span class="muted">暂无步骤。</span>'}</div>
              <div class="step-meta">
                <span><strong>状态</strong>{esc(status_label(status))}</span>
                <span><strong>步骤</strong>{esc(stats.get('done', 0))}/{esc(stats.get('total', 0))}</span>
                <span><strong>Plan</strong><code>{esc(thread.get('plan_path') or '')}</code></span>
                <span><strong>Logs</strong><code>{esc(thread.get('logs_dir') or '')}</code></span>
              </div>
              {render_fields(thread, [
                  ("created_at", "创建时间"),
                  ("updated_at", "更新时间"),
                  ("started_at", "开始时间"),
                  ("completed_at", "完成时间"),
                  ("archive", "归档"),
              ])}
            </article>
            """
        )
    return f"""
    <section class="panel">
      <div class="section-head"><h2>Threads</h2><span>{len(threads)} 条任务线</span></div>
      <div class="thread-list">{''.join(cards) or '<p class="muted">暂无 thread 记录。</p>'}</div>
    </section>
    """


def request_context_cards(
    plan: dict[str, Any] | None,
    brainstorm: dict[str, Any] | None,
    artifacts: list[Path],
    root: Path,
    threads: list[dict[str, Any]],
) -> str:
    current_thread_id = str(
        ((plan or {}).get("thread") or {}).get("id")
        if isinstance((plan or {}).get("thread"), dict)
        else (plan or {}).get("thread_id") or ""
    )
    if not current_thread_id:
        current = next((thread for thread in threads if thread.get("is_current")), None)
        current_thread_id = str((current or {}).get("id") or "legacy-current")
    plan_contexts: list[tuple[str, str, dict[str, Any]]] = []
    seen_threads: set[str] = set()
    if plan:
        plan_contexts.append((current_thread_id, "当前", plan))
        seen_threads.add(current_thread_id)
    for thread in threads:
        thread_id = str(thread.get("id") or "")
        thread_plan = thread.get("plan")
        if not thread_id or thread_id in seen_threads or not isinstance(thread_plan, dict):
            continue
        plan_contexts.append((thread_id, shorten(thread.get("title") or thread_id, 34), thread_plan))
        seen_threads.add(thread_id)
    step_rows = []
    plan_rows = []
    for thread_id, thread_label, thread_plan in plan_contexts:
        plan_summary = first_text(
            {
                "thread_id": thread_id,
                "task": thread_plan.get("task") or thread_plan.get("task_name"),
                "thread": thread_plan.get("thread"),
                "status": thread_plan.get("status"),
                "context_digest": thread_plan.get("context_digest"),
            },
            1400,
        )
        plan_ref = f"Thread {thread_id} · Plan"
        plan_rows.append(
            f"""
            <button class="request-reference request-context-card request-select-card" type="button" data-request-context="plan-step" data-request-thread="{esc(thread_id)}" data-target-ref="{esc(plan_ref)}">
              <div class="node-top"><strong>{esc(thread_label)} Plan 摘要</strong><span>{esc(thread_id)}</span></div>
              <pre>{esc(plan_summary or '暂无 plan 内容。')}</pre>
            </button>
            """
        )
        steps = [step for step in thread_plan.get("steps", []) if isinstance(step, dict)]
        for step in steps:
            label = f"Thread {thread_id} · Step #{step.get('id')} · {shorten(step.get('name'), 72)}"
            reference = first_text(
                {
                    "thread_id": thread_id,
                    "id": step.get("id"),
                    "name": step.get("name"),
                    "status": step.get("status"),
                    "type": step.get("type"),
                    "description": step.get("description"),
                    "depends_on": step.get("depends_on"),
                    "acceptance": step.get("acceptance") or step.get("acceptance_criteria"),
                },
                700,
            )
            step_rows.append(
                f"""
                <button class="request-context-card request-select-card" type="button" data-request-context="plan-step" data-request-thread="{esc(thread_id)}" data-target-ref="{esc(label)}">
                  <span>{esc(thread_id)} · Step #{esc(step.get('id'))} · {esc(status_label(step.get('status')))}</span>
                  <strong>{esc(shorten(step.get('name'), 72))}</strong>
                  <p>{esc(shorten(step.get('description'), 150))}</p>
                </button>
                """
            )
    artifact_rows = []
    for path in artifacts[:12]:
        try:
            rel = path.relative_to(root)
        except ValueError:
            rel = path
        href = artifact_href(path, root)
        label = f"Artifact · {rel.as_posix() if isinstance(rel, Path) else rel}"
        reference = first_text({"path": label, "size": path.stat().st_size}, 360)
        artifact_rows.append(
            f"""
            <button class="request-context-card artifact-context request-select-card" type="button" data-request-context="artifact" data-request-thread="*" data-target-ref="{esc(label)}" data-open-href="{esc(href)}">
              <span>Artifact</span>
              <strong>{esc(shorten(rel, 86))}</strong>
              <p>{path.stat().st_size:,} bytes · 双击打开</p>
            </button>
            """
        )
    brainstorm_summary = first_text(
        {
            "direction": (brainstorm or {}).get("direction"),
            "topic": (brainstorm or {}).get("topic"),
            "task": (brainstorm or {}).get("task"),
            "selected_goal_id": (brainstorm or {}).get("selected_goal_id"),
            "candidate_goals": (brainstorm or {}).get("candidate_goals") or (brainstorm or {}).get("goals"),
        },
        1400,
    )
    context_thread_options = []
    for thread in threads:
        selected = " selected" if thread.get("is_current") else ""
        context_thread_options.append(
            f'<option value="{esc(thread.get("id"))}"{selected}>{esc(thread.get("id"))} · {esc(shorten(thread.get("title"), 46))}</option>'
        )
    return f"""
    <section class="panel request-context-panel">
      <div class="section-head"><h2>选择修改目标</h2><span>点击一个卡片作为本次要修改的目标</span></div>
      <div class="request-context-filters">
        <label>Thread<select data-context-thread-filter>{''.join(context_thread_options) or '<option value="">当前 thread</option>'}</select></label>
        <label>目标<select data-context-target-filter>
          <option value="plan-step">Plan / Step</option>
          <option value="brainstorm">Brainstorm</option>
          <option value="artifact">Artifact</option>
          <option value="other">Other</option>
        </select></label>
      </div>
      <div class="selected-target-bar" aria-live="polite">
        <strong>当前修改目标</strong>
        <span class="selected-target-value is-empty" data-selected-target-display>未选择修改目标</span>
      </div>
      <div class="request-context-layout">
        <div class="request-reference-stack">
          {''.join(plan_rows) or '<p class="muted">暂无 plan 内容。</p>'}
          <button class="request-reference request-context-card request-select-card" type="button" data-request-context="brainstorm" data-request-thread="*" data-target-ref="当前 Brainstorm 摘要">
            <div class="node-top"><strong>当前 Brainstorm 摘要</strong><span>点击设为目标</span></div>
            <pre>{esc(brainstorm_summary or '暂无 brainstorm 内容。')}</pre>
          </button>
        </div>
        <div class="request-reference-list">
          <div class="request-context-group" data-request-context="plan-step">
            <h3>步骤详情</h3>
            <div class="request-context-grid">{''.join(step_rows) or '<p class="muted">暂无步骤。</p>'}</div>
          </div>
          <div class="request-context-group" data-request-context="artifact">
            <h3>最近产物</h3>
            <div class="request-context-grid">{''.join(artifact_rows) or '<p class="muted">暂无产物。</p>'}</div>
          </div>
        </div>
      </div>
    </section>
    """


def render_change_requests(
    requests: list[dict[str, Any]],
    threads: list[dict[str, Any]],
    plan: dict[str, Any] | None,
    brainstorm: dict[str, Any] | None,
    artifacts: list[Path],
    root: Path,
) -> str:
    current_thread = next((thread for thread in threads if thread.get("is_current")), None) or (threads[0] if threads else {})
    current_thread_id = str(current_thread.get("id") or "")
    rows = []
    for item in requests:
        request_path = str(item.get("_path") or "")
        try:
            request_rel = Path(request_path).relative_to(root).as_posix()
        except (ValueError, TypeError):
            request_rel = request_path
        status = str(item.get("status") or "pending_model_update")
        continue_command = f"/auto-goo:goo-continue  # 处理 {request_rel}"
        rows.append(
            f"""
            <article class="request-card" data-request-card data-request-path="{esc(request_rel)}">
              <div class="node-top"><strong>{esc(item.get('title') or item.get('target') or '修改请求')}</strong><span data-request-status>{esc(status)}</span></div>
              <p>{esc(item.get('request') or item.get('note') or '')}</p>
              <div class="step-meta">
                <span><strong>Thread</strong><code>{esc(item.get('thread_id') or '')}</code></span>
                <span><strong>目标</strong>{esc(item.get('target') or '')}</span>
                <span><strong>修改目标</strong>{esc(item.get('target_ref') or '')}</span>
                <span><strong>文件</strong><code>{esc(request_rel)}</code></span>
              </div>
              <div class="request-next-step">
                <strong>下一步</strong>
                <code>{esc(continue_command)}</code>
              </div>
              <div class="request-card-actions">
                <button type="button" data-copy-continue="{esc(continue_command)}">复制继续命令</button>
                <button type="button" data-update-request-status="completed">标记完成</button>
                <button type="button" data-update-request-status="needs_revision">标记需修改</button>
              </div>
            </article>
            """
        )
    return f"""
    {request_context_cards(plan, brainstorm, artifacts, root, threads)}
    <section class="panel request-panel">
      <div class="section-head"><h2>修改请求</h2><span>提交后由 AutoGoo 读取并让模型修改</span></div>
      <form class="request-form" data-change-request-form>
        <input type="hidden" name="thread_id" value="{esc(current_thread_id)}">
        <input type="hidden" name="target" value="plan-step">
        <input type="hidden" name="target_ref" data-target-ref-field>
        <p class="wide request-scope-note">Thread、目标类型和具体修改目标在上方选择；这里专注填写修改内容。</p>
        <label class="wide target-ref-label">修改目标<input data-selected-target data-selected-target-display readonly placeholder="点击上方一个卡片作为修改目标"></label>
        <input type="hidden" name="title">
        <label class="wide quick-request-label">快速输入修改想法
          <div class="quick-request-row">
            <input name="quick_request" data-quick-request placeholder="先在这里简单写一句，例如：把第 3 步验收标准改得更严格">
            <button type="button" data-fill-request>填入修改内容</button>
          </div>
        </label>
        <label class="wide request-input-label">输入修改请求<textarea name="request" rows="7" placeholder="在这里写你希望如何修改上方选中的目标，例如：要改哪里、希望怎么改、验收标准或需要审计的点。"></textarea></label>
        <div class="request-actions">
          <button type="submit">提交到本地 server</button>
          <button type="button" data-copy-request>复制 JSON</button>
        </div>
        <div class="wide request-result is-idle" data-request-result role="status" aria-live="polite">静态打开时可复制 JSON；serve 模式会写入 .goo/change-requests/。</div>
      </form>
    </section>
    <section class="panel">
      <div class="section-head"><h2>待处理请求</h2><span data-request-count>{len(requests)} 条</span></div>
      <p class="request-scope-note">待处理请求不会自动修改文件。下一步在 Codex/Claude 中运行 <code>/auto-goo:goo-continue</code>，AutoGoo 会扫描这些请求、同步进 plan、执行修改和审计；完成后在这里标记状态。</p>
      <div class="request-list" data-request-list>{''.join(rows) or '<p class="muted" data-empty-requests>暂无修改请求。</p>'}</div>
    </section>
    """


def duration_label(started: Any, completed: Any) -> str:
    start = parse_time(started)
    end = parse_time(completed)
    if not start or not end or end < start:
        return "未记录"
    seconds = int((end - start).total_seconds())
    if seconds < 60:
        return f"{seconds} 秒"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} 分 {seconds} 秒" if seconds else f"{minutes} 分"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes} 分" if minutes else f"{hours} 小时"


def render_agent_executions(plan: dict[str, Any] | None) -> str:
    steps = [step for step in (plan or {}).get("steps", []) if isinstance(step, dict) and step.get("subagent")]
    verified = sum(1 for step in steps if step.get("agent_id"))
    running = sum(1 for step in steps if step.get("status") == "running")
    completed = sum(1 for step in steps if step.get("status") == "completed")
    rows = []
    for step in steps:
        status = str(step.get("status") or "pending")
        role = str(step.get("subagent") or "未分配")
        task_agent = str(step.get("task_agent") or "未记录")
        agent_id = str(step.get("agent_id") or "未记录")
        output = step.get("outputs") or step.get("output") or "未记录"
        if isinstance(output, list):
            output = "、".join(str(item) for item in output) or "未记录"
        log_path = step.get("log_path") or "未记录"
        rows.append(
            f"""
            <article class="agent-execution {esc(STATUS_CLASS.get(status, 'pending'))}">
              <div class="agent-execution-head">
                <div>
                  <span class="agent-role">{esc(role)} / {esc(task_agent)}</span>
                  <h3>#{esc(step.get('id'))} {esc(step.get('name') or '未命名步骤')}</h3>
                </div>
                <span class="status {esc(STATUS_CLASS.get(status, 'pending'))}">{esc(status_label(status))}</span>
              </div>
              <dl class="agent-execution-meta">
                <div><dt>实际代理 ID</dt><dd>{esc(agent_id)}</dd></div>
                <div><dt>耗时</dt><dd>{esc(duration_label(step.get('started_at'), step.get('completed_at')))}</dd></div>
                <div><dt>产出</dt><dd>{esc(output)}</dd></div>
                <div><dt>执行日志</dt><dd><code>{esc(log_path)}</code></dd></div>
              </dl>
            </article>
            """
        )
    return f"""
    <section class="panel subagent-panel">
      <div class="section-head"><h2>本次代理执行</h2><span>{len(steps)} 个代理步骤 · {verified} 个已记录实际 ID</span></div>
      <p class="muted">数据来自当前 <code>.goo/plan.json</code> 与步骤日志；“未记录”表示旧计划没有留下可验证的实际调用信息。</p>
      <div class="status-grid">
        <a class="status-card" href="#subagents"><span>代理步骤</span><strong>{len(steps)}</strong></a>
        <a class="status-card" href="#subagents"><span>运行中</span><strong>{running}</strong></a>
        <a class="status-card" href="#subagents"><span>已完成</span><strong>{completed}</strong></a>
        <a class="status-card" href="#subagents"><span>实际 ID 已记录</span><strong>{verified}</strong></a>
      </div>
      <div class="agent-execution-list">{''.join(rows) or '<p class="muted">当前计划没有代理执行记录。</p>'}</div>
    </section>
    """


def render_brainstorm(data: dict[str, Any] | None, source: Path | None = None) -> str:
    if not data:
        return """
        <section class="panel">
          <div class="section-head"><h2>头脑风暴</h2><span>0 个候选目标</span></div>
          <p class="muted">未找到当前 .goo/brainstorm.json 或历史头脑风暴记录。</p>
        </section>
        """
    goals = data.get("candidate_goals") or data.get("goals") or []
    items = []
    for goal in goals if isinstance(goals, list) else []:
        if not isinstance(goal, dict):
            continue
        goal_anchor = f"brainstorm-{slug(goal.get('id') or goal.get('name'), 'goal')}"
        priority = str(goal.get("priority_hint") or goal.get("priority") or "未标注")
        priority_level, _, priority_note = priority.partition(" — ")
        priority_label = {
            "highest": "最高优先级",
            "high": "高优先级",
            "medium": "中优先级",
            "low": "低优先级",
        }.get(priority_level.lower(), priority_level)
        why = goal.get("why") or goal.get("description") or "暂无原因说明"
        first_step = goal.get("first_step") or "暂无第一步建议"
        items.append(
            f"""
            <article id="{esc(goal_anchor)}" class="goal-card brainstorm-detail">
              <details class="brainstorm-goal">
                <summary>
                  <div class="brainstorm-goal-top">
                    <span class="goal-id">{esc(goal.get('id', 'goal'))}</span>
                    <span class="goal-priority">{esc(priority_label)}</span>
                  </div>
                  <h3>{esc(goal.get('name', '候选目标'))}</h3>
                  <p class="goal-reason">{esc(shorten(why, 180))}</p>
                  <div class="goal-next"><strong>第一步</strong><span>{esc(shorten(first_step, 150))}</span></div>
                  <span class="goal-expand">查看完整方案</span>
                </summary>
                <div class="brainstorm-goal-detail">
                  {f'<p class="priority-note">{esc(priority_note)}</p>' if priority_note else ''}
                  {render_fields(goal, [
                      ("description", "说明"),
                      ("why", "原因"),
                      ("expected_output", "预期输出"),
                      ("acceptance_criteria", "验收标准"),
                      ("evidence", "证据"),
                      ("risk", "风险"),
                      ("prerequisites", "前置条件"),
                      ("readiness_checklist", "准备清单"),
                      ("first_step", "第一步"),
                      ("depends_on", "依赖"),
                  ])}
                </div>
              </details>
            </article>
            """
        )
    metadata = render_fields(data, [
        ("status", "状态"),
        ("selected_goal_id", "已选目标"),
        ("created_at", "创建时间"),
        ("updated_at", "更新时间"),
    ])
    return f"""
    <section class="panel brainstorm-panel">
      <div class="section-head"><h2>头脑风暴</h2><span>{len(items)} 个候选目标</span></div>
      <div class="brainstorm-intro">
        <div><span>当前议题</span><strong>{esc(data.get("direction") or data.get("topic") or data.get("task") or "未记录")}</strong></div>
        <code>{esc(source or '.goo/brainstorm.json')}</code>
      </div>
      <div class="brainstorm-meta">{metadata}</div>
      {render_fields(data, [
          ("review", "审阅"),
          ("constraints", "约束"),
          ("open_questions", "开放问题"),
      ])}
      <div class="goal-grid">{''.join(items) or '<p class="muted">暂无候选目标记录。</p>'}</div>
    </section>
    """


def render_activity(events: list[dict[str, Any]], root: Path) -> str:
    rows = []
    for index, event in enumerate(events[:80], start=1):
        when = event["time"].strftime("%Y-%m-%d %H:%M") if isinstance(event.get("time"), datetime) else ""
        path = event.get("path")
        try:
            rel = path.relative_to(root) if isinstance(path, Path) else path
        except ValueError:
            rel = path
        event_anchor = f"activity-{index}"
        tokens = int(event.get("tokens") or 0)
        token_cell = f'<span class="token-pill">{fmt_int(tokens)} tokens</span>' if tokens else '<span class="token-pill empty">-</span>'
        work_content = event.get("work_content") or event.get("title") or "暂无任务摘要"
        rows.append(
            f"""
            <li id="{esc(event_anchor)}" class="activity-row">
              <details class="activity-entry">
              <summary class="activity-link" aria-label="展开执行记录 {index}">
                <span class="dot {esc(STATUS_CLASS.get(event.get('status'), 'pending'))}"></span>
                <span class="activity-summary"><strong>{esc(event.get('title'))}</strong><span>{esc(event.get('detail'))}</span></span>
                {token_cell}
                <time>{esc(when)}</time>
                <code>{esc(rel)}</code>
              </summary>
              <div class="activity-content">
                <dl>
                  <div><dt>任务内容</dt><dd>{esc(work_content)}</dd></div>
                  <div><dt>使用详情</dt><dd>{esc(event.get('detail'))}</dd></div>
                  <div><dt>发生时间</dt><dd>{esc(when or '未知')}</dd></div>
                  <div><dt>项目路径</dt><dd><code>{esc(rel)}</code></dd></div>
                </dl>
              </div>
              </details>
            </li>
            """
        )
    return f"""
    <section class="panel">
      <div class="section-head"><h2>最近执行记录</h2><span>最近 {min(len(events), 80)} 条 · Claude Code usage</span></div>
      <p class="activity-explainer">点击记录可展开任务内容、使用详情、发生时间与项目路径。记录来自当前项目的 Claude Code usage 日志，不是计划步骤日志。</p>
      <ol class="activity-list">{''.join(rows) or '<li class="muted">暂无活动记录。</li>'}</ol>
    </section>
    """


def render_artifacts(paths: list[Path], root: Path) -> str:
    items = []
    for path in paths:
        rel = path
        try:
            rel = path.relative_to(root)
        except ValueError:
            pass
        size = path.stat().st_size
        artifact_anchor = f"artifact-{slug(rel, 'artifact')}"
        href = artifact_href(path, root)
        items.append(
            f"""
            <li id="{esc(artifact_anchor)}"><a href="{esc(href)}" target="_blank" rel="noopener"><code>{esc(rel)}</code><span>{size:,} bytes</span></a></li>
            """
        )
    return f"""
    <section class="panel">
      <div class="section-head"><h2>产物归档</h2><span>最近 {len(paths)} 个</span></div>
      <ul class="artifact-list">{''.join(items) or '<li class="muted">暂无产物。</li>'}</ul>
    </section>
    """


def nav_targets() -> dict[str, str]:
    return {
        "index": "index.html",
        "threads": "threads.html",
        "brainstorm": "brainstorm.html",
        "plan": "plan.html",
        "status": "status.html",
        "observe": "observe.html",
        "subagents": "agents.html",
        "artifacts": "artifacts.html",
        "requests": "requests.html",
    }


def nav_script() -> str:
    token_script = """
  <script>
    const clock = document.getElementById("liveClock");
    const themeToggle = document.getElementById("themeToggle");
    function applyTheme(theme) {
      document.documentElement.dataset.theme = theme;
      localStorage.setItem("autogoo-plugin-workflow-theme", theme);
      if (themeToggle) {
        const isDark = theme === "dark";
        themeToggle.textContent = isDark ? "☼" : "☾";
        themeToggle.setAttribute("aria-label", isDark ? "切换浅色模式" : "切换深色模式");
        themeToggle.setAttribute("title", isDark ? "切换浅色模式" : "切换深色模式");
      }
    }
    applyTheme(localStorage.getItem("autogoo-plugin-workflow-theme") || "light");
    function tick() {
      if (!clock) return;
      const now = new Date();
      clock.textContent = `实时 · ${now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
    }
    if (themeToggle) {
      themeToggle.addEventListener("click", () => {
        const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
        applyTheme(next);
      });
    }
    function syncActiveNav() {
      const hash = window.location.hash || "#overview";
      document.querySelectorAll(".nav-item[href^='#']").forEach((item) => {
        item.classList.toggle("active", item.getAttribute("href") === hash);
      });
    }
    window.addEventListener("hashchange", syncActiveNav);
    syncActiveNav();
    function positionActivityTooltip(tooltip, pointer) {
      const tooltipBox = tooltip.getBoundingClientRect();
      const gutter = 10;
      let left = pointer.clientX + 12;
      left = Math.max(gutter, Math.min(left, window.innerWidth - tooltipBox.width - gutter));
      let top = pointer.clientY + 12;
      if (top + tooltipBox.height > window.innerHeight - gutter) {
        top = pointer.clientY - tooltipBox.height - 12;
      }
      top = Math.max(gutter, top);
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${top}px`;
    }
    function showActivityTooltip(tooltip, pointer, text) {
      if (!tooltip || !pointer || !text) return;
      tooltip.textContent = text;
      tooltip.hidden = false;
      requestAnimationFrame(() => positionActivityTooltip(tooltip, pointer));
    }
    function hideActivityTooltip(tooltip) {
      if (tooltip) tooltip.hidden = true;
    }
    document.querySelectorAll("[data-token-activity]").forEach((widget) => {
      const tooltip = widget.querySelector("[data-token-tooltip]");
      const workPanel = widget.closest("[data-token-work-widget]")?.querySelector("[data-token-work-panel]");
      const workRange = workPanel?.querySelector("[data-token-work-range]");
      const workList = workPanel?.querySelector("[data-token-work-list]");
      if (tooltip) document.body.append(tooltip);
      const selectTokenWork = (cell) => {
        if (!cell?.dataset.tokenWorkItems) return;
        let items = [];
        try {
          items = JSON.parse(cell.dataset.tokenWorkItems);
        } catch (error) {
          items = ["未能读取该时间段的工作内容。"];
        }
        if (workRange) workRange.textContent = cell.dataset.tokenWorkTitle || "已选时间段";
        if (workList) {
          workList.replaceChildren(...items.map((text) => {
            const item = document.createElement("li");
            item.textContent = text;
            return item;
          }));
        }
        widget.querySelectorAll(".token-day.selected").forEach((item) => item.classList.remove("selected"));
        cell.classList.add("selected");
      };
      const showTokenDetail = (cell, pointer) => {
        if (!cell?.dataset.tokenDetail) return;
        showActivityTooltip(tooltip, pointer, cell.dataset.tokenDetail);
      };
      widget.querySelectorAll("[data-token-detail]").forEach((cell) => {
        cell.addEventListener("click", () => selectTokenWork(cell));
        cell.addEventListener("focus", () => selectTokenWork(cell));
        cell.addEventListener("pointerenter", (event) => showTokenDetail(cell, event));
        cell.addEventListener("pointermove", (event) => positionActivityTooltip(tooltip, event));
        cell.addEventListener("pointerleave", () => hideActivityTooltip(tooltip));
      });
      const selectLatestWork = (view) => {
        const usedCells = [...widget.querySelectorAll(`[data-token-panel="${view}"] .token-day:not(.l0)`)];
        const allCells = [...widget.querySelectorAll(`[data-token-panel="${view}"] .token-day`)];
        selectTokenWork(usedCells[usedCells.length - 1] || allCells[allCells.length - 1]);
      };
      widget.querySelectorAll("[data-token-view]").forEach((button) => {
        button.addEventListener("click", () => {
          const view = button.dataset.tokenView;
          widget.dataset.activeView = view || "daily";
          widget.querySelectorAll("[data-token-view]").forEach((item) => item.classList.toggle("active", item === button));
          widget.querySelectorAll("[data-token-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.tokenPanel === view));
          hideActivityTooltip(tooltip);
          selectLatestWork(view || "daily");
        });
      });
      selectLatestWork("daily");
    });
    window.addEventListener("scroll", () => document.querySelectorAll(".activity-tooltip").forEach(hideActivityTooltip), true);
    window.addEventListener("resize", () => document.querySelectorAll(".activity-tooltip").forEach(hideActivityTooltip));
    document.querySelectorAll("[data-change-request-form]").forEach((form) => {
      const result = form.querySelector("[data-request-result]");
      const threadSelect = form.querySelector("[name='thread_id']");
      const targetSelect = form.querySelector("[name='target']");
      const contextThreadSelect = document.querySelector("[data-context-thread-filter]");
      const contextTargetSelect = document.querySelector("[data-context-target-filter]");
      const titleField = form.querySelector("input[name='title']");
      const quickField = form.querySelector("[data-quick-request]");
      const requestField = form.querySelector("textarea[name='request']");
      const selectedTargetField = form.querySelector("[data-selected-target]");
      const targetRefField = form.querySelector("[data-target-ref-field]");
      const selectedTargetDisplays = [...document.querySelectorAll("[data-selected-target-display]")];
      const requestList = document.querySelector("[data-request-list]");
      const requestCount = document.querySelector("[data-request-count]");
      let selectedTarget = "";
      const contextCards = [...document.querySelectorAll("[data-request-context]")];
      const setResult = (text, state = "idle") => {
        if (!result) return;
        result.textContent = text;
        result.dataset.state = state;
        result.classList.toggle("is-success", state === "success");
        result.classList.toggle("is-error", state === "error");
        result.classList.toggle("is-idle", state === "idle");
      };
      const escapeHtml = (value) => String(value || "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      })[char]);
      const updateRequestCount = () => {
        if (!requestList || !requestCount) return;
        const count = requestList.querySelectorAll(".request-card").length;
        requestCount.textContent = `${count} 条`;
      };
      const prependRequestCard = (item, path) => {
        if (!requestList) return;
        requestList.querySelector("[data-empty-requests]")?.remove();
        const continueCommand = `/auto-goo:goo-continue  # 处理 ${path || ""}`;
        const article = document.createElement("article");
        article.className = "request-card just-added";
        article.dataset.requestCard = "";
        article.dataset.requestPath = path || "";
        article.innerHTML = `
          <div class="node-top"><strong>${escapeHtml(item.title || item.target || "修改请求")}</strong><span data-request-status>${escapeHtml(item.status || "pending_model_update")}</span></div>
          <p>${escapeHtml(item.request || "")}</p>
          <div class="step-meta">
            <span><strong>Thread</strong><code>${escapeHtml(item.thread_id || "")}</code></span>
            <span><strong>目标</strong>${escapeHtml(item.target || "")}</span>
            <span><strong>修改目标</strong>${escapeHtml(item.target_ref || "")}</span>
            <span><strong>文件</strong><code>${escapeHtml(path || "")}</code></span>
          </div>
          <div class="request-next-step">
            <strong>下一步</strong>
            <code>${escapeHtml(continueCommand)}</code>
          </div>
          <div class="request-card-actions">
            <button type="button" data-copy-continue="${escapeHtml(continueCommand)}">复制继续命令</button>
            <button type="button" data-update-request-status="completed">标记完成</button>
            <button type="button" data-update-request-status="needs_revision">标记需修改</button>
          </div>
        `;
        requestList.prepend(article);
        updateRequestCount();
      };
      const updateRequestCardStatus = async (button) => {
        const card = button.closest("[data-request-card]");
        const path = card?.dataset.requestPath || "";
        const status = button.dataset.updateRequestStatus || "";
        if (!path || !status) return;
        button.disabled = true;
        try {
          const response = await fetch("/api/change-request/status", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path, status })
          });
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || "状态更新失败");
          card.querySelector("[data-request-status]").textContent = status;
          card.dataset.requestState = status;
          setResult(`已更新请求状态：${path} -> ${status}`, "success");
        } catch (error) {
          setResult(`状态更新失败：${error.message || error}`, "error");
        } finally {
          button.disabled = false;
        }
      };
      const updateTargetField = () => {
        if (selectedTargetField) selectedTargetField.value = selectedTarget;
        if (targetRefField) targetRefField.value = selectedTarget;
        selectedTargetDisplays.forEach((item) => {
          if ("value" in item) item.value = selectedTarget;
          else item.textContent = selectedTarget || "未选择修改目标";
          item.classList.toggle("is-empty", !selectedTarget);
        });
      };
      const buildRequestText = () => {
        const quick = (quickField?.value || "").trim();
        const target = targetSelect?.value || "plan";
        const lines = [
          `目标位置：${target}`,
          selectedTarget ? `修改目标：${selectedTarget}` : "修改目标：未选择",
          "",
          "修改请求：",
          quick || "请在这里补充希望修改的内容。",
          "",
          "期望结果：",
          "请按修改请求更新选中的修改目标。",
          "",
          "验收标准：",
          "- 修改后的内容能直接对应选中的修改目标。",
          "- 不破坏现有 plan/thread/artifact 的关联关系。"
        ];
        return lines.join("\\n");
      };
      const fillRequestField = () => {
        if (!requestField) return;
        requestField.value = buildRequestText();
        if (titleField) titleField.value = requestTitle();
        requestField.focus();
      };
      const requestTitle = () => {
        const quick = (quickField?.value || "").trim();
        if (quick) return quick.slice(0, 48);
        if (selectedTarget) return selectedTarget.slice(0, 48);
        return "修改请求";
      };
      const syncContextFilter = () => {
        const target = targetSelect?.value || "plan-step";
        const threadId = threadSelect?.value || "";
        contextCards.forEach((item) => {
          const context = item.dataset.requestContext || "";
          const itemThread = item.dataset.requestThread || "";
          const matchesTarget = target === "other" || context === target;
          const matchesThread = !threadId || itemThread === "*" || !itemThread || itemThread === threadId;
          const visible = matchesTarget && matchesThread;
          item.toggleAttribute("hidden", !visible);
        });
      };
      const syncContextControls = (source) => {
        if (source !== "context" && contextThreadSelect && threadSelect) contextThreadSelect.value = threadSelect.value;
        if (source !== "context" && contextTargetSelect && targetSelect) contextTargetSelect.value = targetSelect.value;
        if (source !== "form" && contextThreadSelect && threadSelect) threadSelect.value = contextThreadSelect.value;
        if (source !== "form" && contextTargetSelect && targetSelect) targetSelect.value = contextTargetSelect.value;
        syncContextFilter();
      };
      document.addEventListener("click", (event) => {
        const card = event.target.closest("[data-target-ref]");
        if (!card) return;
        event.preventDefault();
        selectedTarget = card.dataset.targetRef || card.textContent.trim();
        document.querySelectorAll("[data-target-ref].selected").forEach((item) => {
          item.classList.remove("selected");
          item.setAttribute("aria-pressed", "false");
        });
        card.classList.add("selected");
        card.setAttribute("aria-pressed", "true");
        updateTargetField();
        setResult(`已选择修改目标：${selectedTarget}`, "idle");
      });
      document.addEventListener("dblclick", (event) => {
        const card = event.target.closest("[data-target-ref]");
        if (card?.dataset.openHref) window.open(card.dataset.openHref, "_blank", "noopener");
      });
      document.addEventListener("click", async (event) => {
        const copyButton = event.target.closest("[data-copy-continue]");
        if (copyButton) {
          event.preventDefault();
          const command = copyButton.dataset.copyContinue || "/auto-goo:goo-continue";
          try {
            await navigator.clipboard.writeText(command);
            setResult(`已复制继续命令：${command}`, "success");
          } catch (error) {
            setResult(command, "error");
          }
          return;
        }
        const statusButton = event.target.closest("[data-update-request-status]");
        if (statusButton) {
          event.preventDefault();
          updateRequestCardStatus(statusButton);
        }
      });
      contextTargetSelect?.addEventListener("change", () => syncContextControls("context"));
      contextThreadSelect?.addEventListener("change", () => syncContextControls("context"));
      form.querySelector("[data-fill-request]")?.addEventListener("click", fillRequestField);
      quickField?.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          fillRequestField();
        }
      });
      syncContextControls("form");
      updateTargetField();
      const payload = () => {
        const data = Object.fromEntries(new FormData(form).entries());
        if (titleField) titleField.value = requestTitle();
        return {
          thread_id: data.thread_id || "",
          target: data.target || "plan",
          title: requestTitle(),
          request: data.request || "",
          target_ref: data.target_ref || selectedTarget || "",
          status: "pending_model_update",
          source: "autogoo-plugin-publish-web",
          created_at: new Date().toISOString()
        };
      };
      form.querySelector("[data-copy-request]")?.addEventListener("click", async () => {
        const text = JSON.stringify(payload(), null, 2);
        try {
          await navigator.clipboard.writeText(text);
          setResult("已复制 JSON。把它交给 AutoGoo 后会写入修改队列。", "success");
        } catch (error) {
          setResult(text, "error");
        }
      });
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          const requestPayload = payload();
          setResult("正在提交到本地 server...", "idle");
          const response = await fetch("/api/change-request", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(requestPayload)
          });
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || "提交失败");
          setResult(`已保存到本地修改队列：${data.path}`, "success");
          prependRequestCard(requestPayload, data.path);
          form.reset();
          selectedTarget = "";
          document.querySelectorAll("[data-target-ref].selected").forEach((item) => {
            item.classList.remove("selected");
            item.setAttribute("aria-pressed", "false");
          });
          updateTargetField();
        } catch (error) {
          setResult(`无法直接保存；请复制 JSON 交给 AutoGoo。${error.message || error}`, "error");
        }
      });
    });
    tick();
    setInterval(tick, 1000);
  </script>
"""
    return token_script


def generated_content_css() -> str:
    return """

/* Dynamic content rendered by goo-publish.py. Shared shell layout lives in
   templates/publish/workflow-shell.html. */
.section-anchor { scroll-margin-top: 150px; }
.grid { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(300px, .75fr); gap: 18px; }
.summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin-bottom: 18px; }
.summary-card { min-height: 126px; padding: 15px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--panel-bg); box-shadow: var(--shadow); color: var(--text); text-decoration: none; display: block; position: relative; overflow: hidden; }
.summary-card::before { content: ""; position: absolute; inset: 0; background: radial-gradient(circle at top right, rgba(9,105,218,.08), transparent 36%); pointer-events: none; }
.summary-card:hover, .summary-card:focus-visible { border-color: rgba(102,166,255,.48); background: var(--control-hover); text-decoration: none; transform: translateY(-1px); }
.summary-card strong { display: block; margin-top: 10px; font-size: 28px; line-height: 1; font-weight: 760; }
.summary-card span, .summary-card p { color: var(--muted); }
.section-head, .node-top { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 12px; }
.section-head h2, .section-head h3, .node-top h3 { margin: 0; font-size: var(--font-lg, 15px); }
.status-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-top: 12px; }
.status-card { border: 1px solid var(--line); border-radius: 8px; padding: 12px; color: var(--text); background: var(--soft-bg); text-decoration: none; }
.status-card strong { display: block; margin-top: 4px; font-size: 22px; }
.status-list { display: grid; gap: 8px; margin-top: 12px; }
.status-row { display: grid; grid-template-columns: 14px minmax(0, 1fr) 92px minmax(120px, .4fr); gap: 10px; align-items: center; border: 1px solid var(--line); border-radius: 8px; padding: 10px; color: var(--text); background: var(--panel-bg); text-decoration: none; }
.observe-grid, .observe-command-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; }
.observe-card, .observe-command-grid > div { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: var(--soft-bg); min-width: 0; }
.observe-card strong { display: block; margin-top: 6px; font-size: 20px; }
.observe-card p, .observe-command-grid p { margin: 8px 0 0; color: var(--muted); font-size: 12px; }
.observe-command-grid code { display: block; margin-top: 6px; padding: 8px; border: 1px solid var(--line); border-radius: 6px; background: var(--panel-bg); overflow-wrap: anywhere; white-space: pre-wrap; font-size: 12px; }
.observe-step-list, .observe-shell-list { display: grid; gap: 10px; }
.observe-step, .observe-shell-log { border: 1px solid var(--line); border-left: 4px solid var(--line-strong); border-radius: 8px; padding: 12px; background: var(--panel-bg); }
.observe-step.running { border-left-color: var(--blue); } .observe-step.failed, .observe-step.blocked { border-left-color: var(--red); }
.observe-log-tail, .observe-shell-log ul { margin-top: 10px; }
.observe-log-tail ul, .observe-shell-log ul { list-style: none; display: grid; gap: 5px; margin: 8px 0 0; padding: 0; }
.observe-log-tail li, .observe-shell-log li { padding: 6px 8px; border-radius: 6px; background: var(--soft-bg); color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; overflow-wrap: anywhere; }
.chip { display: inline-flex; align-items: center; min-height: 24px; padding: 4px 8px; border-radius: 999px; color: var(--muted); background: var(--chip-bg); font-size: 12px; font-weight: 650; }
.done { color: var(--green); } .running { color: var(--blue); } .failed { color: var(--red); } .paused { color: var(--amber); } .blocked { color: var(--red); }
.progress { height: 10px; background: #eaeef2; border-radius: 999px; overflow: hidden; margin-top: 14px; }
.progress span { display: block; height: 100%; background: linear-gradient(90deg, var(--blue), var(--cyan)); }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.detail-card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-top: 12px; }
.goal-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }
.detail-grid.nested { grid-template-columns: minmax(110px, .24fr) minmax(0, 1fr); margin-top: 0; }
.detail-section { border-top: 1px solid var(--line); margin-top: 14px; padding-top: 12px; }
.detail-card, .step-detail { border: 1px solid var(--line); border-left: 4px solid var(--blue); border-radius: 8px; padding: 14px; background: var(--soft-bg); }
.step-detail-list { display: grid; gap: 12px; margin-top: 12px; }
.step-detail { border-left-color: var(--line-strong); background: var(--panel-bg); }
.step-detail.done { border-left-color: var(--green); } .step-detail.running { border-left-color: var(--blue); } .step-detail.failed { border-left-color: var(--red); } .step-detail.blocked { border-left-color: var(--red); }
.step-detail > p { color: var(--muted); margin-top: 8px; }
.step-meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; margin: 12px 0; }
.step-meta span { border: 1px solid var(--line); border-radius: 8px; padding: 8px; background: var(--soft-bg); min-width: 0; overflow-wrap: anywhere; color: var(--muted); }
.step-meta strong { display: block; color: var(--faint); font-size: 12px; margin-bottom: 2px; }
.token-activity-panel { --token-cell: 14px; --token-gap: 3px; background: var(--token-panel-bg, var(--panel-bg)); color: var(--token-text, var(--text)); border-color: var(--token-panel-border, var(--line)); overflow: visible; }
.token-activity-head { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 8px; }
.token-activity-head h2 { font-size: 20px; }
.token-tabs { display: inline-flex; gap: 4px; }
.token-tabs button { appearance: none; border: 0; background: var(--token-control-bg, var(--soft-bg)); color: var(--token-muted, var(--muted)); font: inherit; font-weight: 700; padding: 4px 8px; border-radius: 4px; cursor: pointer; }
.token-tabs button.active { color: var(--token-control-active-text, var(--green)); background: var(--token-control-active, #eaf6ef); }
.token-activity-total { display: flex; align-items: baseline; flex-wrap: wrap; gap: 10px; margin-top: 8px; color: var(--muted); }
.token-activity-total strong { color: var(--text); font-size: 20px; }
.activity-tooltip { position: fixed; z-index: 1000; width: max-content; max-width: min(420px, calc(100vw - 20px)); padding: 8px 10px; border: 1px solid var(--line-strong); border-radius: 6px; background: var(--panel-bg); color: var(--text); box-shadow: 0 8px 24px rgba(31,35,40,.16); font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: anywhere; pointer-events: none; }
.activity-tooltip[hidden] { display: none; }
.token-months { display: grid; grid-template-columns: repeat(53, minmax(0, var(--token-cell))); gap: var(--token-gap); width: calc(100% - 44px); max-width: 898px; margin: 18px 0 8px 44px; color: var(--muted); font-size: 12px; }
.token-months span { white-space: nowrap; line-height: 1; font-weight: 650; }
.token-heat-body { display: flex; gap: 8px; min-width: 0; }
.token-days { display: grid; grid-template-rows: repeat(7, var(--token-cell)); gap: var(--token-gap); color: var(--muted); width: 36px; min-width: 36px; font-size: 12px; }
.token-days span:nth-child(1) { grid-row: 2; } .token-days span:nth-child(2) { grid-row: 4; } .token-days span:nth-child(3) { grid-row: 6; }
.token-activity-panel[data-active-view="weekly"] .token-days, .token-activity-panel[data-active-view="cumulative"] .token-days { display: none; }
.token-activity-panel[data-active-view="weekly"] .token-months, .token-activity-panel[data-active-view="cumulative"] .token-months { margin-left: 0; }
.token-views { position: relative; width: calc(100% - 44px); max-width: 898px; min-width: 0; }
.token-activity-panel[data-active-view="weekly"] .token-views, .token-activity-panel[data-active-view="cumulative"] .token-views { width: 100%; }
.token-grid { display: none; gap: 3px; }
.token-grid.active, .token-grid-period.active { display: grid; grid-template-columns: repeat(53, minmax(0, var(--token-cell))); gap: var(--token-gap); }
.token-grid-period .token-day { width: 100%; height: 32px; aspect-ratio: auto; }
.token-week { display: grid; grid-template-rows: repeat(7, var(--token-cell)); gap: var(--token-gap); min-width: 0; }
.token-day { width: 100%; max-width: var(--token-cell); height: auto; aspect-ratio: 1; padding: 0; border-radius: 3px; display: inline-block; cursor: pointer; background: var(--token-empty, #edf2f7); border: 1px solid var(--token-border, #d8e2dc); }
.token-day.l1 { background: var(--token-1, #dff7e8); } .token-day.l2 { background: var(--token-2, #9be7b3); } .token-day.l3 { background: var(--token-3, #46b86f); } .token-day.l4 { background: var(--token-4, #1f883d); }
.token-day:hover, .token-day:focus-visible, .token-day.selected { outline: 2px solid var(--blue); outline-offset: 1px; }
.token-work-panel { border-left: 3px solid var(--green); background: var(--soft-bg); }
.token-work-range { color: var(--muted); font-size: 12px; font-weight: 650; white-space: nowrap; }
.token-work-list { list-style: none; display: grid; gap: 8px; margin: 0; padding: 0; }
.token-work-list li { position: relative; padding-left: 18px; color: var(--text); font-size: 14px; line-height: 1.5; overflow-wrap: anywhere; }
.token-work-list li::before { content: ""; position: absolute; left: 2px; top: .62em; width: 6px; height: 6px; border-radius: 50%; background: var(--green); }
.token-legend { display: flex; align-items: center; justify-content: flex-end; gap: 4px; color: var(--muted); margin-top: 12px; }
.token-legend .token-day { width: 14px; height: 14px; }
.flow-panel { overflow: hidden; }
.flow-scroll { overflow: hidden; padding: 6px 0 2px; }
.flow-svg { display: block; width: auto; max-width: 100%; min-width: 0; height: auto; }
.flow-node-link { color: inherit; text-decoration: none; cursor: pointer; }
.flow-node-link:hover rect:first-child,
.flow-node-link:focus-visible rect:first-child { stroke: var(--blue); stroke-width: 2; }
.flow-edge { stroke: var(--violet); stroke-width: 2.8; stroke-linecap: round; opacity: .95; }
.flow-arrow { fill: var(--violet); }
.flow-title { fill: currentColor; font: 8.8px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-weight: 700; }
.flow-meta { fill: #57606a; font: 7px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.dag { display: grid; gap: 12px; }
.dag-tier { display: grid; grid-template-columns: 80px repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; align-items: stretch; }
.dag-tier > h3 { margin: 0; color: var(--muted); }
.dag-node, .goal-card { border: 1px solid var(--line); border-left: 4px solid var(--line-strong); border-radius: 8px; padding: 12px; min-height: 128px; background: var(--panel-bg); color: var(--text); display: block; text-decoration: none; }
.dag-node:hover, .dag-node:focus-visible { border-color: var(--blue); background: var(--blue-soft); outline: 2px solid color-mix(in srgb, var(--blue) 32%, transparent); outline-offset: 2px; }
.dag-node.done { border-left-color: var(--green); } .dag-node.running { border-left-color: var(--blue); } .dag-node.failed, .dag-node.blocked { border-left-color: var(--red); }
.pixel-status-panel { background: linear-gradient(180deg, var(--panel-bg), var(--soft-bg)); }
.pixel-progress { height: 18px; padding: 3px; border: 2px solid var(--line-strong); border-radius: 0; background: var(--panel-bg); box-shadow: inset 0 0 0 2px var(--soft-bg); }
.pixel-progress span { display: block; height: 100%; background: repeating-linear-gradient(90deg, var(--green) 0 10px, color-mix(in srgb, var(--green) 78%, #000) 10px 12px); }
.pixel-board { display: grid; grid-template-columns: repeat(auto-fill, minmax(34px, 1fr)); gap: 6px; margin: 14px 0; }
.pixel-step { min-height: 34px; display: grid; place-items: center; border: 2px solid var(--line-strong); color: var(--text); background: var(--panel-bg); text-decoration: none; font: 700 11px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; box-shadow: 3px 3px 0 var(--line); }
.pixel-step.done { background: var(--green-soft); border-color: var(--green); }
.pixel-step.running { background: var(--blue-soft); border-color: var(--blue); }
.pixel-step.failed, .pixel-step.blocked { background: var(--red-soft); border-color: var(--red); }
.pixel-step:hover, .pixel-step:focus-visible { transform: translate(-1px, -1px); box-shadow: 4px 4px 0 var(--line-strong); outline: 0; }
.pixel-card { border: 2px solid var(--line-strong); border-radius: 0; box-shadow: 3px 3px 0 var(--line); }
.pixel-row { border: 1px solid var(--line); border-radius: 0; }
.brainstorm-panel { min-width: 0; overflow: hidden; }
.brainstorm-intro { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; padding: 12px; border-left: 3px solid var(--green); background: var(--soft-bg); }
.brainstorm-intro div { min-width: 0; }
.brainstorm-intro span { display: block; color: var(--muted); font-size: 11px; font-weight: 650; }
.brainstorm-intro strong { display: block; margin-top: 4px; overflow-wrap: anywhere; }
.brainstorm-intro code { max-width: 42%; color: var(--muted); overflow-wrap: anywhere; text-align: right; }
.brainstorm-meta > .detail-grid { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 0; }
.brainstorm-meta dt { color: var(--muted); font-size: 11px; }
.brainstorm-meta dd { margin: 0; font-weight: 650; }
.brainstorm-detail { min-width: 0; min-height: 0; padding: 0; overflow: hidden; }
.brainstorm-goal > summary { min-height: 250px; padding: 14px; list-style: none; cursor: pointer; }
.brainstorm-goal > summary::-webkit-details-marker { display: none; }
.brainstorm-goal > summary:hover, .brainstorm-goal[open] > summary { background: var(--control-hover); }
.brainstorm-goal-top { display: flex; justify-content: space-between; gap: 10px; align-items: center; }
.goal-id { color: var(--text); font-weight: 760; }
.goal-priority { max-width: 55%; padding: 3px 7px; border-radius: 999px; color: var(--green); background: var(--soft-bg); font-size: 11px; font-weight: 700; overflow-wrap: anywhere; }
.brainstorm-goal h3 { margin: 14px 0 8px; font-size: 16px; line-height: 1.4; overflow-wrap: anywhere; }
.goal-reason { display: -webkit-box; margin: 0; color: var(--muted); font-size: 13px; line-height: 1.55; overflow: hidden; overflow-wrap: anywhere; -webkit-line-clamp: 3; -webkit-box-orient: vertical; }
.goal-next { display: grid; gap: 3px; margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--line); }
.goal-next strong { color: var(--muted); font-size: 11px; }
.goal-next span { display: -webkit-box; overflow: hidden; overflow-wrap: anywhere; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.goal-expand { display: block; margin-top: 12px; color: var(--blue); font-size: 12px; font-weight: 650; }
.brainstorm-goal[open] .goal-expand { display: none; }
.brainstorm-goal-detail { padding: 0 14px 14px; border-top: 1px solid var(--line); }
.brainstorm-goal-detail .detail-grid { display: grid; grid-template-columns: 100px minmax(0, 1fr); gap: 10px 12px; margin: 14px 0 0; }
.brainstorm-goal-detail dt { color: var(--muted); font-size: 12px; font-weight: 650; }
.brainstorm-goal-detail dd { min-width: 0; margin: 0; overflow-wrap: anywhere; }
.brainstorm-goal-detail .detail-list { margin: 0; padding-left: 18px; }
.brainstorm-goal-detail .detail-list li + li { margin-top: 5px; }
.priority-note { margin: 12px 0 0; color: var(--muted); font-size: 12px; }
.activity-list, .artifact-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }
.activity-entry > summary { list-style: none; cursor: pointer; }
.activity-entry > summary::-webkit-details-marker { display: none; }
.activity-link { display: grid; grid-template-columns: 14px minmax(0, 1fr) 112px 130px minmax(120px, .5fr); gap: 10px; align-items: start; color: var(--text); border-radius: 8px; padding: 8px; text-decoration: none; }
.activity-link:hover, .activity-entry[open] > .activity-link { background: var(--control-hover); }
.activity-summary { min-width: 0; }
.activity-summary strong, .activity-summary > span { display: block; }
.activity-summary > span { margin-top: 3px; color: var(--muted); font-size: 12px; }
.activity-content { margin: 0 8px 10px 32px; padding: 12px; border-left: 3px solid var(--green); border-radius: 0 6px 6px 0; background: var(--soft-bg); }
.activity-content dl { display: grid; gap: 8px; margin: 0; }
.activity-content dl > div { display: grid; grid-template-columns: 84px minmax(0, 1fr); gap: 12px; }
.activity-content dt { color: var(--muted); font-size: 12px; font-weight: 650; }
.activity-content dd { min-width: 0; margin: 0; color: var(--text); overflow-wrap: anywhere; }
.activity-explainer { margin: -4px 0 12px; color: var(--muted); font-size: 12px; line-height: 1.55; }
.token-pill { display: inline-flex; justify-content: flex-end; color: var(--green); font: 12px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space: nowrap; }
.token-pill.empty { color: var(--muted); }
.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--line-strong); margin-top: 6px; }
.dot.done { background: var(--green); } .dot.running { background: var(--blue); } .dot.failed { background: var(--red); }
.artifact-list a { display: flex; justify-content: space-between; gap: 12px; color: var(--text); border-radius: 8px; padding: 8px; text-decoration: none; }
.artifact-list a:hover, .artifact-list a:focus-visible { background: var(--violet-soft); outline: 2px solid color-mix(in srgb, var(--violet) 30%, transparent); outline-offset: 2px; }
.subagent-panel .muted code { color: inherit; }
.agent-execution-list { display: grid; gap: 10px; margin-top: 14px; }
.agent-execution { border: 1px solid var(--line); border-left: 4px solid var(--line-strong); border-radius: 8px; padding: 12px; background: var(--panel-bg); }
.agent-execution.done { border-left-color: var(--green); } .agent-execution.running { border-left-color: var(--blue); } .agent-execution.failed, .agent-execution.blocked { border-left-color: var(--red); }
.agent-execution-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.agent-execution-head h3 { margin: 4px 0 0; font-size: 14px; }
.agent-role { color: var(--muted); font: 11px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.agent-execution-meta { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 12px 0 0; }
.agent-execution-meta > div { min-width: 0; padding: 8px; border-radius: 6px; background: var(--soft-bg); }
.agent-execution-meta dt { color: var(--muted); font-size: 11px; font-weight: 650; }
.agent-execution-meta dd { margin: 4px 0 0; overflow-wrap: anywhere; }
.thread-list, .request-list { display: grid; gap: 12px; }
.thread-card, .request-card { border: 1px solid var(--line); border-left: 4px solid var(--blue); border-radius: 8px; padding: 14px; background: var(--panel-bg); }
.thread-card.done { border-left-color: var(--green); } .thread-card.running { border-left-color: var(--blue); } .thread-card.failed, .thread-card.blocked { border-left-color: var(--red); }
.thread-card .node-top > span { display: inline-flex; align-items: center; gap: 8px; }
.thread-plan-link { color: var(--blue); font-size: 12px; font-weight: 650; text-decoration: none; }
.thread-plan-link:hover, .thread-plan-link:focus-visible { text-decoration: underline; }
.thread-step-strip { display: flex; flex-wrap: wrap; gap: 6px; margin: 12px 0; }
.thread-step { min-width: 28px; min-height: 28px; display: inline-grid; place-items: center; border: 1px solid var(--line-strong); border-radius: 6px; color: var(--text); background: var(--soft-bg); text-decoration: none; font: 700 10px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.thread-step.done { border-color: var(--green); background: var(--green-soft); }
.thread-step.running { border-color: var(--blue); background: var(--blue-soft); }
.thread-step.failed, .thread-step.blocked { border-color: var(--red); background: var(--red-soft); }
.thread-step:hover, .thread-step:focus-visible { outline: 2px solid color-mix(in srgb, var(--blue) 32%, transparent); outline-offset: 2px; }
.request-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.request-form label { display: grid; gap: 6px; color: var(--muted); font-size: 12px; font-weight: 650; }
.request-form label.wide { grid-column: 1 / -1; }
.request-form .wide { grid-column: 1 / -1; }
.request-scope-note { margin: 0; color: var(--muted); font-size: 12px; }
.request-form input, .request-form select, .request-form textarea { width: 100%; border: 1px solid var(--line); border-radius: 8px; padding: 9px 10px; color: var(--text); background: var(--control-bg); }
.quick-request-label { color: var(--text); font-size: 13px; }
.quick-request-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; align-items: stretch; }
.quick-request-row input { border: 2px solid var(--blue); background: var(--blue-soft); box-shadow: 3px 3px 0 var(--line); }
.quick-request-row button { min-height: 40px; border: 2px solid var(--blue); border-radius: 0; padding: 0 12px; color: var(--text); background: var(--panel-bg); cursor: pointer; box-shadow: 3px 3px 0 var(--line); }
.quick-request-row button:hover, .quick-request-row button:focus-visible { transform: translate(-1px, -1px); box-shadow: 4px 4px 0 var(--blue-soft); outline: 0; }
.target-ref-label { color: var(--text); font-size: 13px; }
.target-ref-label input { border: 2px solid var(--green); background: var(--green-soft); box-shadow: 3px 3px 0 var(--line); }
.request-input-label { color: var(--text); font-size: 13px; }
.request-input-label textarea { min-height: 180px; border: 2px solid var(--amber); background: color-mix(in srgb, var(--amber-soft) 72%, var(--panel-bg)); box-shadow: 4px 4px 0 var(--amber-soft); }
.request-result { margin: 0; padding: 10px 12px; border: 2px solid var(--line-strong); background: var(--soft-bg); color: var(--text); font-size: 13px; font-weight: 700; box-shadow: 3px 3px 0 var(--line); }
.request-result.is-success { border-color: var(--green); background: var(--green-soft); }
.request-result.is-error { border-color: var(--red); background: var(--red-soft); }
.request-card.just-added { border-color: var(--green); background: var(--green-soft); }
.request-next-step { display: grid; gap: 6px; margin-top: 12px; padding: 10px; border: 2px solid var(--amber); background: var(--amber-soft); box-shadow: 3px 3px 0 var(--line); }
.request-next-step strong { color: var(--text); font-size: 12px; }
.request-next-step code { white-space: normal; overflow-wrap: anywhere; }
.request-card-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.request-card-actions button { min-height: 34px; border: 2px solid var(--line-strong); border-radius: 0; padding: 6px 10px; color: var(--text); background: var(--panel-bg); cursor: pointer; box-shadow: 3px 3px 0 var(--line); }
.request-card-actions button:hover, .request-card-actions button:focus-visible { transform: translate(-1px, -1px); box-shadow: 4px 4px 0 var(--line-strong); outline: 0; }
.request-card-actions button:disabled { cursor: wait; opacity: .64; }
.request-actions { grid-column: 1 / -1; display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.request-actions button { min-height: 36px; border: 1px solid var(--line); border-radius: 8px; padding: 6px 10px; color: var(--text); background: var(--control-bg); cursor: pointer; }
.request-context-layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(300px, .85fr); gap: 14px; align-items: start; }
.request-context-filters { display: grid; grid-template-columns: minmax(220px, .8fr) minmax(160px, .45fr); gap: 10px; margin: 0 0 12px; padding: 10px; border: 2px solid var(--blue); background: var(--blue-soft); box-shadow: 4px 4px 0 var(--line); }
.request-context-filters label { display: grid; gap: 5px; color: var(--text); font-size: 12px; font-weight: 700; }
.request-context-filters select { width: 100%; border: 2px solid var(--line-strong); border-radius: 0; padding: 8px 10px; color: var(--text); background: var(--panel-bg); }
.selected-target-bar { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 10px; align-items: center; margin: 0 0 12px; padding: 9px 10px; border: 2px solid var(--green); background: var(--green-soft); box-shadow: 3px 3px 0 var(--line); }
.selected-target-bar strong { font-size: 12px; color: var(--text); }
.selected-target-value { min-width: 0; color: var(--text); font-size: 12px; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.selected-target-value.is-empty { color: var(--muted); font-weight: 650; }
.request-reference-stack { display: grid; gap: 10px; }
.request-reference { min-width: 0; border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: var(--soft-bg); }
.request-reference pre { max-height: 420px; margin: 0; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.request-reference-list { display: grid; gap: 10px; }
.request-reference-list h3 { margin: 0; font-size: 13px; color: var(--muted); }
.request-context-grid { display: grid; gap: 8px; }
.request-context-group[hidden] { display: none !important; }
.request-context-card { display: block; width: 100%; min-width: 0; border: 2px solid var(--line); border-radius: 0; padding: 10px; color: var(--text); background: var(--panel-bg); text-align: left; text-decoration: none; cursor: pointer; box-shadow: 3px 3px 0 var(--line); }
.request-context-card span { color: var(--muted); font-size: 11px; font-weight: 650; }
.request-context-card strong { display: block; margin-top: 4px; font-size: 13px; overflow-wrap: anywhere; }
.request-context-card p { margin: 6px 0 0; color: var(--muted); font-size: 12px; line-height: 1.45; overflow-wrap: anywhere; }
.request-context-card:hover, .request-context-card:focus-visible { border-color: var(--amber); background: var(--amber-soft); outline: 0; transform: translate(-1px, -1px); box-shadow: 4px 4px 0 var(--line-strong); }
.request-context-card.selected { border-color: var(--green); background: var(--green-soft); box-shadow: 4px 4px 0 var(--green); }
.request-context-card[hidden], .request-reference[hidden] { display: none !important; }
.request-reference.request-context-card pre { color: var(--text); }

body { background: var(--pixel-bg, var(--bg)); }
.pixel-theme .panel,
.pixel-theme .summary-card,
.pixel-theme .metric-card,
.pixel-theme .data-card,
.pixel-theme .detail-card,
.pixel-theme .step-detail,
.pixel-theme .thread-card,
.pixel-theme .request-card,
.pixel-theme .agent-execution,
.pixel-theme .status-card,
.pixel-theme .status-row,
.pixel-theme .activity-content,
.pixel-theme .request-reference {
  border: 2px solid var(--line-strong);
  border-radius: 0;
  box-shadow: 4px 4px 0 color-mix(in srgb, var(--page-accent, var(--blue)) 24%, var(--line));
}
.pixel-theme .summary-card:nth-child(1), .pixel-theme .status-card:nth-child(1) { --page-accent: var(--green); }
.pixel-theme .summary-card:nth-child(2), .pixel-theme .status-card:nth-child(2) { --page-accent: var(--blue); }
.pixel-theme .summary-card:nth-child(3), .pixel-theme .status-card:nth-child(3) { --page-accent: var(--violet); }
.pixel-theme .summary-card:nth-child(4), .pixel-theme .status-card:nth-child(4) { --page-accent: var(--amber); }
.pixel-theme .summary-card:nth-child(5) { --page-accent: var(--cyan); }
.pixel-theme .summary-card:nth-child(6) { --page-accent: var(--red); }
.pixel-theme button,
.pixel-theme .request-form input,
.pixel-theme .request-form select,
.pixel-theme .request-form textarea,
.pixel-theme .token-tabs button,
.pixel-theme .nav-item,
.pixel-theme .thread-step,
.pixel-theme .chip {
  border-radius: 0;
}
.pixel-theme .request-actions button,
.pixel-theme .token-tabs button,
.pixel-theme .top-action {
  border: 2px solid var(--line-strong);
  box-shadow: 3px 3px 0 var(--line);
}
.pixel-theme .nav-item.active::before,
.pixel-theme .live-dot,
.pixel-theme .dot {
  border-radius: 0;
}
body[data-page="index"] { --page-accent: var(--green); }
body[data-page="threads"] { --page-accent: var(--blue); }
body[data-page="plan"] { --page-accent: var(--blue); }
body[data-page="activity"] { --page-accent: var(--violet); }
body[data-page="brainstorm"] { --page-accent: var(--amber); }
body[data-page="status"] { --page-accent: var(--green); }
body[data-page="observe"] { --page-accent: var(--amber); }
body[data-page="subagents"] { --page-accent: var(--cyan); }
body[data-page="artifacts"] { --page-accent: var(--violet); }
body[data-page="requests"] { --page-accent: var(--amber); }
.page-title h2 { color: var(--page-accent, var(--text)); }
.nav-item.active::before { background: var(--page-accent, var(--blue)); }
.panel > .section-head { border-left: 3px solid var(--page-accent, var(--line-strong)); padding-left: 10px; }
.summary-card { border-top: 3px solid var(--card-accent, var(--line-strong)); }
.summary-card strong { color: var(--card-accent, var(--text)); }
.summary-card:nth-child(1) { --card-accent: var(--green); background: var(--green-soft); }
.summary-card:nth-child(2) { --card-accent: var(--blue); background: var(--blue-soft); }
.summary-card:nth-child(3) { --card-accent: var(--cyan); background: var(--cyan-soft); }
.summary-card:nth-child(4) { --card-accent: var(--violet); background: var(--violet-soft); }
.summary-card:nth-child(5) { --card-accent: var(--amber); background: var(--amber-soft); }
.summary-card:nth-child(6) { --card-accent: var(--cyan); background: var(--cyan-soft); }
.summary-card:nth-child(7) { --card-accent: var(--violet); background: var(--violet-soft); }
.activity-row .token-pill { color: var(--violet); }
.agent-role { color: var(--cyan); }
.goal-priority { color: var(--amber); background: var(--amber-soft); }
.brainstorm-detail:nth-child(4n + 1) { border-left-color: var(--amber); }
.brainstorm-detail:nth-child(4n + 2) { border-left-color: var(--blue); }
.brainstorm-detail:nth-child(4n + 3) { border-left-color: var(--cyan); }
.brainstorm-detail:nth-child(4n) { border-left-color: var(--violet); }
@media (max-width: 860px) {
  .section-anchor { scroll-margin-top: 16px; }
  .grid, .hero, .detail-grid, .detail-grid.nested { grid-template-columns: 1fr; }
  .activity-link, .status-row { grid-template-columns: 14px 1fr; }
  .activity-link time, .activity-link code, .activity-link .token-pill, .status-row span, .status-row code { grid-column: 2; }
  .activity-content { margin-left: 22px; }
  .activity-content dl > div { grid-template-columns: 1fr; gap: 3px; }
  .agent-execution-head { flex-direction: column; }
  .agent-execution-meta { grid-template-columns: 1fr; }
  .request-form { grid-template-columns: 1fr; }
  .token-pill { justify-content: flex-start; }
  .dag-tier, .goal-grid { grid-template-columns: 1fr; }
  .brainstorm-intro { flex-direction: column; }
  .brainstorm-intro code { max-width: 100%; text-align: left; }
  .brainstorm-goal > summary { min-height: 0; }
  .brainstorm-goal-detail .detail-grid { grid-template-columns: 1fr; gap: 4px; }
  .token-activity-panel { --token-cell: 12px; --token-gap: 2px; }
  .token-activity-head { align-items: flex-start; flex-direction: column; }
  .token-tabs { align-self: stretch; }
  .token-tabs button { flex: 1; }
  .token-months { margin-left: 0; width: 100%; }
  .token-days { display: none; }
  .token-views { width: 100%; }
  .token-work-panel .section-head { align-items: flex-start; flex-direction: column; }
}
"""


def page_shell(title: str, active: str, subtitle: str, output: Path, body: str) -> str:
    nav = nav_targets()
    nav_values = {}
    for key, href in nav.items():
        nav_values[f"NAV_{key.upper()}_CLASS"] = "nav-item active" if key == active else "nav-item"
        nav_values[f"NAV_{key.upper()}_HREF"] = esc(href)
    return render_template(
        "workflow-shell.html",
        {
            "DOCUMENT_TITLE": esc(title),
            "ACTIVE_PAGE": esc(active),
            "DYNAMIC_CSS": generated_content_css(),
            "OUTPUT_NAME": esc(output.name),
            "OUTPUT_PATH": esc(output),
            "PAGE_TITLE": esc(title),
            "PAGE_SUBTITLE": esc(subtitle),
            "PAGE_BODY": body,
            "PAGE_SCRIPT": nav_script(),
            **nav_values,
        },
    )


def render_overview(
    plan: dict[str, Any] | None,
    brainstorm: dict[str, Any] | None,
    brainstorm_source: Path | None,
    events: list[dict[str, Any]],
    artifacts: list[Path],
    root: Path,
    *,
    include_workflow_activity: bool = True,
    include_dag: bool = True,
) -> str:
    stats = plan_stats(plan) if plan else {"total": 0, "done": 0, "progress": 0, "counter": Counter()}
    candidates = brainstorm.get("candidate_goals") if isinstance(brainstorm, dict) else []
    candidate_count = len(candidates) if isinstance(candidates, list) else 0
    recent = render_activity(events[:10], root)
    token_heatmap = render_token_heatmap(
        events,
        datetime.now().astimezone().date(),
        include_workflow_activity=include_workflow_activity,
    )
    tokens = token_summary(events)
    status_href = "status.html"
    plan_href = "plan.html"
    activity_href = "activity.html"
    brainstorm_href = "brainstorm.html"
    artifacts_href = "artifacts.html"
    subagents_href = "agents.html"
    observe_href = "observe.html"
    lower_sections = f"""
    <div class="grid">
      <div>{render_flow_graph(plan)}</div>
      <aside>{recent}</aside>
    </div>
    """
    return f"""
    <section id="overview" class="section-anchor">
      {token_heatmap}
      <section class="summary-grid">
      <a class="summary-card" href="{status_href}"><span class="muted">运行状态</span><strong>{stats['progress']}%</strong><p>已完成 {stats['done']}/{stats['total']} 个步骤</p></a>
      <a class="summary-card" href="{plan_href}"><span class="muted">计划进度</span><strong>{stats['progress']}%</strong><p>已完成 {stats['done']}/{stats['total']} 个步骤</p></a>
      <a class="summary-card" href="{activity_href}"><span class="muted">Tokens</span><strong>{fmt_int(tokens.get('tokens'))}</strong><p>{fmt_int(tokens.get('records'))} 条使用记录</p></a>
      <a class="summary-card" href="{activity_href}"><span class="muted">活动</span><strong>{len(events)}</strong><p>工作流事件</p></a>
      <a class="summary-card" href="{brainstorm_href}"><span class="muted">头脑风暴</span><strong>{candidate_count}</strong><p>候选目标</p></a>
      <a class="summary-card" href="{subagents_href}"><span class="muted">代理执行</span><strong>{sum(1 for step in (plan or {}).get('steps', []) if isinstance(step, dict) and step.get('subagent'))}</strong><p>当前计划代理步骤</p></a>
      <a class="summary-card" href="{observe_href}"><span class="muted">后台观察</span><strong>{sum(1 for step in (plan or {}).get('steps', []) if isinstance(step, dict) and step.get('status') == 'running')}</strong><p>运行中的 step 与 shell logs</p></a>
      <a class="summary-card" href="{artifacts_href}"><span class="muted">产物归档</span><strong>{len(artifacts)}</strong><p>最近文件</p></a>
      </section>
    </section>
    {lower_sections}
    """


def build_site(root: Path, output: Path) -> dict[str, str]:
    config = load_config(root)
    publish = publish_config(config)
    include_workflow_activity = as_bool(
        publish.get("include_workflow_activity", publish.get("include_activity_heatmap")),
        True,
    )
    include_dag = as_bool(publish.get("include_dag"), True)
    plan, _plan_source, current_thread = current_thread_plan(root, config)
    brainstorm, brainstorm_source = load_current_or_latest(
        root,
        config,
        "compat_brainstorm_file",
        "brainstorms_history_dir",
    )
    if current_thread and current_thread.get("id"):
        thread_brainstorm = thread_root(root, config) / str(current_thread["id"]) / "brainstorm.json"
        data = read_json(thread_brainstorm)
        if isinstance(data, dict):
            brainstorm, brainstorm_source = data, thread_brainstorm
    threads = collect_threads(root, config)
    change_requests = collect_change_requests(root, config)
    artifacts = collect_artifacts(root, config)
    events = collect_activity(root, config, artifacts)
    observe_module = load_observe_module()
    observe = observe_module.snapshot(root) if observe_module else {}
    project_slug = config.get("archive", {}).get("project_slug") if isinstance(config.get("archive"), dict) else None
    title = project_slug or root.name
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    site_dir = output.parent
    subtitle = f"生成时间：{generated_at}"
    pages = {
        "index.html": page_shell(
            f"AutoGoo 工作流 · {title}",
            "index",
            subtitle,
            output,
            render_overview(
                plan,
                brainstorm,
                brainstorm_source,
                events,
                artifacts,
                root,
                include_workflow_activity=include_workflow_activity,
                include_dag=include_dag,
            ),
        ),
    }
    pages.update(
        {
            "plan.html": page_shell(
                f"计划 · {title}",
                "plan",
                subtitle,
                site_dir / "plan.html",
                render_plan(plan, include_dag=include_dag),
            ),
            "threads.html": page_shell(
                f"Threads · {title}",
                "threads",
                subtitle,
                site_dir / "threads.html",
                render_threads(threads, root),
            ),
            "activity.html": page_shell(
                f"活动 · {title}",
                "activity",
                subtitle,
                site_dir / "activity.html",
                render_activity(events, root),
            ),
            "brainstorm.html": page_shell(
                f"头脑风暴 · {title}",
                "brainstorm",
                subtitle,
                site_dir / "brainstorm.html",
                render_brainstorm(brainstorm, brainstorm_source),
            ),
            "status.html": page_shell(
                f"运行状态 · {title}",
                "status",
                subtitle,
                site_dir / "status.html",
                render_status(plan, events),
            ),
            "observe.html": page_shell(
                f"观察 · {title}",
                "observe",
                subtitle,
                site_dir / "observe.html",
                render_observe(observe),
            ),
            "agents.html": page_shell(
                f"代理执行 · {title}",
                "subagents",
                subtitle,
                site_dir / "agents.html",
                render_agent_executions(plan),
            ),
            "artifacts.html": page_shell(
                f"产物归档 · {title}",
                "artifacts",
                subtitle,
                site_dir / "artifacts.html",
                render_artifacts(artifacts, root),
            ),
            "requests.html": page_shell(
                f"修改请求 · {title}",
                "requests",
                subtitle,
                site_dir / "requests.html",
                render_change_requests(change_requests, threads, plan, brainstorm, artifacts, root),
            ),
        }
    )
    for filename, html_text in pages.items():
        (site_dir / filename).write_text(html_text, encoding="utf-8")
    theme_source = plugin_root() / "skills" / "auto-goo" / "templates" / "publish" / "workflow-theme.css"
    if not theme_source.exists():
        raise SystemExit(f"required publish theme not found: {theme_source}")
    (site_dir / "workflow-theme.css").write_text(theme_source.read_text(encoding="utf-8"), encoding="utf-8")
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish AutoGoo workflow state as static HTML",
        epilog="Runtime shell: skills/auto-goo/templates/publish/workflow-shell.html",
    )
    parser.add_argument("--root", default=".", help="project root, defaults to current directory")
    parser.add_argument("--output", help="output HTML path, defaults to publish.index_file")
    parser.add_argument("--serve", action="store_true", help="serve the HTML site over HTTP")
    parser.add_argument("--host", help="HTTP host, defaults to publish.host")
    parser.add_argument("--port", type=int, help="HTTP port, defaults to publish.port")
    parser.add_argument("--live", action="store_true", help="rebuild HTML on every browser request")
    parser.add_argument("--no-open", action="store_true", help="do not open a browser window")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    config = load_config(root)
    publish = publish_config(config)
    if not as_bool(publish.get("enabled"), True):
        raise SystemExit("HTML publishing is disabled by .goo/config.json publish.enabled=false")
    output_text = args.output or publish.get("index_file") or publish.get("site_dir") or DEFAULT_PUBLISH_CONFIG["index_file"]
    output = (root / output_text).resolve() if not Path(str(output_text)).is_absolute() else Path(str(output_text))
    if output.is_dir():
        output = output / "index.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    build_site(root, output)
    print(f"AutoGoo HTML published: {output}")
    if args.serve:
        host = args.host or str(publish.get("host") or DEFAULT_PUBLISH_CONFIG["host"])
        port = args.port if args.port is not None else as_int(publish.get("port"), DEFAULT_PUBLISH_CONFIG["port"])
        open_browser = as_bool(publish.get("open_browser"), True) and not args.no_open
        return serve(root, output, host, port, live=args.live, open_browser=open_browser)
    return 0


def make_server(root: Path, output: Path, host: str, port: int, *, live: bool) -> ReusableThreadingHTTPServer:
    site_dir = output.parent
    config = load_config(root)
    allowed_pages = {
        "",
        "index.html",
        "threads.html",
        "plan.html",
        "activity.html",
        "brainstorm.html",
        "status.html",
        "observe.html",
        "agents.html",
        "artifacts.html",
        "requests.html",
        "workflow-theme.css",
    }

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def send_bytes(self, status: int, payload: bytes, content_type: str, cache_control: str = "no-store") -> None:
            self.close_connection = True
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", cache_control)
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            route = self.path.split("?", 1)[0].lstrip("/")
            if route == "api/health":
                body = json.dumps(
                    {
                        "ok": True,
                        "root": str(root),
                        "site_dir": str(site_dir),
                        "live": live,
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                self.send_bytes(200, body, "application/json; charset=utf-8")
                return
            if route.startswith("file/"):
                rel_text = unquote(route.removeprefix("file/"))
                target = (root / rel_text).resolve()
                try:
                    target.relative_to(root.resolve())
                except ValueError:
                    self.send_bytes(403, b"Forbidden", "text/plain; charset=utf-8")
                    return
                if not target.is_file():
                    self.send_bytes(404, b"Not Found", "text/plain; charset=utf-8")
                    return
                if target.stat().st_size > 50 * 1024 * 1024:
                    self.send_bytes(413, b"Payload Too Large", "text/plain; charset=utf-8")
                    return
                payload = target.read_bytes()
                content_type = "text/plain; charset=utf-8"
                if target.suffix.lower() in {".html", ".htm"}:
                    content_type = "text/html; charset=utf-8"
                elif target.suffix.lower() == ".json":
                    content_type = "application/json; charset=utf-8"
                elif target.suffix.lower() in {".md", ".txt", ".log"}:
                    content_type = "text/plain; charset=utf-8"
                self.send_bytes(200, payload, content_type)
                return
            page = "index.html" if route in ("", "/") else route
            if page not in allowed_pages:
                self.send_bytes(404, b"Not Found", "text/plain; charset=utf-8")
                return
            if live:
                build_site(root, output)
            page_path = site_dir / page
            body = page_path.read_text(encoding="utf-8")
            payload = body.encode("utf-8")
            content_type = "text/css; charset=utf-8" if page.endswith(".css") else "text/html; charset=utf-8"
            self.send_bytes(200, payload, content_type, "no-store, no-cache, must-revalidate")

        def do_POST(self) -> None:
            route = self.path.split("?", 1)[0]
            if route not in {"/api/change-request", "/api/change-request/status"}:
                self.send_bytes(404, b'{"error":"not found"}', "application/json; charset=utf-8")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > 65536:
                self.send_bytes(400, b'{"error":"invalid request length"}', "application/json; charset=utf-8")
                return
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.send_bytes(400, b'{"error":"invalid json"}', "application/json; charset=utf-8")
                return
            if route == "/api/change-request/status":
                try:
                    path = update_change_request_status(root, config, data)
                except ValueError as exc:
                    self.send_bytes(
                        400,
                        json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8"),
                        "application/json; charset=utf-8",
                    )
                    return
                if live:
                    build_site(root, output)
                body = json.dumps({"ok": True, "path": path.relative_to(root).as_posix()}, ensure_ascii=False).encode("utf-8")
                self.send_bytes(200, body, "application/json; charset=utf-8")
                return
            try:
                path = save_change_request(root, config, data)
            except ValueError as exc:
                self.send_bytes(
                    400,
                    json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8",
                )
                return
            if live:
                build_site(root, output)
            body = json.dumps({"ok": True, "path": path.relative_to(root).as_posix()}, ensure_ascii=False).encode("utf-8")
            self.send_bytes(201, body, "application/json; charset=utf-8")

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return ReusableThreadingHTTPServer((host, port), Handler)


def write_server_info(root: Path, output: Path, host: str, port: int, urls: list[str], *, live: bool) -> None:
    payload = {
        "host": host,
        "port": port,
        "urls": urls,
        "root": str(root),
        "site_dir": str(output.parent),
        "index": str(output),
        "health": f"http://{host if host not in ('0.0.0.0', '::') else '127.0.0.1'}:{port}/api/health",
        "live": live,
        "started_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    (output.parent / "server.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def local_ip_addresses() -> list[str]:
    addresses: set[str] = set()
    for probe in (socket.gethostname(), socket.getfqdn()):
        try:
            for info in socket.getaddrinfo(probe, None, socket.AF_INET, socket.SOCK_STREAM):
                address = info[4][0]
                if address and not address.startswith("127."):
                    addresses.add(address)
        except OSError:
            pass
    return sorted(addresses)


def display_urls(host: str, port: int) -> list[str]:
    if host in ("0.0.0.0", "::"):
        urls = [f"http://127.0.0.1:{port}/"]
        urls.extend(f"http://{address}:{port}/" for address in local_ip_addresses())
        return urls
    return [f"http://{host}:{port}/"]


def serve(root: Path, output: Path, host: str, port: int, *, live: bool, open_browser: bool) -> int:
    last_error: OSError | None = None
    server: ThreadingHTTPServer | None = None
    selected_port = port
    for candidate in range(port, port + 20):
        try:
            server = make_server(root, output, host, candidate, live=live)
            selected_port = candidate
            break
        except OSError as exc:
            last_error = exc
    if server is None:
        raise SystemExit(f"failed to start server near port {port}: {last_error}")

    urls = display_urls(host, selected_port)
    write_server_info(root, output, host, selected_port, urls, live=live)
    print(f"AutoGoo HTML server: {urls[0]}", flush=True)
    for url in urls[1:]:
        print(f"Remote URL: {url}", flush=True)
    if live:
        print("Live mode: rebuilding HTML on every request.", flush=True)
    print(f"Server info: {output.parent / 'server.json'}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if open_browser:
        try:
            webbrowser.open(urls[0])
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
