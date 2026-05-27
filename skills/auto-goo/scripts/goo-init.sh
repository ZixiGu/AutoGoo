#!/usr/bin/env bash
# AutoGoo: interactive configuration initializer
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  goo-init.sh [--user|--project] [--wiki-dir PATH] [--project-slug SLUG] [--yes] [--force] [--update-claude-md] [--skip-claude-md]

Options:
  --user            Write user-level config to ~/.auto-goo/config.json
  --project         Write project-level config to .goo/config.json
  --wiki-dir PATH   Set Goo-wiki directory (default: ~/workspace/Goo-wiki)
  --project-slug SLUG
                    Set Goo-wiki project archive folder name (default: project directory name)
  --yes             Use defaults for unanswered prompts
  --force           Overwrite existing config without asking
  --update-claude-md
                    Update project CLAUDE.md without asking
  --skip-claude-md  Do not update project CLAUDE.md when Goo-wiki is available
  -h, --help        Show this help
EOF
}

SCOPE=""
WIKI_DIR="${AUTO_GOO_WIKI_DIR:-}"
WIKI_DIR_PROVIDED=0
PROJECT_SLUG=""
YES=0
FORCE=0
UPDATE_CLAUDE_MD=0
SKIP_CLAUDE_MD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user)
      SCOPE="user"
      shift
      ;;
    --project)
      SCOPE="project"
      shift
      ;;
    --wiki-dir)
      if [[ $# -lt 2 ]]; then
        echo "error: --wiki-dir requires a path" >&2
        exit 2
      fi
      WIKI_DIR="$2"
      WIKI_DIR_PROVIDED=1
      shift 2
      ;;
    --project-slug)
      if [[ $# -lt 2 ]]; then
        echo "error: --project-slug requires a value" >&2
        exit 2
      fi
      PROJECT_SLUG="$2"
      shift 2
      ;;
    --yes|-y)
      YES=1
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --update-claude-md)
      UPDATE_CLAUDE_MD=1
      shift
      ;;
    --skip-claude-md)
      SKIP_CLAUDE_MD=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$UPDATE_CLAUDE_MD" -eq 1 && "$SKIP_CLAUDE_MD" -eq 1 ]]; then
  echo "error: --update-claude-md and --skip-claude-md cannot be used together" >&2
  exit 2
fi

prompt() {
  local message="$1"
  local default_value="$2"
  local answer

  if [[ "$YES" -eq 1 || ! -t 0 ]]; then
    printf '%s\n' "$default_value"
    return
  fi

  read -r -p "$message [$default_value]: " answer
  if [[ -z "$answer" ]]; then
    printf '%s\n' "$default_value"
  else
    printf '%s\n' "$answer"
  fi
}

confirm() {
  local message="$1"
  local default_value="${2:-n}"
  local answer

  if [[ "$YES" -eq 1 || "$FORCE" -eq 1 || ! -t 0 ]]; then
    [[ "$default_value" == "y" ]]
    return
  fi

  read -r -p "$message [y/N]: " answer
  answer="${answer:-$default_value}"
  [[ "$answer" == "y" || "$answer" == "Y" || "$answer" == "yes" || "$answer" == "YES" ]]
}

expand_path() {
  local raw="$1"
  if [[ "$raw" == "~" ]]; then
    printf '%s\n' "$HOME"
  elif [[ "$raw" == "~/"* ]]; then
    printf '%s/%s\n' "$HOME" "${raw#\~/}"
  else
    printf '%s\n' "$raw"
  fi
}

ensure_wiki_vault() {
  local wiki_dir="$1"
  WIKI_CREATED=0

  if [[ ! -d "$wiki_dir" ]]; then
    mkdir -p "$wiki_dir"
    WIKI_CREATED=1
  fi

  mkdir -p \
    "$wiki_dir/wiki/projects" \
    "$wiki_dir/wiki/concepts" \
    "$wiki_dir/wiki/questions" \
    "$wiki_dir/journal/daily" \
    "$wiki_dir/journal/weekly"

  if [[ ! -f "$wiki_dir/CLAUDE.md" ]]; then
    cat > "$wiki_dir/CLAUDE.md" <<'EOF'
# Goo-wiki Instructions

This vault stores reusable project memory for AutoGoo workflows.

- Put project notes under `wiki/projects/`.
- Put reusable concepts under `wiki/concepts/`.
- Put daily and weekly work logs under `journal/daily/` and `journal/weekly/`.
- Keep `log.md` as a compact activity index.
EOF
    WIKI_CREATED=1
  fi

  if [[ ! -f "$wiki_dir/log.md" ]]; then
    printf '# Goo-wiki Log\n' > "$wiki_dir/log.md"
    WIKI_CREATED=1
  fi
}

