# Obsidian 归档 (Goo-wiki Archiving)

AutoGoo 以 Goo-wiki 作为项目记忆层：任务开始前读取已有知识，任务结束后将新经验归档回 wiki。Recorder Subagent 负责把执行记录转化为符合 Goo-wiki 规范的 Obsidian 笔记。

## 知识闭环

AutoGoo 的 wiki 流程分成两段：

1. **执行前召回**：读取相关项目页、概念页、周报和 `log.md`，提取历史决策、已验证命令、数据路径、指标口径、失败经验和后续计划。
2. **执行后归档**：把本次任务的目标、计划、对话中固化的方案决策、步骤证据、产物、验证结果、指标、问题处理和可复用经验写回 Goo-wiki，并补齐与既有 Markdown 页面之间的 `[[Wikilink]]`，让 Obsidian 关联图谱随任务增长。

归档不是附加项，也不是孤立报告，而是为了让下一次 AutoGoo 任务能沿着项目页、概念页、问题页、周报和日志之间的链接继续推进。归档完成的判断不能只看 Markdown 文件是否存在，必须同时验收链接关系是否存在；缺少关键链接时 archive step 不得标记为 `completed`。

## 内容输出命令归档

除纯状态查看、纯初始化配置或用户明确要求不归档外，任何产生可复用内容的 AutoGoo 命令最终都必须写入 Goo-wiki，不能只保存在 `.goo/` 或聊天消息中。

`goo-brainstorm` 和 `goo-plan` 是 review-first 命令：先写本地 `.goo/brainstorm.json` / `.goo/plan.json`，向用户展示候选目标或计划摘要，允许用户选择、合并、改写、拆分或调整验收标准。用户确认前不要把草案写成 Goo-wiki/fallback 知识归档；确认后或进入执行前，再归档最终版。

必须归档的内容输出包括：
- `/auto-goo:goo-brainstorm` 经用户确认后的候选 goals、共同前置条件、推荐顺序和关键 wiki 证据。
- `/auto-goo:goo-usage-analyse` 的 usage 快照、成本归因、节省机会、候选 workflow rules 和后续动作。
- `/auto-goo:goo-daily-report` 的日报/周报。
- `/auto-goo:goo-improve` 的流程摩擦、改进建议和采纳状态。
- `/auto-goo:goo-benchmark`、`/auto-goo:goo-start`、`/auto-goo:goo-continue` 产生的指标、执行证据、优化经验和最终结论。
- `/auto-goo:goo-plan` 经用户确认后的计划摘要、关键约束和可复用规划经验；完整 thread plan 仍保留为本地状态源，`.goo/plan.json` 只是兼容入口。

归档优先写入 `<wiki_dir>/<archive.project_dir>/`，并更新项目入口或 `log.md`。Goo-wiki 不可用时写入 `.goo/obsidian/<project-slug>/` fallback。命令对应的 `.goo/*.json` 产物应包含 `archive` 字段，记录归档路径、fallback 状态和 `log.md` 是否更新。

`/auto-goo:goo-publish` 是归档之外的展示层。它无需运行 `goo-init` 或创建 `.goo/config.json`，默认从 `.goo/threads/`、`.goo/current_thread.json`、兼容 `.goo/brainstorm.json`、`.goo/plan.json`、history、当前 thread logs/artifacts/reports、`.goo/change-requests/`、`.goo/obsidian/` 和当前项目 Claude Code usage 日志生成 `.goo/site/` 多页站点。`skills/auto-goo/templates/publish/workflow-shell.html` 是唯一运行时页面外壳，`skills/auto-goo/templates/publish/workflow-theme.css` 是唯一正式视觉主题；脚本填充标题、活动导航、正文、路径和交互脚本，并复制主题到站点目录，不依赖发布后手工注入 CSS。默认生成总览、Threads、计划、活动、头脑风暴、运行状态、代理执行、产物归档和修改请求页面，关键页面标签优先使用中文。Token 格子悬浮时显示消耗明细，点击或聚焦后由下方文本型工作流活动说明所选时间段实际完成的工作；活动记录列表显示对应用户任务摘要，点击记录后展开完整用户任务原文和使用详情，但不发布 assistant 回复或完整对话正文。它默认启动 `0.0.0.0:9877` server、尝试弹出浏览器，同时打印 `127.0.0.1` 和本机 IP 访问地址；端口占用时自动尝试后续端口。server 默认只读已生成 HTML，打开页面时不重新扫描 `.goo/`；需要每次刷新实时重建时再加 `--live`。HTML 发布不替代 Goo-wiki/fallback 归档，不直接修改业务文件、plan 或 brainstorm；Web 表单只新增 `.goo/change-requests/*.json`，后续由主 Agent 纳入 thread plan 并审计。

