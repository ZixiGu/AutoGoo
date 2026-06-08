#!/usr/bin/env python3
"""Publish AutoGoo local workflow state as a static HTML site."""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import socket
import webbrowser
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any


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
    "host": "0.0.0.0",
    "port": 9877,
    "open_browser": True,
    "include_workflow_activity": True,
    "include_dag": True,
}


def read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
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


def collect_artifacts(root: Path, limit: int = 24) -> list[Path]:
    base = root / ".goo"
    candidates: list[Path] = []
    for rel in ("artifacts", "reports", "obsidian", "logs"):
        folder = base / rel
        if folder.exists():
            candidates.extend(path for path in folder.rglob("*") if path.is_file())
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[:limit]


def collect_json_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(folder.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)


def load_current_or_latest(root: Path, current: str, history: str) -> tuple[dict[str, Any] | None, Path | None]:
    current_path = root / ".goo" / current
    data = read_json(current_path)
    if isinstance(data, dict):
        return data, current_path
    for path in collect_json_files(root / ".goo" / history):
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
                    amount = int(usage.get(field) or 0)
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


def collect_activity(root: Path, artifacts: list[Path]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current_plan = root / ".goo" / "plan.json"
    current_brainstorm = root / ".goo" / "brainstorm.json"
    add_plan_events(events, current_plan, "current-plan")
    add_brainstorm_events(events, current_brainstorm, "current-brainstorm")
    for path in collect_json_files(root / ".goo" / "plans" / "history"):
        add_plan_events(events, path, "plan-history")
    for path in collect_json_files(root / ".goo" / "brainstorms" / "history"):
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
    tiers: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for step in steps:
        tier = step.get("tier")
        if not isinstance(tier, int):
            deps = step.get("depends_on") if isinstance(step.get("depends_on"), list) else []
            tier = len(deps) + 1
        tiers[tier].append(step)
    cards = []
    for tier in sorted(tiers):
        items = []
        for step in tiers[tier]:
            deps = step.get("depends_on") if isinstance(step.get("depends_on"), list) else []
            dep_names = [shorten(by_id.get(str(dep), {}).get("name") or dep, 24) for dep in deps]
            status = step.get("status", "pending")
            step_anchor = f"step-{slug(step.get('id'), 'step')}"
            items.append(
                f"""
                <a id="{esc(step_anchor)}" class="dag-node {esc(STATUS_CLASS.get(status, 'pending'))}" href="#plan" aria-label="在计划中查看步骤 #{esc(step.get('id'))}">
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


def render_flow_graph(plan: dict[str, Any] | None) -> str:
    if not plan:
        return '<section class="panel"><h2>任务流程</h2><p class="muted">暂无计划步骤。</p></section>'
    steps = [step for step in plan.get("steps", []) if isinstance(step, dict)]
    if not steps:
        return '<section class="panel"><h2>任务流程</h2><p class="muted">暂无计划步骤。</p></section>'

    tiers: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for step in steps:
        tier = step.get("tier")
        if not isinstance(tier, int):
            deps = step.get("depends_on") if isinstance(step.get("depends_on"), list) else []
            tier = len(deps) + 1
        tiers[tier].append(step)

    node_w, node_h = 190, 86
    x_gap, y_gap = 82, 34
    margin = 32
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
                f'<path d="M{x1},{y1} C{mid},{y1} {mid},{y2} {x2 - 8},{y2}" '
                'fill="none" stroke="#8c959f" stroke-width="1.5" marker-end="url(#arrow)" />'
            )
        status = step.get("status", "pending")
        cls_color = {
            "completed": "#30a14e",
            "running": "#0969da",
            "failed": "#cf222e",
            "paused": "#bc4c00",
        }.get(str(status), "#8c959f")
        title_lines = wrap_svg_text(step.get("name"), 18, 3)
        text_lines = "".join(
            f'<text x="{x + 14}" y="{y + 32 + index * 14}" class="flow-title">{esc(line)}</text>'
            for index, line in enumerate(title_lines)
        )
        nodes.append(
            f"""
            <g>
              <rect x="{x}" y="{y}" width="{node_w}" height="{node_h}" rx="8" fill="#ffffff" stroke="#d0d7de" />
              <rect x="{x}" y="{y}" width="5" height="{node_h}" rx="3" fill="{cls_color}" />
              <text x="{x + 14}" y="{y + 18}" class="flow-meta">#{esc(step.get('id'))} · {esc(status_label(status))}</text>
              {text_lines}
              <text x="{x + 14}" y="{y + node_h - 12}" class="flow-meta">{esc(step.get('type', 'step'))}</text>
            </g>
            """
        )

    return f"""
    <section class="panel flow-panel">
      <div class="section-head"><h2>任务流程</h2><span>{len(steps)} 个步骤</span></div>
      <div class="flow-scroll">
        <svg class="flow-svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="AutoGoo 任务流程图">
          <defs>
            <marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
              <path d="M0,0 L0,6 L9,3 z" fill="#8c959f" />
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
        step_anchor = f"step-{slug(step_id, 'step')}"
        goal_ref = step.get("goal_id") or step.get("goal_ids")
        agent = " / ".join(str(item) for item in (step.get("subagent"), step.get("task_agent")) if item)
        step_cards.append(
            f"""
            <article id="{esc(step_anchor)}" class="step-detail {esc(STATUS_CLASS.get(step_status, 'pending'))}">
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
        f'<a class="status-card" href="#plan"><span>{esc(status_label(name))}</span><strong>{count}</strong></a>'
        for name, count in sorted(stats["counter"].items())
    )
    rows = []
    for step in steps:
        status = step.get("status", "pending")
        step_anchor = f"step-{slug(step.get('id'), 'step')}"
        when = step.get("heartbeat_at") or step.get("started_at") or step.get("completed_at") or ""
        rows.append(
            f"""
            <a class="status-row" href="#{esc(step_anchor)}">
              <span class="dot {esc(STATUS_CLASS.get(status, 'pending'))}"></span>
              <strong>#{esc(step.get('id'))} {esc(shorten(step.get('name'), 72))}</strong>
              <span>{esc(status_label(status))}</span>
              <code>{esc(when or step.get('type', 'step'))}</code>
            </a>
            """
        )
    return f"""
    <section class="panel">
      <div class="section-head"><h2>运行状态</h2><span>已完成 {stats['done']}/{stats['total']} · {stats['progress']}%</span></div>
      <div class="progress"><span style="width:{stats['progress']}%"></span></div>
      <div class="status-grid">{chips or '<span class="muted">暂无步骤状态记录。</span>'}</div>
      <div class="status-list">{''.join(rows) or '<p class="muted">暂无计划步骤。</p>'}</div>
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
        items.append(
            f"""
            <li id="{esc(artifact_anchor)}"><a href="#artifacts"><code>{esc(rel)}</code><span>{size:,} bytes</span></a></li>
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
        "brainstorm": "brainstorm.html",
        "plan": "plan.html",
        "status": "status.html",
        "subagents": "agents.html",
        "artifacts": "artifacts.html",
    }


def nav_script() -> str:
    token_script = """
  <script>
    const clock = document.getElementById("liveClock");
    const themeToggle = document.getElementById("themeToggle");
    function applyTheme(theme) {
      document.documentElement.dataset.theme = theme;
      localStorage.setItem("autogoo-workflow-theme", theme);
      if (themeToggle) {
        const isDark = theme === "dark";
        themeToggle.textContent = isDark ? "☼" : "☾";
        themeToggle.setAttribute("aria-label", isDark ? "切换浅色模式" : "切换深色模式");
        themeToggle.setAttribute("title", isDark ? "切换浅色模式" : "切换深色模式");
      }
    }
    applyTheme(localStorage.getItem("autogoo-workflow-theme") || "light");
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
.flow-scroll { overflow-x: auto; padding: 10px 0; }
.flow-svg { display: block; max-width: none; }
.flow-title { fill: currentColor; font: 11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
.flow-meta { fill: #57606a; font: 9px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.dag { display: grid; gap: 12px; }
.dag-tier { display: grid; grid-template-columns: 80px repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; align-items: stretch; }
.dag-tier > h3 { margin: 0; color: var(--muted); }
.dag-node, .goal-card { border: 1px solid var(--line); border-left: 4px solid var(--line-strong); border-radius: 8px; padding: 12px; min-height: 128px; background: var(--panel-bg); color: var(--text); display: block; text-decoration: none; }
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
body[data-page="index"] { --page-accent: var(--green); }
body[data-page="plan"] { --page-accent: var(--blue); }
body[data-page="activity"] { --page-accent: var(--violet); }
body[data-page="brainstorm"] { --page-accent: var(--amber); }
body[data-page="status"] { --page-accent: var(--green); }
body[data-page="subagents"] { --page-accent: var(--cyan); }
body[data-page="artifacts"] { --page-accent: var(--violet); }
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
    plan_data = read_json(root / ".goo" / "plan.json")
    plan = plan_data if isinstance(plan_data, dict) else None
    brainstorm, brainstorm_source = load_current_or_latest(root, "brainstorm.json", "brainstorms/history")
    artifacts = collect_artifacts(root)
    events = collect_activity(root, artifacts)
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
    parser.add_argument("--serve", action="store_true", help="serve the HTML site on localhost")
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


def make_server(root: Path, output: Path, host: str, port: int, *, live: bool) -> HTTPServer:
    site_dir = output.parent
    allowed_pages = {"", "index.html", "plan.html", "activity.html", "brainstorm.html", "artifacts.html"}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            route = self.path.split("?", 1)[0].lstrip("/")
            page = "index.html" if route in ("", "/") else route
            if page not in allowed_pages:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Not Found")
                return
            if live:
                build_site(root, output)
            page_path = site_dir / page
            body = page_path.read_text(encoding="utf-8")
            payload = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return HTTPServer((host, port), Handler)


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
    server: HTTPServer | None = None
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
    print(f"AutoGoo HTML server: {urls[0]}")
    for url in urls[1:]:
        print(f"Remote URL: {url}")
    if live:
        print("Live mode: rebuilding HTML on every request.")
    print("Press Ctrl+C to stop.")
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
