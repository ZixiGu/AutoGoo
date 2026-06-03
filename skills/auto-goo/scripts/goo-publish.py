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
    "split_pages": False,
    "host": "0.0.0.0",
    "port": 9877,
    "open_browser": True,
    "include_activity_heatmap": True,
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


def render_value(value: Any) -> str:
    if isinstance(value, list):
        if not value:
            return '<span class="muted">none</span>'
        items = "".join(f"<li>{render_value(item)}</li>" for item in value)
        return f'<ul class="detail-list">{items}</ul>'
    if isinstance(value, dict):
        if not value:
            return '<span class="muted">none</span>'
        rows = "".join(
            f"<dt>{esc(key)}</dt><dd>{render_value(item)}</dd>"
            for key, item in value.items()
            if has_value(item)
        )
        empty = '<dd class="muted">none</dd>'
        return f'<dl class="detail-grid nested">{rows or empty}</dl>'
    return esc(value)


def inline_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "none"
    if isinstance(value, dict):
        return ", ".join(str(key) for key in value) if value else "none"
    return str(value) if has_value(value) else "none"


def render_fields(data: dict[str, Any], fields: list[tuple[str, str]]) -> str:
    rows = []
    for key, label in fields:
        value = data.get(key)
        if has_value(value):
            rows.append(f"<dt>{esc(label)}</dt><dd>{render_value(value)}</dd>")
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