project_root() {
  git rev-parse --show-toplevel 2>/dev/null || pwd
}

default_project_slug() {
  local root="$1"
  local raw
  raw="$(basename "$root")"
  raw="$(printf '%s\n' "$raw" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9._-]+/-/g; s/^-+//; s/-+$//; s/-+/-/g')"
  if [[ -z "$raw" ]]; then
    raw="project"
  fi
  printf '%s\n' "$raw"
}

git_remote_url() {
  local root="$1"
  local remote
  if ! git -C "$root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return 1
  fi
  if git -C "$root" remote get-url origin 2>/dev/null; then
    return 0
  fi
  remote="$(git -C "$root" remote 2>/dev/null | sed -n '1p')"
  if [[ -n "$remote" ]]; then
    git -C "$root" remote get-url "$remote" 2>/dev/null
    return $?
  fi
  return 1
}

prompt_secret() {
  local message="$1"
  local answer

  if [[ "$YES" -eq 1 || ! -t 0 ]]; then
    printf '%s\n' ""
    return
  fi

  read -r -s -p "$message: " answer
  echo >&2
  printf '%s\n' "$answer"
}

save_server_secrets() {
  local secrets_file="$1"
  local ip="$2"
  local user="$3"
  local pass="$4"
  local secrets_dir
  secrets_dir="$(dirname "$secrets_file")"

  mkdir -p "$secrets_dir"
  python3 - "$secrets_file" "$ip" "$user" "$pass" <<'PY'
import json
import sys
from pathlib import Path

secrets_file = Path(sys.argv[1])
ip = sys.argv[2]
user = sys.argv[3]
password = sys.argv[4]

if secrets_file.exists():
    try:
        secrets = json.loads(secrets_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        secrets = []
else:
    secrets = []

if not isinstance(secrets, list):
    secrets = []

secrets.append({"ip": ip, "user": user, "password": password})
secrets_file.write_text(json.dumps(secrets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
  chmod 600 "$secrets_file"
}

if [[ -z "$SCOPE" ]]; then
  if [[ ! -t 0 ]]; then
    echo "error: cannot choose init scope in non-interactive mode" >&2
    echo "hint: pass --user or --project explicitly" >&2
    exit 2
  fi
  SCOPE="$(prompt "Configure AutoGoo for user or project? (user/project)" "user")"
fi

case "$SCOPE" in
  user)
    CONFIG_DIR="$HOME/.auto-goo"
    CONFIG_FILE="$CONFIG_DIR/config.json"
    FALLBACK_DIR=".goo/obsidian"
    ;;
  project)
    ROOT="$(project_root)"
    CONFIG_DIR="$ROOT/.goo"
    CONFIG_FILE="$CONFIG_DIR/config.json"
    FALLBACK_DIR=".goo/obsidian"
    ;;
  *)
    echo "error: scope must be 'user' or 'project'" >&2
    exit 2
    ;;
esac

if [[ -z "$WIKI_DIR" ]]; then
  if [[ ! -t 0 ]]; then
    echo "error: cannot choose wiki_dir in non-interactive mode" >&2
    echo "hint: pass --wiki-dir ~/workspace/Goo-wiki or another Goo-wiki path explicitly" >&2
    exit 2
  fi
  DEFAULT_WIKI_DIR="$HOME/workspace/Goo-wiki"
  WIKI_DIR="$(prompt "Goo-wiki directory (press Enter to use default)" "$DEFAULT_WIKI_DIR")"
  WIKI_DIR_PROVIDED=1
elif [[ "$WIKI_DIR_PROVIDED" -eq 0 && -n "${AUTO_GOO_WIKI_DIR:-}" ]]; then
  WIKI_DIR_PROVIDED=1
fi

