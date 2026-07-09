"""
Extract meaningful summaries from Claude Code and Codex session files for
AutoGoo daily reports. Supports both JSONL formats.

Usage:
  python daily-report-sessions.py --date 2026-05-07
  python daily-report-sessions.py --date 2026-05-07 --claude-only
  python daily-report-sessions.py --date 2026-05-07 --codex-only
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from glob import glob


def extract_claude_sessions(date_str):
    """Extract summaries from Claude CLI session files for a given date."""
    home = os.path.expanduser("~")
    claude_projects = os.path.join(home, ".claude", "projects")
    session_meta_dir = os.path.join(home, ".claude", "sessions")

    # Convert date to timestamps for filtering
    try:
        date_start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise SystemExit(f"invalid date: {date_str!r}, expected YYYY-MM-DD")
    date_end = datetime(date_start.year, date_start.month, date_start.day, 23, 59, 59, tzinfo=timezone.utc)
    start_ts = int(date_start.timestamp() * 1000)
    end_ts = int(date_end.timestamp() * 1000)

    # Read session metadata to find sessions from this date
    meta_sessions = {}
    if os.path.isdir(session_meta_dir):
        for f in os.listdir(session_meta_dir):
            if not f.endswith(".json"):
                continue
            fpath = os.path.join(session_meta_dir, f)
            try:
                with open(fpath) as fh:
                    meta = json.load(fh)
                started = meta.get("startedAt", 0)
                if start_ts <= started <= end_ts:
                    sid = meta.get("sessionId", "")
                    meta_sessions[sid] = {
                        "cwd": meta.get("cwd", ""),
                        "started_at": started,
                        "entrypoint": meta.get("entrypoint", ""),
                        "pid": meta.get("pid", ""),
                    }
            except (json.JSONDecodeError, OSError):
                continue

    # Find all JSONL conversation files modified today
    results = []
    found_sessions = set()

    for root, dirs, files in os.walk(claude_projects):
        for f in files:
            if not f.endswith(".jsonl"):
                continue
            fpath = os.path.join(root, f)
            mtime = os.path.getmtime(fpath)
            if not (date_start.timestamp() <= mtime <= date_end.timestamp() + 86400):
                continue

            proj_dir = os.path.basename(os.path.dirname(fpath))
            session_id = f.replace(".jsonl", "")

            # Try to get metadata for this session
            meta = meta_sessions.get(session_id, {})
            cwd = meta.get("cwd", proj_dir)
            started_at = meta.get("started_at", int(mtime * 1000))
            started_str = datetime.fromtimestamp(started_at / 1000).strftime("%H:%M")

            user_msgs, assistant_msgs = _parse_claude_jsonl(fpath)
            if not user_msgs:
                continue

            summary = _summarize_session(user_msgs, assistant_msgs)
            results.append({
                "source": "claude",
                "session_id": session_id,
                "cwd": cwd,
                "started_at": started_str,
                "user_count": len(user_msgs),
                "assistant_count": len(assistant_msgs),
                "summary": summary,
                "file": os.path.relpath(fpath, home),
            })
            found_sessions.add(session_id)

    # Sort by start time
    results.sort(key=lambda x: x["started_at"])
    return results


def _parse_claude_jsonl(fpath):
    """Parse a Claude JSONL conversation file."""
    user_msgs = []
    assistant_msgs = []
    try:
        with open(fpath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                typ = obj.get("type", "")
                if typ == "user":
                    msg = obj.get("message", {})
                    content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
                    if isinstance(content, list):
                        parts = []
                        for c in content:
                            if isinstance(c, dict):
                                t = c.get("text", "") or str(c)[:100]
                                parts.append(str(t)[:200])
                            elif isinstance(c, str):
                                parts.append(c[:200])
                        content = " | ".join(parts)
                    content = str(content).strip()
                    if content:
                        user_msgs.append(content[:500])
                elif typ in ("assistant", "assistant_message"):
                    msg = obj.get("message", {})
                    if isinstance(msg, dict):
                        content = msg.get("content", "")
                    else:
                        content = str(msg)
                    if isinstance(content, list):
                        parts = []
                        for c in content:
                            if isinstance(c, dict):
                                t = c.get("text", "") or str(c)[:200]
                                parts.append(str(t)[:200])
                            elif isinstance(c, str):
                                parts.append(c[:200])
                        content = "\n".join(parts)
                    content = str(content).strip()
                    if content:
                        assistant_msgs.append(content[:300])
    except OSError:
        pass
    return user_msgs, assistant_msgs


def extract_codex_sessions(date_str):
    """Extract summaries from Codex VSCode session files."""
    home = os.path.expanduser("~")
    try:
        year, month, day = date_str.split("-")
    except ValueError:
        return []
    sessions_dir = os.path.join(home, ".codex", "sessions", year, month, day)

    if not os.path.isdir(sessions_dir):
        return []

    results = []
    for f in sorted(os.listdir(sessions_dir)):
        if not f.endswith(".jsonl"):
            continue
        fpath = os.path.join(sessions_dir, f)

        # Parse timestamp from filename
        ts_match = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})", f)
        started_str = ""
        if ts_match:
            started_str = ts_match.group(1).replace("-", ":")  # normalize T time
            started_str = started_str.split("T")[1][:5] if "T" in started_str else ""

        user_msgs, assistant_msgs = _parse_codex_jsonl(fpath)
        if not user_msgs and not assistant_msgs:
            # Count total lines as a fallback
            try:
                with open(fpath) as fh:
                    line_count = sum(1 for _ in fh)
                if line_count < 5:
                    continue  # too short, skip
                results.append({
                    "source": "codex",
                    "session_id": f,
                    "cwd": "",
                    "started_at": started_str,
                    "user_count": 0,
                    "assistant_count": 0,
                    "summary": f"[{line_count} lines, minimal content]",
                    "file": os.path.relpath(fpath, home),
                })
            except OSError:
                pass
            continue

        summary = _summarize_codex_session(user_msgs, assistant_msgs)
        results.append({
            "source": "codex",
            "session_id": f,
            "cwd": user_msgs[0].get("cwd", "") if user_msgs else "",
            "started_at": started_str,
            "user_count": len(user_msgs),
            "assistant_count": len(assistant_msgs),
            "summary": summary,
            "file": os.path.relpath(fpath, home),
        })

    results.sort(key=lambda x: x["started_at"])
    return results


def _parse_codex_jsonl(fpath):
    """Parse a Codex JSONL session file."""
    user_msgs = []
    assistant_msgs = []
    try:
        with open(fpath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "event_msg":
                    continue
                payload = obj.get("payload", {})
                ptype = payload.get("type", "")

                if ptype == "user_message":
                    msg = payload.get("message", "")
                    cwd = payload.get("cwd", "")
                    images = payload.get("images", [])
                    local_images = payload.get("local_images", [])

                    # Extract user's actual request
                    request = ""
                    if "## My request for Codex:" in msg:
                        request = msg.split("## My request for Codex:")[1].strip()
                    elif "## My request" in msg:
                        request = msg.split("## My request")[1].strip()
                    else:
                        request = msg[:300]

                    # Clean up IDE context prefix
                    request = re.sub(r"# Context from my IDE setup:.*?(?=\n## My request)", "", msg, flags=re.DOTALL)
                    if "## My request" in request:
                        request = request.split("## My request")[-1]
                        if ":" in request:
                            request = request.split(":", 1)[1].strip()

                    if request:
                        user_msgs.append({
                            "text": request[:500],
                            "cwd": cwd,
                            "has_images": bool(images or local_images),
                        })
                elif ptype == "assistant_message":
                    msg = payload.get("message", "")
                    if isinstance(msg, str) and msg.strip():
                        assistant_msgs.append(msg[:300])
                elif ptype == "tool_use":
                    # Just count tool uses
                    pass
    except OSError:
        pass
    return user_msgs, assistant_msgs


def _summarize_session(user_msgs, assistant_msgs):
    """Summarize a Claude session based on user prompts."""
    prompts = [u[:300] for u in user_msgs]

    # Detect key topics from prompts
    topics = []
    key_files = []
    key_commands = []

    for p in prompts:
        p_lower = p.lower()

        # Detect file creation
        if any(w in p_lower for w in ["创建", "新增", "add", "create", "new file", "写一个"]):
            topics.append(("create", p[:150]))

        # Detect git operations
        if any(w in p_lower for w in ["git ", "push", "commit", "clone", "pull"]):
            topics.append(("git", p[:150]))

        # Detect SSH/config
        if any(w in p_lower for w in ["ssh", "密钥", "key", "配置"]):
            topics.append(("config", p[:150]))

        # Detect data generation
        if any(w in p_lower for w in ["生成", "generate", "qa", "数据"]):
            topics.append(("data", p[:150]))

        # Detect troubleshooting
        if any(w in p_lower for w in ["error", "失败", "报错", "问题", "修复", "bug", "fix"]):
            topics.append(("fix", p[:150]))

        # Detect plugin/skill
        if any(w in p_lower for w in ["plugin", "skill", "插件"]):
            topics.append(("plugin", p[:150]))

        # Detect refactoring
        if any(w in p_lower for w in ["重构", "refactor", "改造", "优化", "改"]):
            topics.append(("refactor", p[:150]))

    # Deduplicate and categorize
    seen_topics = []
    for cat, detail in topics:
        if cat not in [s[0] for s in seen_topics]:
            seen_topics.append((cat, detail))

    # Build summary text
    parts = []
    cat_names = {
        "create": "创建/新增",
        "git": "Git 操作",
        "config": "配置",
        "data": "数据生成",
        "fix": "修复/调试",
        "plugin": "Plugin/Skill",
        "refactor": "重构/优化",
    }
    for cat, detail in seen_topics[:5]:
        name = cat_names.get(cat, cat)
        parts.append(f"[{name}] {detail}")

    if not parts:
        # Fallback: use first few prompts
        for p in prompts[:3]:
            parts.append(p[:150])

    return "\n".join(parts[:5])


def _summarize_codex_session(user_msgs, assistant_msgs):
    """Summarize a Codex session based on user requests."""
    requests = [u["text"][:200] for u in user_msgs]

    parts = []
    for r in requests[:8]:
        parts.append(r)

    return "\n".join(parts)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Extract session data for daily report")
    parser.add_argument("--date", default="", help="Date in YYYY-MM-DD format (default: today)")
    parser.add_argument("--claude-only", action="store_true", help="Only extract Claude sessions")
    parser.add_argument("--codex-only", action="store_true", help="Only extract Codex sessions")
    args = parser.parse_args()

    date_str = args.date or datetime.now().strftime("%Y-%m-%d")

    all_sessions = []

    if not args.codex_only:
        claude_sessions = extract_claude_sessions(date_str)
        all_sessions.extend(claude_sessions)

    if not args.claude_only:
        codex_sessions = extract_codex_sessions(date_str)
        all_sessions.extend(codex_sessions)

    all_sessions.sort(key=lambda x: x["started_at"])

    print(json.dumps(all_sessions, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
