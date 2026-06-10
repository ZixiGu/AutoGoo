#!/usr/bin/env bash
# AutoGoo 插件自检脚本
# 验证插件结构完整性，安装后快速确认所有组件就绪
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
ERRORS=0
WARNINGS=0

info()  { echo -e "  \033[1;34m•\033[0m $1"; }
pass()  { echo -e "  \033[1;32m✓\033[0m $1"; }
warn()  { echo -e "  \033[1;33m⚠\033[0m $1"; WARNINGS=$((WARNINGS + 1)); }
fail()  { echo -e "  \033[1;31m✗\033[0m $1"; ERRORS=$((ERRORS + 1)); }

echo ""
echo "============================================"
echo "  AutoGoo 插件自检"
echo "============================================"
echo ""

# ── 1. Plugin 元数据 ──
echo "── 1. Plugin 元数据 ──"

if [[ -f "$ROOT/.claude-plugin/plugin.json" ]]; then
  pass ".claude-plugin/plugin.json 存在"
  if command -v python3 &>/dev/null; then
    python3 -c "import json; json.load(open('$ROOT/.claude-plugin/plugin.json'))" 2>/dev/null \
      && pass "  plugin.json 格式正确" \
      || fail "  plugin.json 格式错误"
  fi
else
  fail ".claude-plugin/plugin.json 缺失"
fi

# ── 2. SKILL ──
echo ""
echo "── 2. SKILL 定义 ──"

SKILLS=("auto-goo")
for skill_dir in "${SKILLS[@]}"; do
  SKILL="$ROOT/skills/$skill_dir/SKILL.md"
  if [[ -f "$SKILL" ]]; then
    pass "skills/$skill_dir/SKILL.md 存在"
    if head -1 "$SKILL" | grep -q '^---$'; then
      pass "  YAML frontmatter 起始正确"
    else
      fail "  YAML frontmatter 起始缺失"
    fi
    if command -v python3 &>/dev/null; then
      set +e
      python3 - "$SKILL" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
if not match:
    print("missing-frontmatter")
    raise SystemExit(1)
fields = {}
for line in match.group(1).splitlines():
    if ":" not in line:
        continue
    key, value = line.split(":", 1)
    fields[key.strip()] = value.strip().strip('"').strip("'")
missing = [key for key in ("name", "description") if not fields.get(key)]
if missing:
    print("missing:" + ",".join(missing))
    raise SystemExit(2)
if len(fields["description"]) > 1024:
    raise SystemExit(3)
PY
      rc=$?
      set -e
      case "$rc" in
        0) pass "  frontmatter name/description 格式正确" ;;
        1) fail "  frontmatter 解析失败" ;;
        2) fail "  frontmatter 缺少 name 或 description" ;;
        3) fail "  description 超过 1024 字符，会浪费启动上下文" ;;
        *) fail "  frontmatter 校验异常" ;;
      esac
    fi
  else
    fail "skills/$skill_dir/SKILL.md 缺失"
  fi
done

# ── 3. Reference 文件 ──
echo ""
echo "── 3. Reference 文件 ──"

REFS=(
  "execution-engine.md"
  "heartbeat.md"
  "interaction-templates.md"
  "obsidian-archive.md"
  "optimization-loop.md"
  "python-standards.md"
  "self-improvement.md"
  "setup.md"
  "skill-design.md"
  "task-parsing.md"
)

for ref in "${REFS[@]}"; do
  f="$ROOT/skills/auto-goo/references/$ref"
  if [[ -f "$f" ]]; then
    pass "references/$ref"
  else
    fail "references/$ref 缺失"
  fi
done

INTERACTION_TEMPLATES="$ROOT/skills/auto-goo/references/interaction-templates.md"
if [[ -f "$INTERACTION_TEMPLATES" ]] && command -v python3 &>/dev/null; then
  set +e
  python3 - "$INTERACTION_TEMPLATES" <<'PY'
import json
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
blocks = re.findall(r"```json\n(.*?)\n```", text, re.S)
if not blocks:
    print("no-json-blocks")
    raise SystemExit(1)