WIKI_DIR_EXPANDED="$(expand_path "$WIKI_DIR")"
WIKI_READY=0
WIKI_CREATED=0
PROJECT_ARCHIVE_DIR=""
FALLBACK_PROJECT_ARCHIVE_DIR=""
GIT_REMOTE_URL=""

if [[ "$SCOPE" == "project" ]]; then
  SECRETS_FILE="$CONFIG_DIR/secrets.json"
else
  SECRETS_FILE="$CONFIG_DIR/secrets.json"
fi

SERVERS_JSON="[]"
CONFIG_WRITE_SKIPPED=0

if [[ -t 0 && "$YES" -ne 1 ]]; then
  if confirm "Do you have remote servers to configure?" "n"; then
    SERVERS_JSON="["
    FIRST=1
    while true; do
      echo ""
      echo "--- Server $((FIRST == 0 ? $(echo "$SERVERS_JSON" | grep -o '"ip"' | wc -l) + 1 : 1)) ---"
      SERVER_TYPE="$(prompt "Server type (cpu/gpu)" "cpu")"
      read -r -p "Server IP address: " SERVER_IP
      if [[ -z "$SERVER_IP" ]]; then
        echo "IP address is required, skipping this server."
        break
      fi
      read -r -p "Username: " SERVER_USER
      if [[ -z "$SERVER_USER" ]]; then
        echo "Username is required, skipping this server."
        break
      fi
      read -r -p "SSH port [22]: " SERVER_PORT
      SERVER_PORT="${SERVER_PORT:-22}"
      read -r -p "Purpose (e.g. model training, data processing): " SERVER_PURPOSE
      if [[ -z "$SERVER_PURPOSE" ]]; then
        echo "Purpose is required, skipping this server."
        break
      fi
      SERVER_PASS="$(prompt_secret "Password (input hidden, Enter to skip)")"

      save_server_secrets "$SECRETS_FILE" "$SERVER_IP" "$SERVER_USER" "$SERVER_PASS"

      if [[ "$FIRST" -eq 1 ]]; then
        FIRST=0
      else
        SERVERS_JSON="$SERVERS_JSON,"
      fi
      SERVERS_JSON="$SERVERS_JSON{\"ip\": \"$SERVER_IP\", \"user\": \"$SERVER_USER\", \"port\": \"$SERVER_PORT\", \"type\": \"$SERVER_TYPE\", \"purpose\": \"$SERVER_PURPOSE\", \"secrets_file\": \"$SECRETS_FILE\"}"

      if ! confirm "Add another server?" "n"; then
        break
      fi
    done
    SERVERS_JSON="$SERVERS_JSON]"
  fi
fi

load_existing_servers_json() {
  local config_file="$1"
  if [[ ! -f "$config_file" ]]; then
    printf '[]\n'
    return
  fi
  python3 - "$config_file" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    config = json.loads(path.read_text(encoding="utf-8"))
except (json.JSONDecodeError, OSError):
    print("[]")
    raise SystemExit(0)

servers = config.get("servers")
if not servers:
    servers = config.get("compute_servers")
if not isinstance(servers, list):
    servers = []
print(json.dumps(servers, ensure_ascii=False))
PY
}

if [[ "$SCOPE" == "project" ]]; then
  DEFAULT_PROJECT_SLUG="$(default_project_slug "$ROOT")"
  if [[ -z "$PROJECT_SLUG" ]]; then
    PROJECT_SLUG="$(prompt "Goo-wiki project archive slug" "$DEFAULT_PROJECT_SLUG")"
  fi
  PROJECT_SLUG="$(default_project_slug "$PROJECT_SLUG")"
  PROJECT_ARCHIVE_DIR="wiki/projects/$PROJECT_SLUG"
  FALLBACK_PROJECT_ARCHIVE_DIR="$FALLBACK_DIR/$PROJECT_SLUG"
  GIT_REMOTE_URL="$(git_remote_url "$ROOT" || true)"
fi

echo ""
echo "AutoGoo init"
echo "  scope:      $SCOPE"
echo "  config:     $CONFIG_FILE"
echo "  wiki_dir:   $WIKI_DIR"
if [[ "$SCOPE" == "project" ]]; then
  echo "  project:    $PROJECT_SLUG"
  if [[ -n "$GIT_REMOTE_URL" ]]; then
    echo "  git remote: $GIT_REMOTE_URL"
  fi