## 目录规则

不设独立 `auto-goo/` 目录，按任务所属领域放入对应目录，通过 `auto-goo` tag 区分来源。

**输出目录优先级**：
1. `<wiki_dir>/<archive.project_dir>/`（Goo-wiki vault 存在时，通常是 `Goo-wiki/wiki/projects/<project-slug>/`）
2. `<archive.fallback_project_dir>/`（fallback，仅本地归档，通常是 `.goo/obsidian/<project-slug>/`）

**路径检测**：按 `AUTO_GOO_WIKI_DIR` → `.goo/config.json.wiki_dir` → `~/.auto-goo/config.json.wiki_dir` → `~/workspace/Goo-wiki` 解析 wiki 目录，并检查 `<wiki_dir>/CLAUDE.md` 是否存在（详见 `setup.md`）。项目归档根目录由 `.goo/config.json.archive.project_dir` 指定；不存在则降级为 fallback。

## Goo-wiki 约定

- 按项目放入 `archive.project_dir` 指向的项目根目录下，默认是 `wiki/projects/<project-slug>/`
- 指标类知识放入 `wiki/concepts/<domain>/`
- 周期性复盘和项目状态参考 `journal/weekly/`，但任务产物不直接写入周报

### 项目子目录约定

项目入口文件 `<project-slug>.md` 位于项目根目录。按内容性质分级存放：

| 子目录 | 内容 | 更新触发 | 说明 |
|--------|------|----------|------|
| `tasks/` | 任务总览、步骤笔记、迭代记录 | 每次 AutoGoo 任务 | 主体内容，按任务名聚合 |
| `lessons/` | 跨任务的可复用经验 | 有复用价值时 | 从任务中独立沉淀的高价值经验 |
| `brainstorm/` | 候选目标、选择依据 | brainstorm 完成后 | review-first 产物 |
| `plans/` | DAG、上下文摘要、计划取舍 | plan 确认后 | plan 阶段产物 |
| `reports/` | 一次性分析报告 | 报告产出后 | usage 分析、benchmark、降本报告等 |
| `code-graph/` | 代码模块关系索引 | 代码架构变更时 | 模型召回用的代码链接关系，非人类文档 |

子目录按需创建，非必须全部存在。项目文件数少于 20 时可平铺不建子目录，由 Recorder 根据项目规模自行判断。
- YAML frontmatter 使用标准格式（type, title, status, tags, aliases, date）
- 所有笔记追加 `tags: [auto-goo, <domain>]`（至少 2 个 tag，auto-goo 标记来源）
- 笔记的文件名和 tag 从用户输入的 task 语义推导，而非从执行的具体操作命名
- 文件名使用小写连字符（`lowercase-with-hyphens.md`）
- 默认使用中文
- 每次任务完成后向 `Goo-wiki/log.md` 追加活动日志
- 如果项目是 Git repo，必须在项目页或任务总览笔记中记录 git remote 地址；优先读取 `.goo/config.json.archive.git_remote_url`，缺失时用 `git remote get-url origin` 或第一个 remote 兜底
- 不写入 `raw/` 目录（原始来源不可变）
- 成熟度 status: `seed` → `developing` → `stable`
- 使用 `[[Wikilink]]` 建立双向可发现的链接；任何新任务页都不能成为孤立页面

## 关联图谱规则

Recorder 写入或更新 Markdown 时，必须同时维护页面之间的语义链接，目标是让 Obsidian graph/backlinks 能回答“这个任务属于哪个项目、复用了哪些知识、产出了哪些经验、影响哪些后续问题”。

为减少 token 消耗，Recorder 优先调用通用脚本生成紧凑链接上下文，而不是直接读取大量 Markdown：