seen = set()
required = {
    "config_scope",
    "wiki_dir",
    "update_claude_md",
    "configure_servers",
    "server_type",
    "server_ip",
    "server_port",
    "server_user",
    "server_purpose",
    "server_password",
    "add_another_server",
    "git_init_project",
    "brainstorm_review",
    "existing_brainstorm_goal",
    "thread_action",
    "thread_select",
    "existing_plan_action",
    "plan_review",
    "start_plan_review",
    "failed_step_action",
    "research_followup",
    "usage_view",
    "publish_public_confirm",
    "improve_confirm",
    "permission_block_action",
}

for block in blocks:
    obj = json.loads(block)
    for key in ("header", "id", "question", "options"):
        if not obj.get(key):
            print(f"missing-{key}")
            raise SystemExit(2)
    if obj["id"] in seen:
        print(f"duplicate-id:{obj['id']}")
        raise SystemExit(3)
    seen.add(obj["id"])
    options = obj["options"]
    if not isinstance(options, list) or len(options) < 2:
        print(f"bad-options:{obj['id']}")
        raise SystemExit(4)
    if "(Recommended)" not in options[0].get("label", ""):
        print(f"missing-recommended:{obj['id']}")
        raise SystemExit(5)
    for opt in options:
        if not opt.get("label") or not opt.get("description"):
            print(f"bad-option-field:{obj['id']}")
            raise SystemExit(6)

missing = sorted(required - seen)
if missing:
    print("missing-required:" + ",".join(missing))
    raise SystemExit(7)
PY
  rc=$?
  set -e
  case "$rc" in
    0) pass "  interaction-templates.md JSON 模板正确" ;;
    1) fail "  interaction-templates.md 缺少 JSON 模板" ;;
    2) fail "  interaction-templates.md 模板缺少必填字段" ;;
    3) fail "  interaction-templates.md 模板 id 重复" ;;
    4) fail "  interaction-templates.md 模板选项少于 2 个" ;;
    5) fail "  interaction-templates.md 模板第一项缺少 Recommended" ;;
    6) fail "  interaction-templates.md 模板选项缺少 label/description" ;;
    7) fail "  interaction-templates.md 缺少必需模板 id" ;;
    *) fail "  interaction-templates.md JSON 校验异常" ;;
  esac
fi

# ── 4. 命令文件 ──
echo ""
echo "── 4. 命令文件 ──"

CMDS=("goo-init" "goo-brainstorm" "goo-plan" "goo-start" "goo-research" "goo-benchmark" "goo-continue" "goo-improve" "goo-status" "goo-daily-report" "goo-usage" "goo-usage-analyse" "goo-publish")
for cmd in "${CMDS[@]}"; do
  f="$ROOT/commands/$cmd.md"
  if [[ -f "$f" ]]; then
    pass "commands/$cmd.md"
    if grep -q "^name: auto-goo:$cmd$" "$f"; then
      pass "  /auto-goo:$cmd 注册名正确"
    else
      fail "  commands/$cmd.md 注册名应为 name: auto-goo:$cmd"
    fi
  else
    fail "commands/$cmd.md 缺失"
  fi
done

# ── 5. Agent 文件 ──
echo ""
echo "── 5. Agent 文件 ──"