fi
if [[ "$SERVERS_JSON" != "[]" ]]; then
  SERVER_COUNT=$(echo "$SERVERS_JSON" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
  echo "  servers:    $SERVER_COUNT server(s) configured"
  echo "  secrets:    $SECRETS_FILE"
fi

ensure_wiki_vault "$WIKI_DIR_EXPANDED"
if [[ "$WIKI_CREATED" -eq 1 ]]; then
  WIKI_READY=1
  echo "  wiki check: created ($WIKI_DIR_EXPANDED/CLAUDE.md)"
else
  WIKI_READY=1
  echo "  wiki check: ready ($WIKI_DIR_EXPANDED/CLAUDE.md)"
fi

if [[ -f "$CONFIG_FILE" && "$FORCE" -ne 1 ]]; then
  echo ""
  echo "Existing config found:"
  sed -n '1,120p' "$CONFIG_FILE"
  echo ""
  if ! confirm "Overwrite $CONFIG_FILE?" "n"; then
    CONFIG_WRITE_SKIPPED=1
    echo "Skipped config write. Existing config kept."
    if [[ "$SCOPE" != "project" || "$SKIP_CLAUDE_MD" -eq 1 ]]; then
      exit 0
    fi
    if [[ "$UPDATE_CLAUDE_MD" -ne 1 && ("$YES" -eq 1 || ! -t 0) ]]; then
      echo "Project CLAUDE.md was not updated; rerun with --update-claude-md to add configuration."
      exit 0
    fi
    if [[ "$SERVERS_JSON" == "[]" ]]; then
      SERVERS_JSON="$(load_existing_servers_json "$CONFIG_FILE")"
    fi
  fi
fi

if [[ "$SCOPE" == "project" && "$WIKI_READY" -eq 1 ]]; then
  mkdir -p "$WIKI_DIR_EXPANDED/$PROJECT_ARCHIVE_DIR"
  echo "  archive root: $WIKI_DIR_EXPANDED/$PROJECT_ARCHIVE_DIR"
  if [[ -n "$GIT_REMOTE_URL" ]]; then
    python3 - "$WIKI_DIR_EXPANDED/$PROJECT_ARCHIVE_DIR/index.md" "$PROJECT_SLUG" "$ROOT" "$GIT_REMOTE_URL" <<'PY'
import sys
from pathlib import Path

target = Path(sys.argv[1])
project_slug = sys.argv[2]
project_root = sys.argv[3]
git_remote_url = sys.argv[4]

begin = "<!-- AUTO-GOO-PROJECT-META-BEGIN -->"
end = "<!-- AUTO-GOO-PROJECT-META-END -->"
block = f"""{begin}
## Project Metadata

- Project slug: `{project_slug}`
- Local path: `{project_root}`
- Git repository: `{git_remote_url}`
{end}
"""

if target.exists():
    text = target.read_text(encoding="utf-8")
else:
    text = f"# {project_slug}\n"

if begin in text and end in text:
    prefix, rest = text.split(begin, 1)
    _, suffix = rest.split(end, 1)
    new_text = prefix.rstrip() + "\n\n" + block + suffix.lstrip("\n")
else:
    new_text = text.rstrip() + "\n\n" + block

target.write_text(new_text, encoding="utf-8")
PY
    echo "  project page: updated git repository in $WIKI_DIR_EXPANDED/$PROJECT_ARCHIVE_DIR/index.md"
  fi
fi

if [[ "$CONFIG_WRITE_SKIPPED" -eq 0 ]]; then
  mkdir -p "$CONFIG_DIR"

  python3 - "$CONFIG_FILE" "$WIKI_DIR" "$FALLBACK_DIR" "$PROJECT_SLUG" "$PROJECT_ARCHIVE_DIR" "$FALLBACK_PROJECT_ARCHIVE_DIR" "$GIT_REMOTE_URL" "$SERVERS_JSON" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
wiki_dir = sys.argv[2]
fallback_dir = sys.argv[3]
project_slug = sys.argv[4]
project_archive_dir = sys.argv[5]
fallback_project_archive_dir = sys.argv[6]
git_remote_url = sys.argv[7]
servers_json = sys.argv[8]

config = {
    "version": 1,
    "wiki_dir": wiki_dir,
    "wiki": {
        "search_paths": [
            "wiki/projects",
            "wiki/concepts",
            "journal/weekly",
            "log.md",
        ],
    },
    "archive": {
        "enabled": True,
        "fallback_dir": fallback_dir,
        "plan_history_dir": ".goo/plans/history",
        "brainstorm_history_dir": ".goo/brainstorms/history",
    },
    "execution": {
        "max_concurrent": 6,
        "heartbeat_seconds": 30,
        "stale_after_seconds": 120,
    },
    "planning": {
        "recall_wiki": True,
        "require_wiki_context": False,
    },
    "init": {
        "prompt_for_scope": True,
        "prompt_for_wiki_dir": True,
    },
}

if project_slug:
    config["archive"]["project_slug"] = project_slug
    config["archive"]["project_dir"] = project_archive_dir
    config["archive"]["fallback_project_dir"] = fallback_project_archive_dir
    if git_remote_url:
        config["archive"]["git_remote_url"] = git_remote_url

try:
    servers = json.loads(servers_json)
    if servers:
        config["servers"] = servers
except (json.JSONDecodeError, ValueError):
    pass

target.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

  if [[ "$SCOPE" == "project" && -f "$SECRETS_FILE" ]]; then
    GITIGNORE="$ROOT/.gitignore"
    if [[ -f "$GITIGNORE" ]]; then
      if ! grep -qF '.goo/secrets.json' "$GITIGNORE" 2>/dev/null; then
        echo '.goo/secrets.json' >> "$GITIGNORE"
        echo "Added .goo/secrets.json to .gitignore"
      fi
    else
      echo '.goo/secrets.json' > "$GITIGNORE"
      echo "Created .gitignore with .goo/secrets.json"
    fi
  fi

  echo ""
  echo "Wrote $CONFIG_FILE"
else
  echo ""
  echo "Kept $CONFIG_FILE"
fi

if [[ "$SCOPE" == "project" && "$SKIP_CLAUDE_MD" -ne 1 ]]; then
  PROJECT_CLAUDE_MD="$ROOT/CLAUDE.md"
  SHOULD_UPDATE_CLAUDE_MD=0
  if [[ "$UPDATE_CLAUDE_MD" -eq 1 ]]; then
    SHOULD_UPDATE_CLAUDE_MD=1
  elif [[ "$YES" -eq 1 || ! -t 0 ]]; then
    echo "Project CLAUDE.md was not updated; rerun with --update-claude-md to add configuration."
  elif [[ "$SERVERS_JSON" != "[]" && "$WIKI_READY" -eq 1 ]]; then
    if confirm "Update $PROJECT_CLAUDE_MD with server config and archive principles?" "y"; then
      SHOULD_UPDATE_CLAUDE_MD=1
    else
      echo "Skipped project CLAUDE.md update by user choice."
    fi
  elif [[ "$SERVERS_JSON" != "[]" ]]; then
    if confirm "Update $PROJECT_CLAUDE_MD with server config?" "y"; then
      SHOULD_UPDATE_CLAUDE_MD=1
    else
      echo "Skipped project CLAUDE.md update by user choice."
    fi
  elif [[ "$WIKI_READY" -eq 1 ]]; then
    if confirm "Add Goo-wiki archive principles to $PROJECT_CLAUDE_MD?" "y"; then
      SHOULD_UPDATE_CLAUDE_MD=1
    else
      echo "Skipped project CLAUDE.md update by user choice."
    fi
  fi

  if [[ "$SHOULD_UPDATE_CLAUDE_MD" -eq 1 ]]; then
    set +e
    python3 - "$PROJECT_CLAUDE_MD" "$WIKI_DIR" "$FALLBACK_PROJECT_ARCHIVE_DIR" "$PROJECT_ARCHIVE_DIR" "$SERVERS_JSON" "$WIKI_READY" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
wiki_dir = sys.argv[2]
fallback_project_dir = sys.argv[3]
project_archive_dir = sys.argv[4]
servers_json = sys.argv[5]
wiki_ready = sys.argv[6] == "1"

begin = "<!-- AUTO-GOO-WIKI-ARCHIVE-BEGIN -->"
end = "<!-- AUTO-GOO-WIKI-ARCHIVE-END -->"

server_section = ""
try:
    servers = json.loads(servers_json)
    if servers:
        def server_purpose(server):
            raw = str(server.get("purpose") or "").strip()
            if raw and raw != "-":
                return raw
            server_type = str(server.get("type") or "").strip().lower()
            if server_type == "gpu":
                return "用于 GPU 相关任务：模型训练、推理评测、批量生成、图像/数据处理等重算力步骤。"
            if server_type == "cpu":
                return "用于 CPU 相关任务：数据整理、预处理、轻量脚本、索引构建和批量文件操作。"
            return "用于本项目需要远程算力或长时间后台执行的步骤。"

        def usage_hint(server, purpose):
            server_type = str(server.get("type") or "").strip().lower()
            if server_type == "gpu":
                return f"{purpose} 当任务涉及训练、推理、批量评测、自动标注图片生成或本机资源不足时优先使用。"
            if server_type == "cpu":
                return f"{purpose} 当任务主要是数据清洗、格式转换、批处理或不需要 GPU 时优先使用。"
            return f"{purpose} 使用前先确认任务是否需要远程环境、长时间运行或特定依赖。"

        lines = ["\n## 远程服务器\n"]
        lines.append("| IP | 端口 | 用户名 | 类型 | 用途 | 密码来源 |")
        lines.append("|---|------|--------|------|------|----------|")
        for s in servers:
            purpose = server_purpose(s)
            lines.append(f"| {s['ip']} | {s.get('port', '22')} | {s['user']} | {s['type']} | {purpose} | `{s['secrets_file']}` |")
        lines.append("")
        lines.append("### 何时使用")
        for s in servers:
            purpose = server_purpose(s)
            lines.append(f"- **{s['ip']}**（{s['type']}）：{usage_hint(s, purpose)}连接信息见 `{s['secrets_file']}`。")
        lines.append("")
        lines.append(f"config 位于 `.goo/config.json`，secrets 位于 `.goo/secrets.json`（chmod 600，已加入 .gitignore）。")
        lines.append("连接远程服务器由 AutoGoo 工具读取 `.goo/config.json` 与 `.goo/secrets.json` 处理；执行任务时必须显式选择目标服务器，不依赖默认第一个。")
        lines.append("不得把 secrets 展开到命令行、日志、计划正文或 subagent prompt。")
        lines.append("")
        lines.append("添加新服务器：")
        lines.append("```bash")
        lines.append("/auto-goo:goo-init --project  # 交互式输入服务器信息")
        lines.append("```")
        server_section = "\n".join(lines)
except (json.JSONDecodeError, ValueError):
    pass

archive_section = ""
if wiki_ready:
    archive_section = f"""## AutoGoo / Goo-wiki 归档原则

- 本项目启用 Goo-wiki 作为项目记忆层；规划前先检索 `{wiki_dir}` 中相关项目页、概念页、周报和 `log.md`，复用已有约束、命令、路径、指标口径和历史经验。
- 使用 `/auto-goo:goo-plan` 生成计划时，必须在 `.goo/plan.json` 最后保留 `归档到 Goo-wiki` 步骤，并依赖所有非归档叶子步骤；计划必须包含 `wiki_context` 和 `context_digest`，让后续执行不依赖主会话聊天记录。
- 如果当前对话已经形成方案、取舍、约束或验收标准，短内容写入 `.goo/plan.json.context_digest`；长方案、会议纪要或 prompt 草案优先写入 `Goo-wiki/{project_archive_dir}/context/`，并在 `.goo/plan.json.context_artifacts` 中引用。
- 如果 `.goo/plan.json` 已生成后又通过对话产生新方案、约束、验收标准或用户偏好，`/auto-goo:goo-start` 和 `/auto-goo:goo-continue` 默认先做 context sync：把旧 plan 复制到 `.goo/plans/history/`，短内容写入 `context_digest.post_plan_updates`，长内容写入 `context_artifacts` 指向的 Markdown；只有与原 plan 冲突、扩大范围、改变验收标准或涉及危险操作时才询问用户确认。
- 使用 `/auto-goo:goo-start` 或 `/auto-goo:goo-continue` 执行时，只能基于当前 `.goo/plan.json`、`context_artifacts` 指向的 Goo-wiki/Markdown、相关 `wiki_context`、`.goo/logs/` 和上游产物路径恢复任务；不得依赖“刚才讨论过”的隐含上下文。
- 使用 `/auto-goo:goo-start` 或 `/auto-goo:goo-continue` 执行时，所有 `research` / `exec` / `optimize` / `eval` / `review` / `archive` step 必须派发给 `.goo/plan.json` 中声明的 `subagent`；主 Agent 只负责编排、状态修复、上下文补全和产物审核，不直接代写步骤产物或代跑步骤命令。
- 如果待执行 step 缺少 `subagent`、`depends_on`、`output`、读写边界或必要上下文，先更新 `.goo/plan.json` / `context_artifacts` 后再派发，不用主会话聊天记录临时补齐。
- 使用 `/auto-goo:goo-start` 或 `/auto-goo:goo-continue` 执行后，必须归档任务目标、计划摘要、步骤证据、产物路径、验证结果、关键决策、问题处理和可复用经验。
- 任何产生可复用内容的命令最终都必须归档到 Goo-wiki 或 `.goo/obsidian/` fallback；不得只写 `.goo/*.json` 或只在聊天中展示。brainstorm 候选目标和 plan 摘要必须先给用户审阅，确认后或进入执行前再归档最终版；usage/token 降本分析、日报/周报、改进建议、benchmark 指标和执行经验按命令规则归档。
- 用户要求日报、周报、总结今天或调用 `/auto-goo:goo-daily-report` 时，必须把 Claude Code / Codex 会话沉淀到 Goo-wiki `journal/daily/`，并更新 `log.md`；同日日报已存在时只追加新增内容，不整体覆盖已有人工整理。
- Goo-wiki 可用时优先写入 `{wiki_dir}/{project_archive_dir}/` 并追加 `Goo-wiki/log.md`；不可用时写入 `{fallback_project_dir}` 作为本地 fallback。
- 归档完成前必须补齐并验收 Markdown 连接图谱：任务页链接项目入口、复用的 `wiki_context` / `context_artifacts` 和关键概念/问题/指标/历史任务页；项目 `index.md` 与 `log.md` 反向链接任务页；新增 concept/lessons/metrics 页面链接回任务页或项目入口。缺少这些链接时不得把 archive step 标记为 completed。
- 不把归档当作事后报告；归档内容要能支撑下一次任务的召回、规划和复用。
"""

content = archive_section + server_section
if not content.strip():
    sys.exit(2)

block = f"""{begin}
{content.rstrip()}
{end}
"""

if target.exists():
    text = target.read_text(encoding="utf-8")
else:
    text = "# Project Instructions\n"

if begin in text and end in text:
    prefix, rest = text.split(begin, 1)
    _, suffix = rest.split(end, 1)
    new_text = prefix.rstrip() + "\n\n" + block + suffix.lstrip("\n")
else:
    new_text = text.rstrip() + "\n\n" + block

target.write_text(new_text, encoding="utf-8")
PY
    PY_EXIT=$?
    if [[ "$PY_EXIT" -eq 0 ]]; then
      echo "Updated $PROJECT_CLAUDE_MD"
    else
      echo "CLAUDE.md not modified (no content to write)"
    fi
    set -e
  fi
elif [[ "$SCOPE" == "project" && "$SKIP_CLAUDE_MD" -eq 1 ]]; then
  echo "Skipped project CLAUDE.md update (--skip-claude-md)"
fi

echo ""
echo "Recommended SessionStart hook:"
cat <<'EOF'
{
  "hooks": {
    "SessionStart": [{
      "hooks": [
        {
          "type": "command",
          "command": "test -f \"${AUTO_GOO_WIKI_DIR:-$HOME/workspace/Goo-wiki}/CLAUDE.md\" && echo 'Goo-wiki vault ready' || echo 'Goo-wiki not found; using .goo/obsidian fallback'"
        },
        {
          "type": "command",
          "command": "cat .goo/plan.json 2>/dev/null && echo 'Unfinished AutoGoo plan found; run /auto-goo:goo-continue to resume' || true"
        }
      ]
    }]
  }
}
EOF