```bash
auto_goo_root="$(
  python3 - <<'PY' 2>/dev/null || true
import json
from pathlib import Path

home = Path.home()
matches = []

def usable(path):
    return path.exists() and not (path / ".orphaned_at").exists()

registry = home / ".claude/plugins/installed_plugins.json"
if registry.exists():
    data = json.loads(registry.read_text(encoding="utf-8"))
    for key, entries in data.get("plugins", {}).items():
        if key.split("@", 1)[0] != "auto-goo":
            continue
        for entry in entries:
            path = Path(entry.get("installPath", "")).expanduser()
            if usable(path):
                matches.append((entry.get("lastUpdated", ""), str(path)))

if not matches:
    settings = home / ".claude/settings.json"
    if settings.exists():
        data = json.loads(settings.read_text(encoding="utf-8"))
        enabled = data.get("enabledPlugins", {})
        marketplaces = data.get("extraKnownMarketplaces", {})
        for key, is_enabled in enabled.items():
            if not is_enabled or "@" not in key:
                continue
            plugin, marketplace = key.split("@", 1)
            if plugin != "auto-goo":
                continue
            source = marketplaces.get(marketplace, {}).get("source", {})
            if source.get("source") != "directory":
                continue
            path_text = source.get("path")
            if not path_text:
                continue
            path = Path(path_text).expanduser()
            if usable(path):
                matches.append(("settings:" + marketplace, str(path)))

if matches:
    print(sorted(matches)[-1][1])
PY
)"
if [ -z "$auto_goo_root" ] || [ ! -f "$auto_goo_root/skills/auto-goo/scripts/wiki-graph-assist.py" ]; then
  echo "AutoGoo root not configured; install auto-goo or enable a local directory marketplace in ~/.claude/settings.json" >&2
  exit 127
fi
python3 "$auto_goo_root/skills/auto-goo/scripts/wiki-graph-assist.py" \
  --wiki-dir "$WIKI_DIR" \
  --project-slug "<project-slug>" \
  --query "<task title and key terms>" \
  --task-page "wiki/projects/<project-slug>/<task>.md" \
  --max-pages 12
```

脚本只输出相关页面、候选 `[[Wikilink]]`、少量标题和片段。任务页写好后，可用 `--update-index --append-log` 机械维护项目入口和 `log.md` 链接。

**归档前检查**：
- 在 `wiki.search_paths` 范围内检索同项目、同领域、同数据集、同配置、同命令、同错误信息和同指标口径的既有页面。
- 优先识别项目入口 `wiki/projects/<project-slug>/<project-slug>.md`、相关任务页、概念页、问题页、周报、`log.md` 和 `context_artifacts`。
- 如果已存在同主题页面，优先更新或链接到既有页面；只有任务语义确实独立时才创建新页面。

**归档时必须建立的链接**：
- 新任务页链接回项目入口：`[[wiki/projects/<project-slug>/<project-slug>|项目名]]`。
- 项目入口 `<project-slug>.md` 按小节维护与子目录的双向链接：
  - `## 最近任务` → 链接到 `tasks/` 下的任务页（最新任务置顶）
  - `## 可复用经验` → 链接到 `lessons/` 下的经验页或任务页中的经验小节
  - `## 代码结构` → 链接到 `code-graph/` 下的模块索引页
  - 如有 `brainstorm/`、`plans/`、`reports/` 产物，在项目入口对应小节或任务页中链接
- 任务页链接到本次复用的 `wiki_context`、`context_artifacts`、关键概念页、问题页、指标页、数据/配置说明页和必要周报。
- 可复用经验应写入任务页的”可复用经验”小节，必要时链接到独立 lessons 页面；lessons 页面也应链接回代表性任务页和项目入口。
- `log.md` 的活动日志必须链接到任务页；如果任务改变项目状态，项目入口也要能从正文链接到这条任务记录。

**归档完成验收**：
- 任务页存在，且至少链接到项目入口；有 `wiki_context` / `context_artifacts` 时必须链接到被复用的来源页或上下文页。
- 项目入口 `<project-slug>.md` 存在，且 `## 最近任务` 中包含本次任务页链接。
- `log.md` 有本次活动记录，并链接到任务页。
- 如新增 lessons/metrics 页面，任务页必须链接过去；新增页面必须链接回任务页和项目入口。
- 如果没有可链接的既有知识页，任务页必须显式记录 `wiki_context.found=false` 或”未找到可复用页面”，但仍要链接项目入口和 `log.md`。

**链接质量约束**：
- 不为了图谱密度链接所有出现过的词，只链接能帮助后续召回、规划、复盘或溯源的页面。
- 不手工维护无限增长的反链清单；反链交给 Obsidian。页面正文只保留少量高价值“相关链接”。
- 纯路径、文件名、命令和错误文本如果对应已有说明页，应同时给出 `[[...]]` 链接；没有对应页面时保留代码格式路径即可。
- fallback `.goo/obsidian/` 归档也按同样链接结构写 Markdown，方便未来迁移回 Goo-wiki。

## 笔记类型

| 笔记类型 | 路径 | Tag | 频率 |
|---------|------|-----|------|
| 任务总览 | `wiki/projects/<slug>/tasks/<task>.md` | `[auto-goo, <domain>]` | 每次任务 |
| 步骤笔记 | `wiki/projects/<slug>/tasks/<task>-step-<id>.md` | `[auto-goo, <domain>, step]` | 每步一次 |
| 迭代记录 | `wiki/projects/<slug>/tasks/<task>-round-<n>.md` | `[auto-goo, <domain>, optimization]` | 每轮优化 |
| 指标档案 | `wiki/concepts/<domain>/<task>-metrics.md` | `[auto-goo, metrics]` | 追加累积 |
| 经验沉淀 | `wiki/projects/<slug>/lessons/<task>-lessons.md` 或任务页小节 | `[auto-goo, lessons]` | 有复用价值时 |
| 活动日志 | `log.md` | `## [YYYY-MM-DD] auto-goo \| <task>` | 每次任务 |
| 代码关系索引 | `wiki/projects/<slug>/code-graph/<module>.md` | `[auto-goo, code-graph]` | 代码架构变更时 |