ROLE_AGENTS=("researcher" "implementer" "optimizer" "evaluator" "reviewer" "auditor" "recorder")
TASK_AGENTS=(
  "tasks/research/codebase-scout"
  "tasks/research/document-analyst"
  "tasks/research/domain-researcher"
  "tasks/research/requirement-analyst"
  "tasks/implementation/feature-builder"
  "tasks/implementation/bug-fixer"
  "tasks/implementation/refactorer"
  "tasks/implementation/script-writer"
  "tasks/implementation/doc-editor"
  "tasks/optimization/profiler"
  "tasks/optimization/performance-optimizer"
  "tasks/optimization/token-cost-optimizer"
  "tasks/optimization/workflow-optimizer"
  "tasks/evaluation/test-runner"
  "tasks/evaluation/benchmark-runner"
  "tasks/evaluation/data-validator"
  "tasks/evaluation/acceptance-checker"
  "tasks/review/code-reviewer"
  "tasks/review/api-contract-reviewer"
  "tasks/review/doc-reviewer"
  "tasks/audit/security-checker"
  "tasks/audit/compliance-auditor"
  "tasks/audit/evidence-auditor"
  "tasks/audit/traceability-auditor"
  "tasks/audit/risk-auditor"
  "tasks/recording/obsidian-recorder"
  "tasks/recording/wiki-curator"
  "tasks/recording/execution-summarizer"
  "tasks/recording/lesson-extractor"
)
for agent in "${ROLE_AGENTS[@]}"; do
  f="$ROOT/agents/roles/$agent.md"
  if [[ -f "$f" ]]; then
    pass "agents/roles/$agent.md"
    if head -1 "$f" | grep -q '^---$\|^#'; then
      pass "  frontmatter/heading 起始正确"
    else
      warn "  agents/roles/$agent.md 缺少 frontmatter 或 heading"
    fi
  else
    fail "agents/roles/$agent.md 缺失"
  fi
done

for agent in "${TASK_AGENTS[@]}"; do
  f="$ROOT/agents/$agent.md"
  if [[ -f "$f" ]]; then
    pass "agents/$agent.md"
    if head -1 "$f" | grep -q '^---$\|^#'; then
      pass "  frontmatter/heading 起始正确"
    else
      warn "  agents/$agent.md 缺少 frontmatter 或 heading"
    fi
  else
    fail "agents/$agent.md 缺失"
  fi
done

# ── 6. 脚本文件 ──
echo ""
echo "── 6. 脚本文件 ──"

SCRIPTS=("goo-init.sh" "init-plan.sh" "goo-status.py" "update-step.py" "thread-state.py" "thread-locks.py" "wiki-graph-assist.py" "daily-report-sessions.py" "goo-usage.py" "goo-publish.py" "goo-ssh.sh" "check-plugin.sh")
for s in "${SCRIPTS[@]}"; do
  f="$ROOT/skills/auto-goo/scripts/$s"
  if [[ -f "$f" ]]; then
    pass "scripts/$s"
    if [[ -x "$f" ]]; then
      pass "  $s 可执行"
    else
      warn "  $s 不可执行 —— 请 chmod +x"
    fi
  else
    fail "scripts/$s 缺失"
  fi
done