def extract_template_style(name: str = "workflow-dashboard-prototype.html") -> str:
    text = read_publish_template(name)
    match = re.search(r"<style>(.*?)</style>", text, re.S)
    return match.group(1).strip() if match else ""


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
        if node.get("type") == "user":
            return node
        current = str(node.get("parentUuid") or "")
    return {}


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
                turn_id = str(user_turn.get("uuid") or obj.get("parentUuid") or obj.get("uuid") or when.isoformat())
                session_id = str(obj.get("sessionId") or "")
                key = (session_id, turn_id)
                row = grouped.setdefault(
                    key,
                    {
                        "time": when,
                        "type": "token-usage",
                        "title": "Claude Code token usage",
                        "detail": "",
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
        pieces.append(f"{row.get('records', 0)} records")
        row["detail"] = " · ".join(pieces)
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


def render_heatmap(events: list[dict[str, Any]], today: date) -> str:
    counts: dict[date, int] = defaultdict(int)
    for event in events:
        when = event.get("time")
        if isinstance(when, datetime):
            counts[when.date()] += 1
    start = today - timedelta(days=364)
    start -= timedelta(days=(start.weekday() + 1) % 7)
    weeks = []
    day = start
    max_count = max(counts.values(), default=0)
    while day <= today:
        week = []
        for _ in range(7):
            count = counts.get(day, 0)
            level = 0 if count == 0 else min(4, max(1, math.ceil(count / max(1, max_count) * 4)))
            week.append(
                f'<span class="heat-cell l{level}" title="{esc(day.isoformat())}: {count} activities"></span>'
            )
            day += timedelta(days=1)
        weeks.append('<div class="heat-week">' + "".join(week) + "</div>")
    month_labels = []
    seen: set[tuple[int, int]] = set()
    day = start
    index = 0
    while day <= today:
        key = (day.year, day.month)
        if day.day <= 7 and key not in seen:
            seen.add(key)
            month_labels.append(f'<span style="grid-column:{index + 1}">{esc(day.strftime("%b"))}</span>')
        day += timedelta(days=7)
        index += 1
    return f"""
    <section class="panel heat-panel">
      <div class="section-head">
        <h2>Workflow Activity</h2>
        <span>{len(events)} events</span>
      </div>
      <div class="heat-months">{"".join(month_labels)}</div>
      <div class="heat-body">
        <div class="heat-days"><span>Mon</span><span>Wed</span><span>Fri</span></div>
        <div class="heat-grid">{"".join(weeks)}</div>
      </div>
      <div class="heat-footer"><span>Less</span><span class="heat-cell l0"></span><span class="heat-cell l1"></span><span class="heat-cell l2"></span><span class="heat-cell l3"></span><span class="heat-cell l4"></span><span>More</span></div>
    </section>
    """


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
    parts = [f"{label}: {fmt_int(data.get('tokens'))} tokens", f"{fmt_int(data.get('records'))} records"]
    input_total = int(data.get("input_tokens") or 0) + int(data.get("cache_creation_input_tokens") or 0)
    output_total = int(data.get("output_tokens") or 0)
    cache_read = int(data.get("cache_read_input_tokens") or 0)
    if input_total or output_total or cache_read:
        parts.append(f"input {fmt_int(input_total)}")
        parts.append(f"output {fmt_int(output_total)}")
        parts.append(f"cache read {fmt_int(cache_read)}")
    return " · ".join(parts)


def token_cell_level(value: int, max_value: int) -> int:
    if value <= 0:
        return 0
    return min(4, max(1, math.ceil(value / max(1, max_value) * 4)))


def render_token_heatmap(events: list[dict[str, Any]], today: date) -> str:
    daily = token_daily_totals(events)
    if not daily:
        return """
        <section class="panel token-activity-panel">
          <div class="token-activity-head">
            <h2>Token Activity</h2>
            <span class="muted">No token usage records for this project.</span>
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

    def token_cell(label: str, data: dict[str, int], max_value: int) -> str:
        level = token_cell_level(int(data.get("tokens") or 0), max_value)
        title = token_title(label, data)
        return f'<span class="token-day l{level}" title="{esc(title)}" aria-label="{esc(title)}"></span>'

    def daily_cells() -> str:
        output = []
        for current in days:
            output.append(token_cell(current.isoformat(), daily.get(current, {}), max_daily))
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
                label = f"{week_start.isoformat()} to {week_end.isoformat()}"
                max_value = max_weekly
            else:
                data = cumulative.get(week_end, {})
                label = f"Through {week_end.isoformat()}"
                max_value = max_cumulative
            output.append(token_cell(label, data, max_value))
        return "".join(output)

    month_labels = []
    seen: set[tuple[int, int]] = set()
    for index, current in enumerate(days[::7]):
        key = (current.year, current.month)
        if current.day <= 7 and key not in seen:
            seen.add(key)
            month_labels.append(f'<span style="grid-column:{index + 1}">{esc(current.strftime("%b"))}</span>')
    totals = token_summary(events)
    return f"""
    <section class="panel token-activity-panel" data-token-activity data-active-view="daily">
      <div class="token-activity-head">
        <h2>Token Activity</h2>
        <div class="token-tabs" role="tablist" aria-label="Token activity view">
          <button type="button" class="active" data-token-view="daily">Daily</button>
          <button type="button" data-token-view="weekly">Weekly</button>
          <button type="button" data-token-view="cumulative">Cumulative</button>
        </div>
      </div>
      <div class="token-activity-total"><strong>{fmt_int(totals.get('tokens'))}</strong><span>tokens · {fmt_int(totals.get('records'))} usage records</span></div>
      <div class="token-months">{"".join(month_labels)}</div>
      <div class="token-heat-body">
        <div class="token-days"><span>Mon</span><span>Wed</span><span>Fri</span></div>
        <div class="token-views">
          <div class="token-grid active" data-token-panel="daily">{daily_cells()}</div>
          <div class="token-grid token-grid-period" data-token-panel="weekly">{period_cells("weekly")}</div>
          <div class="token-grid token-grid-period" data-token-panel="cumulative">{period_cells("cumulative")}</div>
        </div>
      </div>
      <div class="token-legend"><span>Less</span><span class="token-day l0"></span><span class="token-day l1"></span><span class="token-day l2"></span><span class="token-day l3"></span><span class="token-day l4"></span><span>More</span></div>
    </section>
    """


def render_dag(plan: dict[str, Any]) -> str:
    steps = [step for step in plan.get("steps", []) if isinstance(step, dict)]
    if not steps:
        return '<section class="panel"><h2>DAG</h2><p class="muted">No plan steps found.</p></section>'
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
                <a id="{esc(step_anchor)}" class="dag-node {esc(STATUS_CLASS.get(status, 'pending'))}" href="#plan" aria-label="View step #{esc(step.get('id'))} in Plan">
                  <div class="node-top"><strong>#{esc(step.get('id'))}</strong><span>{esc(status)}</span></div>
                  <h3>{esc(shorten(step.get('name'), 64))}</h3>
                  <p>{esc(shorten(step.get('description'), 110))}</p>
                  <small>{esc(step.get('type', 'step'))} · deps: {esc(", ".join(dep_names) or "none")}</small>
                </a>
                """
            )
        cards.append(f'<div class="dag-tier"><h3>Tier {tier}</h3>{"".join(items)}</div>')
    return f'<section class="panel"><div class="section-head"><h2>DAG</h2><span>{len(steps)} steps</span></div><div class="dag">{"".join(cards)}</div></section>'


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
        return '<section class="panel"><h2>Task Flow</h2><p class="muted">No plan steps found.</p></section>'
    steps = [step for step in plan.get("steps", []) if isinstance(step, dict)]
    if not steps:
        return '<section class="panel"><h2>Task Flow</h2><p class="muted">No plan steps found.</p></section>'

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
              <text x="{x + 14}" y="{y + 18}" class="flow-meta">#{esc(step.get('id'))} · {esc(status)}</text>
              {text_lines}
              <text x="{x + 14}" y="{y + node_h - 12}" class="flow-meta">{esc(step.get('type', 'step'))}</text>
            </g>
            """
        )

    return f"""
    <section class="panel flow-panel">
      <div class="section-head"><h2>Task Flow</h2><span>{len(steps)} steps</span></div>
      <div class="flow-scroll">
        <svg class="flow-svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="AutoGoo task flow diagram">
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
        return '<section class="panel"><h2>Current Plan</h2><p class="muted">No .goo/plan.json found.</p></section>'
    stats = plan_stats(plan)
    counter = stats["counter"]
    status = plan.get("status", "pending")
    chips = "".join(
        f'<span class="chip {esc(STATUS_CLASS.get(name, "pending"))}">{esc(name)} {count}</span>'
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
              <h3>{esc(goal.get("name") or goal.get("description") or "Goal")}</h3>
              {render_fields(goal, [
                  ("description", "Description"),
                  ("why", "Why"),
                  ("expected_output", "Expected output"),
                  ("outputs", "Outputs"),
                  ("acceptance_criteria", "Acceptance criteria"),
                  ("evidence", "Evidence"),
                  ("risk", "Risk"),
                  ("prerequisites", "Prerequisites"),
                  ("readiness_checklist", "Readiness checklist"),
                  ("first_step", "First step"),
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
              <div class="node-top"><strong>#{esc(step_id)} {esc(step.get("name", "Step"))}</strong><span class="status {esc(STATUS_CLASS.get(step_status, "pending"))}">{esc(step_status)}</span></div>
              <p>{esc(step.get("description", ""))}</p>
              <div class="step-meta">
                <span><strong>Goal</strong> {esc(inline_value(goal_ref))}</span>
                <span><strong>Agent</strong> {esc(agent or "unassigned")}</span>
                <span><strong>Progress</strong> {esc(step.get("progress", 0))}%</span>
                <span><strong>Depends on</strong> {esc(inline_value(step.get("depends_on")))}</span>
              </div>
              {render_fields(step, [
                  ("agent_id", "Agent id"),
                  ("type", "Type"),
                  ("available_skills", "Available skills"),
                  ("inputs", "Inputs"),
                  ("outputs", "Outputs"),
                  ("allowed_read_paths", "Allowed read paths"),
                  ("allowed_write_paths", "Allowed write paths"),
                  ("validation", "Validation"),
                  ("requires_user_confirm", "Requires user confirm"),
                  ("started_at", "Started at"),
                  ("heartbeat_at", "Heartbeat at"),
                  ("completed_at", "Completed at"),
                  ("blocked_at", "Blocked at"),
                  ("error", "Error"),
                  ("block_reason", "Block reason"),
                  ("approval_request", "Approval request"),
                  ("notes", "Notes"),
              ])}
            </article>
            """
        )
    top_fields = render_fields(
        plan,
        [
            ("version", "Version"),
            ("task_name", "Task name"),
            ("task", "Task"),
            ("status", "Status"),
            ("started_at", "Started at"),
            ("updated_at", "Updated at"),
            ("completed_at", "Completed at"),
        ],
    )
    return f"""
    <section class="panel">
      <div class="section-head"><h2>Current Plan</h2><span class="status {esc(STATUS_CLASS.get(status, "pending"))}">{esc(status)}</span></div>
      <h3>{esc(plan.get("task") or plan.get("task_name") or "Untitled AutoGoo task")}</h3>
      <div class="progress"><span style="width:{stats['progress']}%"></span></div>
      <p class="muted">{stats['done']}/{stats['total']} steps completed · {stats['progress']}%</p>
      <div class="chips">{chips}</div>
      {top_fields}
      {render_json_section("Context digest", plan.get("context_digest"))}
      {render_json_section("Wiki context", plan.get("wiki_context"))}
      {render_json_section("Context artifacts", plan.get("context_artifacts"))}
      {render_json_section("Review", plan.get("review"))}
      {render_json_section("Archive", plan.get("archive"))}
    </section>
    <section class="panel">
      <div class="section-head"><h2>Goals</h2><span>{len(goal_cards)} goals</span></div>
      <div class="detail-card-grid">{''.join(goal_cards) or '<p class="muted">No goals recorded.</p>'}</div>
    </section>
    <section class="panel">
      <div class="section-head"><h2>Plan Steps</h2><span>{len(step_cards)} steps</span></div>
      <div class="step-detail-list">{''.join(step_cards) or '<p class="muted">No plan steps found.</p>'}</div>
    </section>
    {render_flow_graph(plan)}
    {render_dag(plan) if include_dag else ""}
    """


def render_status(plan: dict[str, Any] | None, events: list[dict[str, Any]]) -> str:
    if not plan:
        return '<section class="panel"><h2>Running Status</h2><p class="muted">No .goo/plan.json found.</p></section>'
    stats = plan_stats(plan)
    steps = [step for step in plan.get("steps", []) if isinstance(step, dict)]
    chips = "".join(
        f'<a class="status-card" href="#plan"><span>{esc(name)}</span><strong>{count}</strong></a>'
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
              <span>{esc(status)}</span>
              <code>{esc(when or step.get('type', 'step'))}</code>
            </a>
            """
        )
    recent = render_activity(events[:8], Path("/__autogoo_no_rel__")) if events else ""
    return f"""
    <section class="panel">
      <div class="section-head"><h2>Running Status</h2><span>{stats['done']}/{stats['total']} completed · {stats['progress']}%</span></div>
      <div class="progress"><span style="width:{stats['progress']}%"></span></div>
      <div class="status-grid">{chips or '<span class="muted">No step status recorded.</span>'}</div>
      <div class="status-list">{''.join(rows) or '<p class="muted">No plan steps found.</p>'}</div>
    </section>
    {recent}
    """


def render_subagents(auto_goo_root: Path) -> str:
    roles = sorted((auto_goo_root / "agents" / "roles").glob("*.md"))
    task_agents = sorted((auto_goo_root / "agents" / "tasks").glob("*/*.md"))
    departments = Counter(path.parent.name for path in task_agents)
    department_cards = "".join(
        f'<a class="status-card" href="#subagents"><span>{esc(name)}</span><strong>{count}</strong></a>'
        for name, count in sorted(departments.items())
    )
    svg_path = auto_goo_root / "docs" / "assets" / "autogoo-subagent-architecture.svg"
    svg = svg_path.read_text(encoding="utf-8") if svg_path.exists() else ""
    return f"""
    <section class="panel subagent-panel">
      <div class="section-head"><h2>Subagent Architecture</h2><span>{len(roles)} roles · {len(task_agents)} task agents</span></div>
      <p class="muted">Role agents map to <code>subagent</code>; task agents map to <code>task_agent</code>.</p>
      <div class="subagent-figure">{svg or '<p class="muted">Architecture diagram not found.</p>'}</div>
      <div class="status-grid">
        <a class="status-card" href="#subagents"><span>roles</span><strong>{len(roles)}</strong></a>
        <a class="status-card" href="#subagents"><span>task agents</span><strong>{len(task_agents)}</strong></a>
        {department_cards}
      </div>
    </section>
    """


def render_brainstorm(data: dict[str, Any] | None, source: Path | None = None) -> str:
    if not data:
        return """
        <section class="panel">
          <div class="section-head"><h2>Brainstorm</h2><span>0 candidates</span></div>
          <p class="muted">No current .goo/brainstorm.json or brainstorm history found.</p>
        </section>
        """
    goals = data.get("candidate_goals") or data.get("goals") or []
    items = []
    for goal in goals if isinstance(goals, list) else []:
        if not isinstance(goal, dict):
            continue
        goal_anchor = f"brainstorm-{slug(goal.get('id') or goal.get('name'), 'goal')}"
        items.append(
            f"""
            <article id="{esc(goal_anchor)}" class="goal-card brainstorm-detail">
              <div class="node-top"><strong>{esc(goal.get('id', 'goal'))}</strong><span>{esc(goal.get('priority_hint', ''))}</span></div>
              <h3>{esc(goal.get('name', 'Candidate goal'))}</h3>
              {render_fields(goal, [
                  ("description", "Description"),
                  ("why", "Why"),
                  ("expected_output", "Expected output"),
                  ("acceptance_criteria", "Acceptance criteria"),
                  ("evidence", "Evidence"),
                  ("risk", "Risk"),
                  ("prerequisites", "Prerequisites"),
                  ("readiness_checklist", "Readiness checklist"),
                  ("first_step", "First step"),
                  ("depends_on", "Depends on"),
              ])}
            </article>
            """
        )
    return f"""
    <section class="panel">
      <div class="section-head"><h2>Brainstorm</h2><span>{len(items)} candidates</span></div>
      <p class="muted">{esc(data.get("direction") or data.get("topic") or data.get("task") or "")}</p>
      <p class="muted"><code>{esc(source or '.goo/brainstorm.json')}</code></p>
      {render_fields(data, [
          ("status", "Status"),
          ("selected_goal_id", "Selected goal"),
          ("created_at", "Created at"),
          ("updated_at", "Updated at"),
          ("review", "Review"),
          ("constraints", "Constraints"),
          ("open_questions", "Open questions"),
      ])}
      <div class="goal-grid">{''.join(items) or '<p class="muted">No candidate goals recorded.</p>'}</div>
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
        rows.append(
            f"""
            <li id="{esc(event_anchor)}" class="activity-row">
              <a class="activity-link" href="#activity" aria-label="View activity {index}">
                <span class="dot {esc(STATUS_CLASS.get(event.get('status'), 'pending'))}"></span>
                <div><strong>{esc(event.get('title'))}</strong><p>{esc(event.get('detail'))}</p></div>
                {token_cell}
                <time>{esc(when)}</time>
                <code>{esc(rel)}</code>
              </a>
            </li>
            """
        )
    return f"""
    <section class="panel">
      <div class="section-head"><h2>Contribution Activity</h2><span>latest {min(len(events), 80)} · token usage included</span></div>
      <ol class="activity-list">{''.join(rows) or '<li class="muted">No activity found.</li>'}</ol>
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
      <div class="section-head"><h2>Artifacts</h2><span>{len(paths)} recent</span></div>
      <ul class="artifact-list">{''.join(items) or '<li class="muted">No artifacts found.</li>'}</ul>
    </section>
    """


def nav_pages(split_pages: bool) -> list[tuple[str, str, str]]:
    if not split_pages:
        return [
            ("index", "总览", "#overview"),
            ("brainstorm", "头脑风暴", "#brainstorm"),
            ("plan", "计划", "#plan"),
            ("status", "运行状态", "#status"),
            ("subagents", "子代理", "#subagents"),
            ("artifacts", "产物归档", "#artifacts"),
        ]
    return [
        ("index", "总览", "index.html"),
        ("brainstorm", "头脑风暴", "brainstorm.html"),
        ("plan", "计划", "plan.html"),
        ("status", "运行状态", "index.html#status"),
        ("subagents", "子代理", "index.html#subagents"),
        ("artifacts", "产物归档", "artifacts.html"),
    ]


def render_nav(active: str, *, split_pages: bool) -> str:
    pages = nav_pages(split_pages)
    links = []
    for key, label, href in pages:
        cls = "nav-item active" if key == active else "nav-item"
        badge = '<span class="nav-badge live">实时</span>' if key == "status" else ""
        links.append(
            f'<a class="{cls}" href="{href}"><span class="nav-icon"></span><span class="nav-text">{esc(label)}</span>{badge}</a>'
        )
    return '<div class="nav-section"><div class="nav-label">工作区</div>' + "".join(links) + "</div>"


def nav_script(split_pages: bool) -> str:
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
    document.querySelectorAll("[data-token-activity]").forEach((widget) => {
      widget.querySelectorAll("[data-token-view]").forEach((button) => {
        button.addEventListener("click", () => {
          const view = button.dataset.tokenView;
          widget.dataset.activeView = view || "daily";
          widget.querySelectorAll("[data-token-view]").forEach((item) => item.classList.toggle("active", item === button));
          widget.querySelectorAll("[data-token-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.tokenPanel === view));
        });
      });
    });
    tick();
    setInterval(tick, 1000);
  </script>
"""
    return token_script


def generated_content_css() -> str:
    return """

/* Dynamic sections rendered by goo-publish.py. The page shell, sidebar, theme,
   and base component language come from templates/publish/workflow-*.html. */
.section-anchor { scroll-margin-top: 16px; }
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
.detail-card-grid, .goal-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-top: 12px; }
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
.token-activity-panel { background: var(--token-panel-bg, var(--panel-bg)); color: var(--token-text, var(--text)); border-color: var(--token-panel-border, var(--line)); overflow-x: auto; }
.token-activity-head { display: flex; justify-content: space-between; align-items: center; gap: 16px; min-width: max-content; margin-bottom: 8px; }
.token-tabs { display: inline-flex; gap: 4px; }
.token-tabs button { appearance: none; border: 0; background: var(--token-control-bg, var(--soft-bg)); color: var(--token-muted, var(--muted)); font: inherit; font-weight: 700; padding: 4px 8px; border-radius: 4px; cursor: pointer; }
.token-tabs button.active { color: var(--token-control-active-text, var(--green)); background: var(--token-control-active, #eaf6ef); }
.token-activity-total { display: flex; align-items: baseline; gap: 10px; margin-top: 8px; color: var(--muted); min-width: max-content; }
.token-months { display: grid; grid-auto-flow: column; grid-auto-columns: 14px; gap: 3px; margin: 14px 0 6px 44px; color: var(--muted); min-width: max-content; }
.token-heat-body { display: flex; gap: 8px; }
.token-days { display: grid; grid-template-rows: repeat(7, 14px); gap: 3px; color: var(--muted); width: 36px; font-size: 12px; }
.token-days span:nth-child(1) { grid-row: 2; } .token-days span:nth-child(2) { grid-row: 4; } .token-days span:nth-child(3) { grid-row: 6; }
.token-activity-panel[data-active-view="weekly"] .token-days, .token-activity-panel[data-active-view="cumulative"] .token-days { display: none; }
.token-activity-panel[data-active-view="weekly"] .token-months, .token-activity-panel[data-active-view="cumulative"] .token-months { margin-left: 0; }
.token-views { position: relative; min-width: max-content; }
.token-grid { display: none; gap: 3px; }
.token-grid.active, .token-grid-period.active { display: flex; }
.token-grid-period .token-day { width: 14px; height: 32px; }
.token-week { display: grid; grid-template-rows: repeat(7, 14px); gap: 3px; }
.token-day { width: 14px; height: 14px; border-radius: 3px; display: inline-block; background: var(--token-empty, #edf2f7); border: 1px solid var(--token-border, #d8e2dc); }
.token-day.l1 { background: var(--token-1, #dff7e8); } .token-day.l2 { background: var(--token-2, #9be7b3); } .token-day.l3 { background: var(--token-3, #46b86f); } .token-day.l4 { background: var(--token-4, #1f883d); }
.token-legend { display: flex; align-items: center; justify-content: flex-end; gap: 4px; color: var(--muted); margin-top: 10px; min-width: max-content; }
.flow-panel { overflow: hidden; }
.flow-scroll { overflow-x: auto; padding: 10px 0; }
.flow-svg { display: block; max-width: none; }
.flow-title { fill: currentColor; font: 11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
.flow-meta { fill: #57606a; font: 9px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.dag { display: grid; gap: 12px; }
.dag-tier { display: grid; grid-template-columns: 80px repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; align-items: stretch; }
.dag-tier > h3 { margin: 0; color: var(--muted); }
.dag-node, .goal-card { border: 1px solid var(--line); border-left: 4px solid var(--line-strong); border-radius: 8px; padding: 12px; min-height: 128px; background: var(--panel-bg); color: var(--text); display: block; text-decoration: none; }
.brainstorm-detail { min-height: 0; }
.activity-list, .artifact-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }
.activity-link { display: grid; grid-template-columns: 14px minmax(0, 1fr) 112px 130px minmax(120px, .5fr); gap: 10px; align-items: start; color: var(--text); border-radius: 8px; padding: 8px; text-decoration: none; }
.token-pill { display: inline-flex; justify-content: flex-end; color: var(--green); font: 12px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space: nowrap; }
.token-pill.empty { color: var(--muted); }
.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--line-strong); margin-top: 6px; }
.dot.done { background: var(--green); } .dot.running { background: var(--blue); } .dot.failed { background: var(--red); }
.artifact-list a { display: flex; justify-content: space-between; gap: 12px; color: var(--text); border-radius: 8px; padding: 8px; text-decoration: none; }
.subagent-panel .muted code { color: inherit; }
.subagent-figure { overflow-x: auto; margin: 14px 0; border: 1px solid var(--line); border-radius: 8px; background: #0f172a; }
.subagent-figure svg { display: block; min-width: 900px; width: 100%; height: auto; }
@media (max-width: 860px) {
  .grid, .hero, .detail-grid, .detail-grid.nested { grid-template-columns: 1fr; }
  .activity-link, .status-row { grid-template-columns: 14px 1fr; }
  .activity-link time, .activity-link code, .activity-link .token-pill, .status-row span, .status-row code { grid-column: 2; }
  .token-pill { justify-content: flex-start; }
  .dag-tier { grid-template-columns: 1fr; }
}
"""


def site_css() -> str:
    template_css = extract_template_style()
    if template_css:
        return template_css + generated_content_css()
    return """
    :root {
      color-scheme: light;
      --bg: #f4f5f7; --panel: #ffffff; --text: #1f2328; --muted: #667085; --line: #d7dce2;
      --line-strong: #afb8c1; --nav: #111827; --surface-subtle: #f8fafc;
      --green1: #d8f3df; --green2: #7bd88f; --green3: #2f9e44; --green4: #1b6b34;
      --blue: #2563eb; --blue-soft: #dbeafe; --orange: #b45309; --red: #b42318; --purple: #6d28d9;
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body { margin: 0; font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
    header { border-bottom: 1px solid var(--line); background: var(--panel); position: sticky; top: 0; z-index: 2; box-shadow: 0 1px 0 rgba(17,24,39,.02); }
    .wrap { max-width: 1240px; margin: 0 auto; padding: 18px 24px; }
    .hero { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 16px; align-items: end; }
    h1, h2, h3, p { margin: 0; }
    h1 { font-size: 22px; font-weight: 700; letter-spacing: 0; }
    h2 { font-size: 16px; font-weight: 700; }
    h3 { font-size: 14px; font-weight: 700; margin-top: 8px; }
    code { font: 12px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; color: #57606a; }
    a { color: var(--blue); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .muted { color: var(--muted); }
    .tabs { display: flex; flex-wrap: wrap; gap: 18px; margin-top: 14px; border-top: 1px solid #eef1f4; padding-top: 12px; }
    .tabs a { color: var(--muted); padding: 4px 0 7px; border-bottom: 2px solid transparent; font-weight: 600; }
    .tabs a.active { color: var(--nav); border-color: var(--blue); }
    .section-anchor { scroll-margin-top: 104px; }
    .grid { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(300px, .75fr); gap: 16px; margin-top: 16px; }
    .summary-grid, .goal-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 12px; }
    .detail-card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-top: 12px; }
    .panel, .summary-card { background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 16px; margin-bottom: 16px; }
    .panel { box-shadow: 0 1px 2px rgba(16,24,40,.03); }
    .summary-card { color: var(--text); position: relative; overflow: hidden; }
    .summary-card::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: var(--blue); }
    .summary-card strong { display: block; font-size: 24px; line-height: 1.1; margin-top: 8px; }
    .section-head, .node-top { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
    .status-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-top: 12px; }
    .status-card { border: 1px solid var(--line); border-radius: 6px; padding: 12px; color: var(--text); background: var(--surface-subtle); }
    .status-card strong { display: block; font-size: 22px; margin-top: 4px; }
    .status-card span { color: var(--muted); }
    .status-card:hover, .status-row:hover { border-color: var(--line-strong); background: #fff; text-decoration: none; }
    .status-list { display: grid; gap: 8px; margin-top: 12px; }
    .status-row { display: grid; grid-template-columns: 14px minmax(0, 1fr) 92px minmax(120px, .4fr); gap: 10px; align-items: center; border: 1px solid var(--line); border-radius: 6px; padding: 10px; color: var(--text); }
    .status, .chip { border: 1px solid var(--line); border-radius: 999px; padding: 2px 8px; font-size: 12px; white-space: nowrap; background: var(--surface-subtle); }
    .done { color: var(--green4); } .running { color: var(--blue); } .failed { color: var(--red); } .paused { color: var(--orange); } .blocked { color: var(--purple); }
    .progress { height: 10px; background: #eaeef2; border-radius: 999px; overflow: hidden; margin-top: 14px; }
    .progress span { display: block; height: 100%; background: var(--green3); }
    .chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
    .compact { padding-left: 18px; margin: 8px 0 0; }
    .detail-section { border-top: 1px solid var(--line); margin-top: 14px; padding-top: 12px; }
    .detail-grid { display: grid; grid-template-columns: minmax(130px, .28fr) minmax(0, 1fr); gap: 8px 14px; margin: 12px 0 0; }
    .detail-grid.nested { grid-template-columns: minmax(110px, .24fr) minmax(0, 1fr); margin-top: 0; }
    .detail-grid dt { color: var(--muted); font-weight: 700; }
    .detail-grid dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
    .detail-list { margin: 0; padding-left: 18px; }
    .detail-card, .step-detail { border: 1px solid var(--line); border-left: 4px solid var(--blue); border-radius: 6px; padding: 14px; background: var(--surface-subtle); }
    .step-detail-list { display: grid; gap: 12px; margin-top: 12px; }
    .step-detail { border-left-color: #8c959f; background: var(--panel); }
    .step-detail.done { border-left-color: var(--green3); } .step-detail.running { border-left-color: var(--blue); } .step-detail.failed { border-left-color: var(--red); } .step-detail.blocked { border-left-color: var(--purple); }
    .step-detail > p { color: var(--text); margin-top: 8px; }
    .step-meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; margin: 12px 0; }
    .step-meta span { border: 1px solid var(--line); border-radius: 6px; padding: 8px; background: var(--surface-subtle); min-width: 0; overflow-wrap: anywhere; }
    .step-meta strong { display: block; color: var(--muted); font-size: 12px; margin-bottom: 2px; }
    .heat-panel { overflow-x: auto; }
    .heat-months { display: grid; grid-auto-flow: column; grid-auto-columns: 13px; gap: 3px; margin-left: 44px; color: var(--muted); min-width: max-content; }
    .heat-body { display: flex; gap: 8px; margin-top: 4px; }
    .heat-days { display: grid; grid-template-rows: repeat(7, 13px); gap: 3px; color: var(--muted); width: 36px; }
    .heat-days span:nth-child(1) { grid-row: 2; } .heat-days span:nth-child(2) { grid-row: 4; } .heat-days span:nth-child(3) { grid-row: 6; }
    .heat-grid { display: flex; gap: 3px; }
    .heat-week { display: grid; grid-template-rows: repeat(7, 13px); gap: 3px; }
    .heat-cell { width: 13px; height: 13px; border-radius: 3px; display: inline-block; background: #ebedf0; border: 1px solid rgba(27,31,36,.06); }
    .heat-cell.l1 { background: var(--green1); } .heat-cell.l2 { background: var(--green2); } .heat-cell.l3 { background: var(--green3); } .heat-cell.l4 { background: var(--green4); }
    .heat-footer { display: flex; align-items: center; justify-content: flex-end; gap: 4px; color: var(--muted); margin-top: 10px; }
    .token-activity-panel { background: var(--panel); color: var(--text); border-color: var(--line); overflow-x: auto; }
    .token-activity-head { display: flex; justify-content: space-between; align-items: center; gap: 16px; min-width: max-content; }
    .token-activity-head h2 { color: var(--text); }
    .token-tabs { display: inline-flex; gap: 4px; }
    .token-tabs button { appearance: none; border: 0; background: var(--surface-subtle); color: var(--muted); font: inherit; font-weight: 700; padding: 4px 8px; border-radius: 4px; cursor: pointer; }
    .token-tabs button.active { color: var(--green4); background: #eaf6ef; }
    .token-tabs button:focus-visible { outline: 2px solid var(--green3); outline-offset: 2px; }
    .token-activity-total { display: flex; align-items: baseline; gap: 10px; margin-top: 8px; color: var(--muted); min-width: max-content; }
    .token-activity-total strong { color: var(--text); font-size: 18px; }
    .token-months { display: grid; grid-auto-flow: column; grid-auto-columns: 14px; gap: 3px; margin: 14px 0 6px 44px; color: var(--muted); min-width: max-content; }
    .token-heat-body { display: flex; gap: 8px; }
    .token-days { display: grid; grid-template-rows: repeat(7, 14px); gap: 3px; color: var(--muted); width: 36px; font-size: 12px; }
    .token-days span:nth-child(1) { grid-row: 2; } .token-days span:nth-child(2) { grid-row: 4; } .token-days span:nth-child(3) { grid-row: 6; }
    .token-activity-panel[data-active-view="weekly"] .token-days, .token-activity-panel[data-active-view="cumulative"] .token-days { display: none; }
    .token-activity-panel[data-active-view="weekly"] .token-months, .token-activity-panel[data-active-view="cumulative"] .token-months { margin-left: 0; }
    .token-views { position: relative; min-width: max-content; }
    .token-grid { display: none; gap: 3px; }
    .token-grid.active { display: flex; }
    .token-grid-period.active { display: flex; align-items: center; gap: 3px; }
    .token-grid-period .token-day { width: 14px; height: 32px; }
    .token-week { display: grid; grid-template-rows: repeat(7, 14px); gap: 3px; }
    .token-day { width: 14px; height: 14px; border-radius: 3px; display: inline-block; background: #edf2f7; border: 1px solid #d8e2dc; }
    .token-day.l1 { background: #dff7e8; } .token-day.l2 { background: #9be7b3; } .token-day.l3 { background: #46b86f; } .token-day.l4 { background: #1f883d; }
    .token-legend { display: flex; align-items: center; justify-content: flex-end; gap: 4px; color: var(--muted); margin-top: 10px; min-width: max-content; }
    .flow-panel { overflow: hidden; background: linear-gradient(180deg, #fff, #f9fafb); }
    .flow-scroll { overflow-x: auto; padding: 10px 0; }
    .flow-svg { display: block; max-width: none; }
    .flow-title { fill: #24292f; font: 11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    .flow-meta { fill: #57606a; font: 9px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    .dag { display: grid; gap: 12px; }
    .dag-tier { display: grid; grid-template-columns: 80px repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; align-items: stretch; }
    .dag-tier > h3 { margin: 0; color: var(--muted); }
    .dag-node, .goal-card { border: 1px solid var(--line); border-left: 4px solid #8c959f; border-radius: 6px; padding: 12px; min-height: 128px; background: var(--panel); }
    .dag-node, .goal-card { color: var(--text); display: block; }
    .brainstorm-detail { min-height: 0; }
    .dag-node:hover, .goal-card:hover, .activity-link:hover, .artifact-list a:hover { border-color: var(--line-strong); background: var(--surface-subtle); text-decoration: none; }
    .dag-node:focus-visible, .goal-card:focus-visible, .activity-link:focus-visible, .artifact-list a:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
    .dag-node.done, .goal-card.done { border-left-color: var(--green3); } .dag-node.running { border-left-color: var(--blue); } .dag-node.failed { border-left-color: var(--red); }
    .dag-node p, .goal-card p { color: var(--muted); margin: 6px 0; }
    .activity-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }
    .activity-row { border-bottom: 1px solid #e5e7eb; padding-bottom: 10px; }
    .activity-link { display: grid; grid-template-columns: 14px minmax(0, 1fr) 112px 130px minmax(120px, .5fr); gap: 10px; align-items: start; color: var(--text); border-radius: 6px; padding: 8px; margin: -8px; }
    .activity-row p { color: var(--muted); }
    .token-pill { display: inline-flex; justify-content: flex-end; color: var(--green4); font: 12px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space: nowrap; }
    .token-pill.empty { color: var(--muted); }
    .dot { width: 10px; height: 10px; border-radius: 50%; background: #8c959f; margin-top: 6px; }
    .dot.done { background: var(--green3); } .dot.running { background: var(--blue); } .dot.failed { background: var(--red); }
    .artifact-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }
    .artifact-list li { border-bottom: 1px solid #e5e7eb; padding-bottom: 8px; }
    .artifact-list a { display: flex; justify-content: space-between; gap: 12px; color: var(--text); border-radius: 6px; padding: 8px; margin: -8px; }
    .subagent-panel .muted code { color: inherit; }
    .subagent-figure { overflow-x: auto; margin: 14px 0; border: 1px solid var(--line); border-radius: 6px; background: #0f172a; }
    .subagent-figure svg { display: block; min-width: 900px; width: 100%; height: auto; }
    @media (max-width: 860px) { .grid, .hero { grid-template-columns: 1fr; } .activity-link, .status-row { grid-template-columns: 14px 1fr; } .activity-link time, .activity-link code, .activity-link .token-pill, .status-row span, .status-row code { grid-column: 2; } .token-pill { justify-content: flex-start; } .dag-tier, .detail-grid, .detail-grid.nested { grid-template-columns: 1fr; } }
    """


def page_shell(title: str, active: str, subtitle: str, output: Path, body: str, *, split_pages: bool) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <style>{site_css()}</style>
</head>
<body data-page="{esc(active)}">
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark"></div>
        <div>
          <h1>AutoGoo</h1>
          <span>工作流发布</span>
        </div>
      </div>
      {render_nav(active, split_pages=split_pages)}
      <div class="sidebar-card">
        <strong>{esc(output.name)}</strong>
        <p>{esc(output)}</p>
        <div class="mini-progress"><span></span></div>
      </div>
    </aside>
    <main class="main">
      <div class="topbar compact-topbar">
        <button class="top-action theme-toggle" id="themeToggle" type="button" aria-label="切换深色模式" title="切换深色模式">☾</button>
      </div>
      <section class="page-title">
        <div>
          <h2>{esc(title)}</h2>
          <p>{esc(subtitle)}</p>
        </div>
        <div class="live-pill"><span class="live-dot"></span><span id="liveClock">仅模板展示</span></div>
      </section>
      {body}
    </main>
  </div>
  {nav_script(split_pages)}
</body>
</html>
"""


def render_overview(
    plan: dict[str, Any] | None,
    brainstorm: dict[str, Any] | None,
    brainstorm_source: Path | None,
    events: list[dict[str, Any]],
    artifacts: list[Path],
    root: Path,
    *,
    include_activity_heatmap: bool = True,
    include_dag: bool = True,
    split_pages: bool = False,
) -> str:
    stats = plan_stats(plan) if plan else {"total": 0, "done": 0, "progress": 0, "counter": Counter()}
    candidates = brainstorm.get("candidate_goals") if isinstance(brainstorm, dict) else []
    candidate_count = len(candidates) if isinstance(candidates, list) else 0
    recent = render_activity(events[:10], root)
    heatmap = render_heatmap(events, datetime.now().astimezone().date()) if include_activity_heatmap else ""
    token_heatmap = render_token_heatmap(events, datetime.now().astimezone().date())
    tokens = token_summary(events)
    if split_pages:
        status_href = "index.html#status"
        plan_href, activity_href, brainstorm_href, artifacts_href = "plan.html", "activity.html", "brainstorm.html", "artifacts.html"
        subagents_href = "index.html#subagents"
        lower_sections = f"""
    <div id="status" class="section-anchor">{render_status(plan, events)}</div>
    <div class="grid">
      <div>{render_flow_graph(plan)}</div>
      <aside>{recent}</aside>
    </div>
    <div id="subagents" class="section-anchor">{render_subagents(plugin_root())}</div>
    """
    else:
        status_href = "#status"
        plan_href, activity_href, brainstorm_href, artifacts_href = "#plan", "#activity", "#brainstorm", "#artifacts"
        subagents_href = "#subagents"
        lower_sections = f"""
    <div id="status" class="section-anchor">{render_status(plan, events)}</div>
    <div id="plan" class="section-anchor">{render_plan(plan, include_dag=include_dag)}</div>
    <div id="brainstorm" class="section-anchor">{render_brainstorm(brainstorm, brainstorm_source)}</div>
    <div id="activity" class="section-anchor">{render_activity(events, root)}</div>
    <div id="subagents" class="section-anchor">{render_subagents(plugin_root())}</div>
    <div id="artifacts" class="section-anchor">{render_artifacts(artifacts, root)}</div>
    """
    return f"""
    <section id="overview" class="section-anchor">
      {token_heatmap}
      {heatmap}
      <section class="summary-grid">
      <a class="summary-card" href="{status_href}"><span class="muted">Status</span><strong>{stats['progress']}%</strong><p>{stats['done']}/{stats['total']} steps completed</p></a>
      <a class="summary-card" href="{plan_href}"><span class="muted">Plan progress</span><strong>{stats['progress']}%</strong><p>{stats['done']}/{stats['total']} steps completed</p></a>
      <a class="summary-card" href="{activity_href}"><span class="muted">Tokens</span><strong>{fmt_int(tokens.get('tokens'))}</strong><p>{fmt_int(tokens.get('records'))} usage records</p></a>
      <a class="summary-card" href="{activity_href}"><span class="muted">Activity</span><strong>{len(events)}</strong><p>workflow events</p></a>
      <a class="summary-card" href="{brainstorm_href}"><span class="muted">Brainstorm</span><strong>{candidate_count}</strong><p>candidate goals</p></a>
      <a class="summary-card" href="{subagents_href}"><span class="muted">Subagents</span><strong>Roles</strong><p>architecture and task agents</p></a>
      <a class="summary-card" href="{artifacts_href}"><span class="muted">Artifacts</span><strong>{len(artifacts)}</strong><p>recent files</p></a>
      </section>
    </section>
    {lower_sections}
    """


def build_site(root: Path, output: Path) -> dict[str, str]:
    config = load_config(root)
    publish = publish_config(config)
    split_pages = as_bool(publish.get("split_pages"), False)
    include_activity_heatmap = as_bool(publish.get("include_activity_heatmap"), True)
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
    subtitle = f"Generated at {generated_at}"
    pages = {
        "index.html": page_shell(
            f"AutoGoo Workflow · {title}",
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
                include_activity_heatmap=include_activity_heatmap,
                include_dag=include_dag,
                split_pages=split_pages,
            ),
            split_pages=split_pages,
        ),
    }
    if split_pages:
        pages.update(
            {
                "plan.html": page_shell(
                    f"Plan · {title}",
                    "plan",
                    subtitle,
                    site_dir / "plan.html",
                    render_plan(plan, include_dag=include_dag),
                    split_pages=split_pages,
                ),
                "activity.html": page_shell(
                    f"Activity · {title}",
                    "activity",
                    subtitle,
                    site_dir / "activity.html",
                    (render_heatmap(events, datetime.now().astimezone().date()) if include_activity_heatmap else "")
                    + render_activity(events, root),
                    split_pages=split_pages,
                ),
                "brainstorm.html": page_shell(
                    f"Brainstorm · {title}",
                    "brainstorm",
                    subtitle,
                    site_dir / "brainstorm.html",
                    render_brainstorm(brainstorm, brainstorm_source),
                    split_pages=split_pages,
                ),
                "artifacts.html": page_shell(
                    f"Artifacts · {title}",
                    "artifacts",
                    subtitle,
                    site_dir / "artifacts.html",
                    render_artifacts(artifacts, root),
                    split_pages=split_pages,
                ),
            }
        )
    for filename, html_text in pages.items():
        (site_dir / filename).write_text(html_text, encoding="utf-8")
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish AutoGoo workflow state as static HTML",
        epilog="Reference templates: skills/auto-goo/templates/publish/workflow-*.html",
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
