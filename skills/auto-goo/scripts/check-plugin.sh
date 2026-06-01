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

# ── 4. 命令文件 ──
echo ""
echo "── 4. 命令文件 ──"

CMDS=("goo-init" "goo-brainstorm" "goo-plan" "goo-start" "goo-research" "goo-benchmark" "goo-continue" "goo-improve" "goo-status" "goo-daily-report" "goo-usage" "goo-usage-analyse")
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

SCRIPTS=("goo-init.sh" "init-plan.sh" "goo-status.py" "update-step.py" "wiki-graph-assist.py" "daily-report-sessions.py" "goo-usage.py" "goo-ssh.sh" "check-plugin.sh")
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

TEMPLATES=("config.example.json" "user-config.example.json")
for tmpl in "${TEMPLATES[@]}"; do
  f="$ROOT/skills/auto-goo/templates/$tmpl"
  if [[ -f "$f" ]]; then
    pass "templates/$tmpl"
    if command -v python3 &>/dev/null; then
      python3 -c "import json; json.load(open('$f'))" 2>/dev/null \
        && pass "  $tmpl 格式正确" \
        || fail "  $tmpl 格式错误"
    fi
  else
    fail "templates/$tmpl 缺失"
  fi
done

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