## Recorder Prompt 模板

当步骤完成或任务结束时，按以下模式派发 Recorder：

```
你是一个 AutoGoo Obsidian Recorder Subagent。

## 任务
将以下执行记录格式化为符合 Goo-wiki 规范的 Obsidian 笔记。

## 输入数据
{step_log_content}
{wiki_context}

## Goo-wiki 规范（必须遵守）
1. 不设独立 auto-goo 目录，按项目领域和内容性质分级存放：
   - 任务/步骤/迭代 → wiki/projects/<project-slug>/tasks/
   - 经验沉淀 → wiki/projects/<project-slug>/lessons/
   - brainstorm 产物 → wiki/projects/<project-slug>/brainstorm/
   - plan 产物 → wiki/projects/<project-slug>/plans/
   - 分析报告 → wiki/projects/<project-slug>/reports/
   - 代码关系索引 → wiki/projects/<project-slug>/code-graph/
   - 指标 → wiki/concepts/<domain>/
   - 项目入口 → wiki/projects/<project-slug>/<project-slug>.md（根目录，含项目说明）
2. 所有笔记 tags 必须包含 auto-goo + 至少一个领域 tag
3. Tag 和文件名从用户输入的**任务目的**推导，不从实现命名
4. YAML frontmatter 格式：type, title, domain, status, tags, date, aliases
5. type 取值：concept（步骤/指标）、project（任务总览）
6. status 取值：seed / developing / stable
7. 文件名使用小写连字符
8. 默认使用中文
9. 用 [[wiki/projects/<project-slug>/tasks/xxx|显示名]] 格式的 wikilink，并避免产生孤立页面
10. 数字和指标用表格呈现
11. 记录本次任务复用了哪些 wiki 经验，以及新增了哪些可复用经验
12. 记录 `context_digest` 中的关键方案、取舍、用户约束和验收标准；如果有 `context_artifacts`，用路径或 wikilink 引用
13. 如果项目是 Git repo，在项目页或任务总览笔记的 `Project Metadata` / `项目元信息` 小节写入 git remote 地址；优先使用 `.goo/config.json.archive.git_remote_url`
14. 任务完成后向 Goo-wiki/log.md 追加一条活动日志，日志必须链接到任务页
15. 不要写入 raw/ 目录
16. 输出目录优先级：Goo-wiki/wiki/ > .goo/obsidian/（fallback）
17. 子步骤内容内联在主任务笔记中，用 --- 分隔，不拆为独立文件
18. 写入前检索并链接相关项目页、概念页、问题页、周报、context_artifacts 和历史任务页
19. 写入后更新项目入口 `<project-slug>.md`，维护以下小节的双向链接：`## 最近任务`（链接到 tasks/ 下最新任务）、`## 可复用经验`（链接到 lessons/ 或任务页经验小节）、`## 代码结构`（链接到 code-graph/）；项目入口必须包含项目说明（背景、目标、核心功能）
20. 如新增 concept/lessons/metrics 页面，必须从任务页链接过去，并在新页面链接回 1-3 个代表性任务页或项目入口
21. 完成前必须做链接验收：任务页、项目入口、log.md、复用知识页/上下文页、新增经验页之间的必要 `[[Wikilink]]` 均存在；缺失时先补链，不得只因为文件已写入就宣布归档完成
```

## log.md 追加格式

```markdown
## [{{YYYY-MM-DD}}] auto-goo | {{task_name}}

执行 {{step_count}} 步，耗时 {{total_duration}}。含优化迭代 {{round_count}} 轮。
项目页：[[wiki/projects/<project-slug>/<task-name>|<task_name>]]
Git: {{git_remote_url_or_empty}}
复用经验：{{reused_knowledge_count}} 条；新增经验：{{new_lessons_count}} 条。
```

## 命名规范

- 文件名/标签从任务目的推导：CLAUDE.md 优化 → `claude-md-优化` / `[auto-goo, claude-md-optimization]`
- 文件名小写连字符，子步骤内联在主笔记中用 `---` 分隔
- 同一领域任务使用相同 slug，创建新目录前检查是否已有相关领域目录
- fallback（Goo-wiki 不存在时）：`.goo/obsidian/<slug>/`，跳过 log.md