if command -v python3 &>/dev/null; then
  for py in "$ROOT"/skills/auto-goo/scripts/*.py; do
    [[ -f "$py" ]] || continue
    if PYTHONPYCACHEPREFIX="${TMPDIR:-/tmp}/autogoo-check-pycache" python3 -m py_compile "$py" 2>/dev/null; then
      pass "  $(basename "$py") 语法正确"
    else
      fail "  $(basename "$py") 语法错误"
    fi
  done
fi

for sh in "$ROOT"/skills/auto-goo/scripts/*.sh; do
  [[ -f "$sh" ]] || continue
  if bash -n "$sh" 2>/dev/null; then
    pass "  $(basename "$sh") 语法正确"
  else
    fail "  $(basename "$sh") 语法错误"
  fi
done

# ── 6b. 模板文件 ──
echo ""
echo "── 6b. 模板文件 ──"

TEMPLATES=("config.example.json" "user-config.example.json" "publish/workflow-shell.html" "publish/workflow-theme.css")
for tmpl in "${TEMPLATES[@]}"; do
  f="$ROOT/skills/auto-goo/templates/$tmpl"
  if [[ -f "$f" ]]; then
    pass "templates/$tmpl"
    if [[ "$tmpl" == *.json ]] && command -v python3 &>/dev/null; then
      python3 -c "import json; json.load(open('$f'))" 2>/dev/null \
        && pass "  $tmpl 格式正确" \
        || fail "  $tmpl 格式错误"
    elif [[ "$tmpl" == *.html ]]; then
      grep -q '{{DYNAMIC_CSS}}' "$f" \
        && grep -q '{{PAGE_BODY}}' "$f" \
        && grep -q '{{NAV_INDEX_CLASS}}' "$f" \
        && grep -q '{{PAGE_TITLE}}' "$f" \
        && pass "  $tmpl 占位符正确" \
        || fail "  $tmpl 缺少必要占位符"
    fi
  else
    fail "templates/$tmpl 缺失"
  fi
done

PUBLISH_SHELL="$ROOT/skills/auto-goo/templates/publish/workflow-shell.html"
PUBLISH_THEME="$ROOT/skills/auto-goo/templates/publish/workflow-theme.css"
if [[ -f "$PUBLISH_SHELL" ]] && grep -q 'workflow-theme.css' "$PUBLISH_SHELL"; then
  pass "  workflow-shell.html 引用正式发布主题"
else
  fail "  workflow-shell.html 未引用 workflow-theme.css"
fi
if [[ -f "$PUBLISH_THEME" ]] \
  && grep -q 'body\[data-page="brainstorm"\]' "$PUBLISH_THEME" \
  && grep -q 'summary-card:nth-child' "$PUBLISH_THEME" \
  && grep -q 'html\[data-theme="dark"\]' "$PUBLISH_THEME"; then
  pass "  workflow-theme.css 包含页面语义色、指标卡配色和暗色主题"
else
  fail "  workflow-theme.css 缺少正式主题关键样式"
fi
if ! grep -q 'split_pages' "$ROOT/skills/auto-goo/scripts/goo-publish.py"; then
  pass "  goo-publish.py 固定多页输出，不保留 split_pages 旧分支"
else
  fail "  goo-publish.py 仍残留 split_pages 旧分支"
fi

# ── 6c. HTML 发布 smoke test ──
echo ""
echo "── 6c. HTML 发布 smoke test ──"

if command -v python3 &>/dev/null; then
  PUBLISH_SMOKE_DIR="${TMPDIR:-/tmp}/autogoo-check-publish-$$"
  mkdir -p "$PUBLISH_SMOKE_DIR/project/.goo/artifacts" "$PUBLISH_SMOKE_DIR/project/.goo/logs"
  python3 - "$PUBLISH_SMOKE_DIR/project" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
goo = root / ".goo"
(goo / "plan.json").write_text(json.dumps({
    "status": "pending",
    "steps": [{
        "id": 1,
        "name": "示例步骤",
        "status": "completed",
        "progress": 100,
        "subagent": "implementer",
        "task_agent": "feature-builder",
        "tier": 1,
        "depends_on": [],
        "output": ".goo/artifacts/out.txt",
    }],
    "goals": [{"id": "g1", "name": "示例目标", "status": "completed"}],
}, ensure_ascii=False) + "\n", encoding="utf-8")
(goo / "brainstorm.json").write_text(json.dumps({
    "candidate_goals": [{
        "id": "cg1",
        "title": "示例候选",
        "priority": "high",
        "why": "用于发布 smoke test",
        "expected_output": "HTML",
    }],
}, ensure_ascii=False) + "\n", encoding="utf-8")
(goo / "artifacts" / "out.txt").write_text("artifact\n", encoding="utf-8")
PY
  if python3 "$ROOT/skills/auto-goo/scripts/goo-publish.py" \
      --root "$PUBLISH_SMOKE_DIR/project" \
      --output "$PUBLISH_SMOKE_DIR/project/.goo/site/index.html" >/dev/null 2>&1; then
    missing_pages=0
    for page in index.html threads.html plan.html activity.html brainstorm.html status.html agents.html artifacts.html requests.html workflow-theme.css; do
      if [[ ! -f "$PUBLISH_SMOKE_DIR/project/.goo/site/$page" ]]; then
        missing_pages=$((missing_pages + 1))
      fi
    done
    if [[ "$missing_pages" -eq 0 ]]; then
      pass "  goo-publish.py 可生成完整多页站点"
    else
      fail "  goo-publish.py 缺少 $missing_pages 个预期页面"
    fi
  else
    fail "  goo-publish.py smoke test 失败"
  fi
fi

# ── 6d. 远程服务器 helper smoke test ──
echo ""
echo "── 6d. 远程服务器 helper ──"

if command -v python3 &>/dev/null; then
  REMOTE_SMOKE_DIR="${TMPDIR:-/tmp}/autogoo-check-remote-$$"
  mkdir -p "$REMOTE_SMOKE_DIR/project/.goo"
  python3 - "$REMOTE_SMOKE_DIR/project/.goo/config.json" "$REMOTE_SMOKE_DIR/project/.goo/secrets.json" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
secrets_path = Path(sys.argv[2])
config_path.write_text(json.dumps({
    "servers": [{
        "ip": "10.0.0.8",
        "user": "ubuntu",
        "port": 22,
        "type": "gpu",
        "purpose": "smoke",
        "secrets_file": ".goo/secrets.json",
    }]
}, ensure_ascii=False) + "\n", encoding="utf-8")
secrets_path.write_text(json.dumps([{
    "ip": "10.0.0.8",
    "user": "ubuntu",
    "password": "",
}], ensure_ascii=False) + "\n", encoding="utf-8")
PY
  if bash "$ROOT/skills/auto-goo/scripts/goo-ssh.sh" \
      --config "$REMOTE_SMOKE_DIR/project/.goo/config.json" \
      --server ubuntu@10.0.0.8:22 \
      --dry-run -- nvidia-smi 2>/dev/null \
      | grep -q 'plain ssh (key/manual auth; no password loaded)'; then
    pass "  goo-ssh.sh 支持无密码 dry-run / SSH key 模式"
  else
    fail "  goo-ssh.sh 无密码 dry-run 失败"
  fi

  python3 - "$REMOTE_SMOKE_DIR/project/.goo/secrets.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
data[0]["password"] = "smoke-password"
path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
PY
  if bash "$ROOT/skills/auto-goo/scripts/goo-ssh.sh" \
      --config "$REMOTE_SMOKE_DIR/project/.goo/config.json" \
      --server 0 \
      --dry-run -- hostname 2>/dev/null \
      | grep -q 'password via sshpass'; then
    pass "  goo-ssh.sh 支持密码 dry-run / sshpass 模式"
  else
    fail "  goo-ssh.sh 密码 dry-run 失败"
  fi
fi

# ── 7. 示例文件 ──
echo ""
echo "── 7. 示例文件 ──"

EXAMPLES=("csv-analysis-workflow" "optimization-workflow" "multi-step-orchestration")
for ex in "${EXAMPLES[@]}"; do
  f="$ROOT/skills/auto-goo/examples/$ex.md"
  if [[ -f "$f" ]]; then
    pass "examples/$ex.md"
  else
    warn "examples/$ex.md 缺失（可选）"
  fi
done

# ── 8. 配置文件 ──
echo ""
echo "── 8. 配置文件 ──"

if [[ -f "$ROOT/.claude/settings.json" ]]; then
  pass ".claude/settings.json"
else
  fail ".claude/settings.json 缺失"
fi

if [[ -f "$ROOT/.gitignore" ]]; then
  pass ".gitignore"
else
  warn ".gitignore 缺失"
fi

if [[ -f "$ROOT/README.md" ]]; then
  pass "README.md"
else
  warn "README.md 缺失"
fi

# ── 结果汇总 ──
echo ""
echo "============================================"
if [[ $ERRORS -eq 0 && $WARNINGS -eq 0 ]]; then
  echo -e "  \033[1;32m全部通过 ✓\033[0m"
elif [[ $ERRORS -eq 0 ]]; then
  echo -e "  \033[1;33m通过（$WARNINGS 个警告）\033[0m"
else
  echo -e "  \033[1;31m$ERRORS 个错误，$WARNINGS 个警告\033[0m"
fi
echo "============================================"
echo ""

exit $ERRORS
