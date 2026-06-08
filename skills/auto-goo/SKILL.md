---
name: goo-workflow
description: "Use when the user says '/auto-goo:goo-init', '/auto-goo:goo-brainstorm', '/auto-goo:goo-plan', '/auto-goo:goo-start', '/auto-goo:goo-research', '/auto-goo:goo-daily-report', '/auto-goo:goo-usage', '/auto-goo:goo-usage-analyse', '/auto-goo:goo-publish', 'brainstorm', '找目标', '开始任务', 'run:', '读论文', '论文', 'paper', '日报', '周报', 'usage', 'token统计', 'token降本', '发布HTML', '自改进', or gives a goal-clear multi-step task that can be decomposed into sub-tasks. Runs Goo workflow: config init, wiki-based brainstorm, wiki recall, DAG planning, subagent execution, research material archiving, status, HTML publishing, optimization, Goo-wiki archiving, usage monitor, usage cost analysis, daily reports, and plugin self-improvement. Requires Read, Write, Edit, Bash, WebSearch, Agent, AskUserQuestion tools."
version: 0.3.3
tools: [Read, Write, Edit, Bash, WebSearch, Agent, AskUserQuestion]
---

# AutoGoo 自动化工作流

收到可分解的多步任务后，按以下六个阶段执行。单步任务或纯问答不需启动此流程，直接执行即可。

**兼容性**：AutoGoo 完全支持非 Git 项目。Git 相关功能（remote 地址记录等）仅在项目是 Git repo 时启用，非 Git 项目不会收到任何 Git 相关错误。

**上下文预算**：`SKILL.md` 只保留触发条件、阶段入口和关键铁律。长规则、schema、prompt 变体和检查表放入 `references/`；重复机械操作优先脚本化，并让脚本输出紧凑 packet，避免主会话读取大段 Markdown。完整设计约束见 `references/skill-design.md`。

命令模式：
- `/auto-goo:goo-init --user`：初始化用户级 `~/.auto-goo/config.json`，作为所有项目的默认配置。
- `/auto-goo:goo-init --project`：初始化当前项目 `.goo/config.json`，覆盖用户级默认配置。
- `/auto-goo:goo-brainstorm <方向/项目>`：目标不明确时，基于 Goo-wiki 和当前上下文生成候选 goals，写入 `.goo/brainstorm.json` 后等待用户选择。
- `/auto-goo:goo-plan <任务>`：只执行 Phase 0-1，写入 `.goo/plan.json` 后停止，等待用户确认。
- `/auto-goo:goo-start <任务>`：执行完整流程，必要时可先生成 plan 再继续执行。
- `/auto-goo:goo-research paper <论文/DOI/arXiv/URL/PDF>`：研究资料归档入口；`paper` 子命令用于论文深读、代码/数据集搜索、下载检查和 Goo-wiki 归档。
- `/auto-goo:goo-daily-report [日期|范围]`：扫描 Claude Code / Codex 会话，生成 Goo-wiki 日报或周报素材。
- `/auto-goo:goo-usage [参数]`：扫描 Claude Code usage 日志，参考 Claude-Code-Usage-Monitor 的终端界面风格渲染今天总 token、项目分布、模型分布和可选 cost 面板。
- `/auto-goo:goo-usage-analyse [项目|范围]`：结合 usage 热点和 Goo-wiki 项目知识，归因 token 开销并生成可落地节省方案。
- `/auto-goo:goo-publish`：无需 config，把 `.goo/` 工作流状态发布成静态多页 HTML，包含活动热力图、头脑风暴、计划、任务流程图、DAG、运行状态和产物索引。

**内容输出归档铁律**：除纯状态查看、纯初始化配置或用户明确要求不归档外，任何产生可复用内容的命令最终都必须归档到 Goo-wiki。包括 `/auto-goo:goo-brainstorm` 的候选 goals、`/auto-goo:goo-research paper` 的论文资料包和深度笔记、`/auto-goo:goo-usage-analyse` 的降本报告、`/auto-goo:goo-daily-report` 的日报/周报、`/auto-goo:goo-improve` 的改进建议、benchmark/plan/start/continue 的计划与执行经验。Goo-wiki 不可用时写入 `.goo/obsidian/<project-slug>/` fallback；不得只写 `.goo/*.json` 或只在聊天中展示。`goo-brainstorm` 和 `goo-plan` 必须先让用户审阅，用户确认前只写本地 `.goo/brainstorm.json` / `.goo/plan.json` 草案，不急着归档最终知识页。

**同一任务归档根**：同一条任务链路的 brainstorm、plan 和 execution 知识归档默认放在同一个 `task_archive_root` 下，用子目录区分阶段：`brainstorm/` 保存候选目标、推荐顺序和选择依据；`plan/` 保存正式 DAG、上下文摘要和计划取舍；`execution/` 保存步骤证据、验证结果和最终经验。`task_archive_root` 优先位于 `wiki/projects/<project-slug>/tasks/<YYYY-MM-DDTHH-MM-SS-task-slug>/`；Goo-wiki 不可用时使用 `.goo/obsidian/<project-slug>/tasks/<task-slug>/`。`.goo/brainstorm.json.archive.task_archive_root` 与 `.goo/plan.json.archive.task_archive_root` 必须保持一致，除非用户明确要求分开归档。注意：这不同于本地 JSON 历史快照；旧 `.goo/plan.json` 仍保存到 `.goo/plans/history/`，旧 `.goo/brainstorm.json` 保存到 `.goo/brainstorms/history/`。

**HTML 发布层**：`/auto-goo:goo-publish` 是工作流的只读展示层，无需运行 `goo-init` 或创建 `.goo/config.json`，默认从 `.goo/brainstorm.json`、`.goo/plan.json`、`.goo/plans/history/`、`.goo/brainstorms/history/`、`.goo/logs/`、`.goo/artifacts/`、`.goo/reports/`、`.goo/obsidian/` 和当前项目 Claude Code usage 日志生成 `.goo/site/` 多页站点。`skills/auto-goo/templates/publish/workflow-shell.html` 是唯一运行时页面外壳，`skills/auto-goo/templates/publish/workflow-theme.css` 是唯一正式视觉主题；脚本填充标题、活动导航链接、正文、路径和交互脚本，并把主题复制到站点目录，禁止依赖发布后手工注入 CSS 或 `/tmp` 概念稿。正式主题采用紧凑工作台布局、浅色/暗色模式和页面语义色：计划/流程为蓝色、完成状态为绿色、代理执行为青色、头脑风暴为琥珀色、活动与归档为紫色、失败与风险为红色。默认生成总览、计划、活动、头脑风暴、运行状态、代理执行和产物归档页面，关键页面标签优先使用中文；桌面端固定左侧导航，移动端恢复自然滚动。Token 格子悬浮时显示消耗明细，点击或聚焦后由下方文本型工作流活动说明所选时间段实际完成的工作；活动记录列表显示对应用户任务摘要，点击记录后展开完整用户任务原文和使用详情，但不发布 assistant 回复或完整对话正文。它会启动 `0.0.0.0:9877` server、尝试弹出浏览器，同时打印 `127.0.0.1` 和本机 IP 访问地址；端口占用时自动尝试后续端口。server 默认只读取已生成的 HTML，打开页面时不重新扫描 `.goo/`；需要每次刷新实时重建时再加 `--live`。发布 HTML 不替代 Goo-wiki 归档，也不得修改当前 plan 或 brainstorm。

**用户交互契约**：任何需要用户选择、确认、重试、跳过、合并、改写或授权的步骤，必须优先调用结构化选择 UI / `AskUserQuestion`，让 Claude Code 渲染可用方向键移动、Enter 确认的选择控件；不得在工具可用时用普通文本要求用户手打 `1/2`、ID 或命令参数。每个问题至少给 2 个显式选项，推荐项放第一项并标注 Recommended；多候选问题必须把候选 ID/编号放进选项说明。只有结构化选择 UI / `AskUserQuestion` 不可用、调用失败或按钮没有渲染时，才允许降级为纯文本编号列表，并明确这是 fallback。用户未明确选择前，不得用推荐项静默继续。

**远程服务器机制**：`goo-init` 收集到远程服务器非敏感参数后，最终脚本调用必须追加 `--server 'ip=<host>,user=<user>,port=<port>,type=<cpu|gpu>,purpose=<用途>'`，可重复传多台；密码不得进入聊天、命令行、plan、日志或 prompt，只能由用户填入 chmod 600 的 secrets 文件。`goo-plan` / `goo-start` 只有在步骤确实需要远程算力、远程依赖、长跑环境或用户明确要求时，才写入并执行 `execution_target="remote"`、`remote_server` 和 `remote_reason`；远程 step 必须 `requires_user_confirm=true`，并通过 `skills/auto-goo/scripts/goo-ssh.sh --config <config> --server <remote_server> -- <remote command>` 执行，不默认使用第一台服务器。

**AskUserQuestion 固定结构**：需要 Enter-select 交互时必须按 `skills/auto-goo/references/interaction-templates.md` 中的 JSON 模板组织并实际调用 `AskUserQuestion`，不得只把结构写成自然语言题目或自由改写选项。字段固定为 `header`、`id`、`question`、`options[].label`、`options[].description`；推荐项放第一项，label 必须包含 `(Recommended)`。系统自动提供的 Other 只用于自定义输入，不算显式选项。凡能固定的问题必须复用模板；涉及路径、IP、端口、用户名、goal ID、分支目录、用户修改要求等输入时，模板必须提供默认选项并说明 Other 输入如何落盘、校验或继续追问。

## Phase -1: 项目初始化

首次使用 AutoGoo 时，建议先运行 `/auto-goo:goo-init --user` 写入用户级默认配置；进入具体项目后，可运行 `/auto-goo:goo-init --project` 写入项目级覆盖配置。

初始化要求：
1. 使用主 Agent 交互模式：收到命令后直接开始交互提问，不预先检查环境。主 Agent 必须用 `AskUserQuestion` 问清作用域、wiki 路径、是否更新项目 `CLAUDE.md`、是否配置远程服务器等，再调用脚本落盘；不得在结构化选择 UI 可用时用普通文本要求用户手打 `1/2` 或 `--project/--user`。不得派发 Subagent 代替初始化，也不得用临时代码写配置。如果结构化选择 UI / AskUserQuestion 不可用、调用失败或按钮没有渲染，才允许降级为明确标注 fallback 的纯文本列表选项，继续收集用户选择。
2. 最终落盘前必须先解析 AutoGoo 根目录：优先读取 Claude Code 安装记录 `$HOME/.claude/plugins/installed_plugins.json` 中 `auto-goo@*` 的 `installPath`。该 `installPath` 通常位于 `$HOME/.claude/plugins/cache/<marketplace>/<plugin>/<version>`，是 Claude Code 实际加载的插件副本。如果 `installPath` 不存在或已 orphaned，再读取 `$HOME/.claude/settings.json`，只有 `enabledPlugins` 中启用了 `auto-goo@<marketplace>`，且 `extraKnownMarketplaces.<marketplace>.source` 是本地 `directory` 时，才使用该本地 marketplace 路径。当前工作目录可能是用户项目，不要假设相对路径存在；不得读取环境变量，不得扫描当前目录、上级目录或源码 checkout 路径来猜插件根目录；不得在根目录变量为空时拼出 `/skills/auto-goo/scripts/goo-init.sh`。安装记录和本地 marketplace 都不可用或目标脚本不存在时，必须 fail-fast 提示用户重新安装/启用 AutoGoo 插件。
3. 根据参数或主 Agent 提问选择作用域：`--user` 写 `~/.auto-goo/config.json`，`--project` 写 `.goo/config.json`。如果用户只输入 `/auto-goo:goo-init`，必须先用 `AskUserQuestion` 询问作用域，不得默认选择 project；用户选择后必须把 `--user` 或 `--project` 传给脚本。作用域问题必须包含这两个结构化选项：「项目级 --project (Recommended) - 写入当前项目 .goo/config.json」「用户级 --user - 写入 ~/.auto-goo/config.json」。
4. 必须用 `AskUserQuestion` 询问 Goo-wiki 路径，提供默认值 `~/workspace/Goo-wiki`；如果用户不输入路径，就按默认值处理。每个 `AskUserQuestion` 至少 2 个选项（推荐默认值 + 备选），如「~/workspace/Goo-wiki (Recommended)」「自定义路径（选择后在下方 Other 输入）」。如果交互控件不可用，使用明确标注 fallback 的纯文本列表选项继续收集路径；用户接受默认值或输入自定义路径后，都必须把 `--wiki-dir <路径>` 传给脚本，不得在未展示默认路径的情况下静默使用默认值。
5. 询问用户是否有远程服务器需要配置。用户确认后，使用 `AskUserQuestion` 逐字段收集服务器信息。**每个问题必须至少 2 个显式选项**（系统的自动 Other 不算），用户可直接选用预设值或通过 Other 输入自定义值：服务器类型（GPU/CPU）、IP 地址、SSH 端口、用户名、用途说明、密码（可跳过，稍后手动填入 secrets 文件）。密码存储在独立 secrets 文件中（项目级 `.goo/secrets.json`，用户级 `~/.auto-goo/secrets.json`），文件权限 `chmod 600`；项目级 secrets 文件自动加入 `.gitignore`。config 中只记录 `servers[].{ip, port, user, type, purpose, secrets_file}`，不存储密码。支持配置多个服务器。
6. 配置远程服务器后，通过 `goo-ssh.sh` 连接。用法：`bash "$auto_goo_root/skills/auto-goo/scripts/goo-ssh.sh" [--config .goo/config.json] [--server INDEX|HOST]`。脚本从 `secrets.json` 读取密码，不暴露在命令行；如果没有配置密码，则退回普通 `ssh`，支持 SSH key 或手动认证。有密码自动登录时才需要 `sshpass`（首次使用前 `sudo apt install sshpass`）。
7. 确保目标目录存在：用户级 `~/.auto-goo/`，项目级 `.goo/`。
8. 如果目标配置已存在，脚本内部自行检测并询问是否覆盖。用户保留 config 但传了 `--update-claude-md` 或交互确认更新 `CLAUDE.md` 时，仍必须继续更新项目 `CLAUDE.md`。
9. 按优先级解析 wiki 路径：`AUTO_GOO_WIKI_DIR` → `.goo/config.json.wiki_dir` → `~/.auto-goo/config.json.wiki_dir` → `~/workspace/Goo-wiki`。
10. 确保 Goo-wiki 路径存在：如果用户确认或输入的 `<wiki_dir>` 不存在，脚本必须自动创建该目录，并补齐 `CLAUDE.md`、`log.md`、`wiki/projects/`、`wiki/concepts/`、`wiki/questions/`、`journal/daily/`、`journal/weekly/` 基础结构；不得因为路径不存在而改用 `.goo/obsidian/` fallback。
11. 如果是 `--project`，确定 `project_slug`：默认用项目根目录名，可用 `--project-slug <slug>` 覆盖；创建或复用 `<wiki_dir>/wiki/projects/<project_slug>/` 作为项目归档根路径。
12. 如果项目是 Git repo，读取 `origin` remote（没有 origin 时读取第一个 remote），写入 `.goo/config.json.archive.git_remote_url`，并同步到 `<wiki_dir>/wiki/projects/<project_slug>/<project_slug>.md` 的项目元信息块。
13. 写入目标 config，默认结构参考 `skills/auto-goo/templates/config.example.json`；项目级配置必须记录 `archive.project_slug`、`archive.project_dir` 和 `archive.fallback_project_dir`；有远程服务器时写入 `servers`。
14. 如果是 `--project` 且 Goo-wiki 可用，必须询问用户是否在项目 `CLAUDE.md` 中加入或更新 AutoGoo marker 包裹的项目归档原则和要求；只改该段，不覆盖用户已有项目指引。非交互场景默认不写，需传 `--update-claude-md` 明确写入；用户传 `--skip-claude-md` 时跳过。
15. 展示推荐 SessionStart hooks，但不要自动覆盖 `.claude/settings.json`，除非用户明确要求。
16. 配置完成后，脚本不得尝试连接服务器（不做 ssh、ping、端口探测等任何网络连接）；仅写入配置文件。

## Phase 0: Wiki 经验召回

**先查已有经验，再规划新任务。** AutoGoo 的默认目标不是从零开始，而是复用 Goo-wiki 中沉淀的项目知识、历史决策和失败经验。

召回步骤：
1. 按配置优先级解析 wiki 路径；不存在则记录 fallback，继续使用 `.goo/obsidian/` 本地归档。
2. 根据用户任务提取项目名、领域词、文件名、命令、数据路径、指标名等关键词。
3. 在 Goo-wiki 中优先查找：
   - `wiki/projects/` 下相关项目页和任务页
   - `wiki/concepts/` 下相关概念、指标、流程规范
   - `journal/weekly/` 下近期周报中的项目状态、风险、下一步
   - `log.md` 中最近活动记录
4. 提炼 `wiki_context`：已有约束、可复用命令、已验证路径、历史坑点、指标口径、命名规范、相关 wikilink。
5. 规划时必须显式利用这些上下文；如果没有找到相关知识，也要记录 `wiki_context.found=false`，避免假装有历史依据。

不要把 wiki 当成最后才写的报告；它是任务启动时的项目记忆，也是任务结束后的经验沉淀层。

## Brainstorm 指令

`/auto-goo:goo-brainstorm <方向/项目/问题>` 是 AutoGoo 内部指令，用于目标不明确时先找 goal，再进入 plan。

行为：
1. 解析 AutoGoo 配置和 Goo-wiki 路径。
2. 检索 `wiki/projects/`、`journal/weekly/`、`wiki/concepts/` 和 `log.md`。
3. 提取未完成事项、反复问题、风险、近期计划、指标缺口、文档缺口、测试缺口、发布阻塞和可复用经验。
4. 提炼共同前置条件 `global_prerequisites`，例如数据路径、账号权限、远程资源、评价指标、用户取舍和安全确认。
5. 生成 3-7 个候选 goals，每个包含 `id`、`name`、`why`、`expected_output`、`acceptance_criteria`、`evidence`、`risk`、`prerequisites`、`readiness_checklist`、`first_step`、`priority_hint`。
6. 写入 `.goo/brainstorm.json`，状态为 `pending_decision`。如果旧 `.goo/brainstorm.json` 已存在，先原样复制到 `.goo/brainstorms/history/brainstorm-<timestamp>.json`。
7. 向用户展示推荐顺序、共同前置条件和每个候选 goal 的 ready checklist，等待用户选择、合并、改写或要求继续 brainstorm；用户确认前只保留本地 `.goo/brainstorm.json` 草案，不写 Goo-wiki/fallback 最终归档。
8. 用户确认最终候选目标后，再将候选 goals、共同前置条件、推荐顺序、用户选择/合并依据和关键证据归档到同一任务归档根的 `brainstorm/` 子目录；Goo-wiki 不可用时写入 `.goo/obsidian/<project-slug>/tasks/<task-slug>/brainstorm/` fallback，并在 `.goo/brainstorm.json.archive` 记录 `task_archive_root` 和 `brainstorm_dir`。

边界：
- 不写 `.goo/plan.json`。
- 不生成执行 DAG。
- 不派发 Subagent 执行。
- 不修改业务文件；只允许写 `.goo/brainstorm.json` 和 Goo-wiki/fallback 归档笔记。
- 不运行实现、评测、训练、安装、远程或删除命令。
- 用户明确一个或多个 goals 后，再调用 `/auto-goo:goo-plan <明确目标>`。

## Phase 1: 任务解析

**必须先解析为 DAG，不得跳过规划直接动手编码。**

**并行优先**：DAG 规划默认最大化可安全并行的执行层。只有真实数据依赖、验收/用户确认门槛、共享写入冲突、资源冲突或高风险顺序要求，才允许写 `depends_on`。不要因为用户描述顺序、文档段落顺序、同属一个 goal 或“看起来更稳”把可并行步骤串成线性链。

### 规划前现有 plan 检查

每次进入 `/auto-goo:goo-plan`、`/auto-goo:goo-start` 中的自动规划阶段，或任何会写入新 `.goo/plan.json` 的流程前，必须先检查当前 `.goo/plan.json`：

1. 如果 `.goo/plan.json` 不存在，正常生成新 plan。
2. 如果存在旧 plan，读取 `steps[]` 和顶层 `status`，判断是否全部完成。只有所有 step 的 `status` 都是 `completed`，且顶层 `status` 为 `completed` 或可由 steps 推断为完成时，才允许直接归档旧 plan 并生成新 plan。
3. 如果存在未完成 step，或顶层 `status` 是 `pending` / `running` / `blocked` / `paused` / `failed`，必须暂停规划，向用户展示未完成 step 数量和关键摘要，并询问用户选择：
   - 修改当前 plan：把新需求合并进现有 `.goo/plan.json`，保留已完成步骤、日志、产物和执行证据。
   - 新建 plan：先把旧 `.goo/plan.json` 原样归档到 `.goo/plans/history/`，再写新的当前 plan。
4. 上述询问必须优先使用 `AskUserQuestion` / 结构化选择 UI 呈现；纯文本编号只作为交互控件不可用时的 fallback。用户未明确选择前，不得覆盖、归档或重写 `.goo/plan.json`。

解析步骤：
1. 识别输入形态 — 普通一句话、Markdown 任务包、已有 plan、issue/PR 描述、日志片段等要区别处理。
2. 如果输入是 Markdown 文件或片段，先解析标题层级、checkbox、编号列表、表格、代码块、路径、命令、约束和验收标准；不得简单视为"文本处理/整理 Markdown"任务。
3. 确认目标已明确 — 目标可以来自用户直接描述，也可以来自用户明确选择的 `.goo/brainstorm.json` candidate goal；如果用户还不知道要做什么、要求 brainstorm、探索方向或基于 wiki 找下一步，停止 plan 流程并切换到 `/auto-goo:goo-brainstorm`。
4. 识别交付目标 — 抽取一个或多个 `goals[]`，每个 goal 都要有交付物、验收标准和优先级；不能把多个目标压成一句含糊的总目标。
5. 如果用户选择了 brainstorm candidate goal，读取 `.goo/brainstorm.json`，把选中的 `candidate_goals[]` 转成正式 `goals[]`，并把 `prerequisites` / `readiness_checklist` 转成前置检查 step、`validation` 或 `requires_user_confirm`。
   - 如果 `.goo/brainstorm.json.archive.task_archive_root` 存在，plan 归档必须复用该目录，把正式 DAG 和计划摘要写到 `plan/` 子目录，并在 `.goo/plan.json.archive.task_archive_root` 记录同一个路径。
   - 如果 brainstorm 尚无 `task_archive_root`，先创建同一任务归档根并补写 `.goo/brainstorm.json.archive.task_archive_root` / `brainstorm_dir`，再写 plan 归档。
6. 判断 goal 关系 — 独立 goal 优先拆成多个 plan；共享前置步骤则保留一个 DAG 并分支；强依赖 goal 按依赖链串联；冲突或优先级不清时先问用户。
7. 合并 wiki_context — 把既有项目经验转成约束、默认命令、风险提醒和可复用产物路径。
8. 固化对话方案 — 把当前对话里已经形成的方案、备选路线、取舍原因、用户偏好、验收标准和仍未解决的问题写入 `context_digest`；大段材料优先写入 Goo-wiki 项目路径 `wiki/projects/<project-slug>/context/<timestamp>-planning-context.md` 并在 `context_artifacts` 引用，Goo-wiki 不可用时降级到 `.goo/obsidian/<project-slug>/context/`。
9. 逆向拆解 — 从每个 goal 倒推，追问到"不可再分"的原子步骤。如果任务本身就是单步的（如"把这个文件转成 PDF"），直接执行，不走此流程。
10. 标注依赖关系 — 识别前置条件，推导拓扑顺序。原始数据准备 → 处理 → 输出，每一步依赖前一步的输出；每个非归档 step 必须绑定 `goal_id` 或 `goal_ids`。
11. 并行优先审计 — 遍历所有非归档 step，移除仅由叙事顺序、文档顺序或保守习惯造成的依赖；只读同一输入、写不同产物、验收互不依赖的步骤应放入同一 `tier`，并保持空/相同 `depends_on`。每条依赖都要能说明具体上游产物、验收结果、确认门槛或冲突资源。
12. 识别优化标记 — 含"性能、速度、延迟、吞吐、效率、内存、GPU、耗时"关键词 → 标记 `type: "optimize"`
13. 追加默认归档步骤 — DAG 最后必须有 `归档到 Goo-wiki`，依赖所有非归档叶子步骤；除非用户明确禁止归档或配置 `archive.enabled=false`
14. 归档历史 plan — 仅当旧 plan 已完成，或用户明确选择“新建 plan”时，才把 `.goo/plan.json` 复制到 `.goo/plans/history/plan-<timestamp>.json`；不得静默覆盖未完成 plan。
15. 输出 `.goo/plan.json`，并在审阅摘要中展示并行组、必要串行链及主要风险。

### 步骤粒度原则

- 每步应产出可验证的中间结果（文件、指标、报告）
- 步骤过多（>10）说明拆分过细，考虑合并
- 步骤过少（<2）说明拆分不够，需要继续追问"还需要什么"
- 步骤粒度服务于并行调度：能独立读输入、独立写产物、独立验收的工作不要合并成一个大步骤，也不要串成逐步依赖

### Plan 拆分决策

**DAG 过深、步骤过多或中间需要判断时，就拆成多个小 plan。** 小 plan 2-4 步，目标是当前轮可直接完成并验收；大 plan 6-20 步，提供全局 DAG 视图但依赖心跳+产物检测兜底。

触发拆分的信号：步骤 > 8、DAG 层数 > 3、中间有人工判断点、后半段依赖前半段产物质量。

完整拆分规则 → `references/task-parsing.md`

### plan.json 概要

```json
{
  "task": "<任务描述>",
  "goals": [
    {
      "id": "g1",
      "name": "<目标名>",
      "description": "<该目标要交付什么>",
      "priority": 1,
      "status": "pending",
      "acceptance_criteria": ["<该目标的验收标准>"],
      "outputs": ["<该目标的最终产物>"],
      "depends_on": []
    }
  ],
  "status": "pending",
  "created_at": "YYYY-MM-DDTHH-MM-SS",
  "started_at": null,
  "completed_at": null,
  "wiki_context": {
    "found": true,
    "sources": ["wiki/projects/<slug>/<note>.md"],
    "reused_knowledge": ["<约束/命令/路径/指标/历史经验>"]
  },
  "context_digest": {
    "found": true,
    "decisions": ["<本轮对话已确认的方案/取舍>"],
    "constraints": ["<用户明确约束>"],
    "acceptance_criteria": ["<验收标准>"],
    "open_questions": []
  },
  "context_artifacts": ["<可选：<wiki_dir>/wiki/projects/<project-slug>/context/xxx.md 或任务说明 md>"],
  "steps": [
    {
      "id": 1,
      "goal_id": "g1",
      "tier": 1,
      "name": "<步骤名>",
      "description": "<做什么，含输入、边界、输出和验收点>",
      "depends_on": [],
      "type": "exec",
      "subagent": "implementer",
      "task_agent": "feature-builder",
      "available_skills": [],
      "status": "pending",
      "progress": 0,
      "output": "<主产物路径>",
      "inputs": ["<输入文件/上游产物/上下文 artifact>"],
      "outputs": ["<主产物路径>"],
      "allowed_read_paths": ["<允许读取的路径>"],
      "allowed_write_paths": ["<允许写入的路径>"],
      "validation": "<验收方式：命令、文件存在性、人工检查点或指标阈值>",
      "risk_level": "low",
      "requires_user_confirm": false,
      "agent_id": null,
      "heartbeat_at": null,
      "started_at": null,
      "completed_at": null
    },
    {
      "id": 2,
      "goal_ids": ["g1"],
      "tier": 2,
      "name": "归档到 Goo-wiki",
      "description": "将任务目标、计划、关键证据、产物路径、验证结果、决策和可复用经验归档到 Goo-wiki；必须补齐任务页、项目入口 <project-slug>.md、log.md、复用知识页和新增经验页之间的 Wikilink/backlink 关系，防止 Obsidian 连接图谱断裂；Goo-wiki 不可用时写入 .goo/obsidian/ fallback",
      "depends_on": [1],
      "type": "archive",
      "subagent": "recorder",
      "task_agent": "wiki-curator",
      "available_skills": [],
      "status": "pending",
      "progress": 0,
      "output": "Goo-wiki/wiki/projects/<project-slug>/ 或 .goo/obsidian/<project-slug>/",
      "inputs": [".goo/plan.json", ".goo/logs/", "<上游产物路径>"],
      "outputs": ["Goo-wiki/wiki/projects/<project-slug>/ 或 .goo/obsidian/<project-slug>/"],
      "allowed_read_paths": [".goo/plan.json", ".goo/logs/", ".goo/artifacts/"],
      "allowed_write_paths": ["Goo-wiki/wiki/projects/<project-slug>/ 或 .goo/obsidian/<project-slug>/"],
      "validation": "归档页或 fallback 笔记存在；任务页链接项目入口、复用的 wiki_context/context_artifacts 和关键概念/问题/指标/历史任务页；项目 <project-slug>.md 与 log.md 反向链接任务页；新增 concept/lessons/metrics 页也链接回任务页或项目入口；记录产物路径、验证结果和可复用经验",
      "risk_level": "low",
      "requires_user_confirm": false,
      "agent_id": null,
      "heartbeat_at": null,
      "started_at": null,
      "completed_at": null
    }
  ]
}
```

完整 schema、时间戳格式、依赖声明规则 → `references/task-parsing.md`

Markdown 任务输入的完整解析规则也在 `references/task-parsing.md`：Markdown 可以是需求文档、TODO 清单、执行计划或 issue 模板，只有用户明确要求总结/润色/改写时才按文本处理。

### Plan/Wiki/MD-only 执行契约

生成 plan 后，执行阶段必须能在不读取主会话历史的情况下继续。也就是说，`.goo/plan.json`、`context_artifacts` 指向的 Goo-wiki/Markdown、Goo-wiki 召回摘要和上游产物路径必须足够让 Subagent 完成对应 step。

- step 的 `description` 必须写清楚做什么、边界、输入、输出和验收点，不能依赖"刚才讨论的方案"。
- 多 goal plan 中，非归档 step 必须包含 `goal_id` 或 `goal_ids`；归档 step 用 `goal_ids` 覆盖所有被归档目标。
- step 应包含 `inputs`、`outputs`、`allowed_read_paths`、`allowed_write_paths`、`validation`、`risk_level` 和 `requires_user_confirm`，让执行阶段不用猜读写范围、验收方式和是否需要用户确认。
- `goo-start` / `goo-continue` 执行前默认执行 context sync：检查 plan 生成后当前对话是否新增方案、取舍、约束、验收标准、用户偏好或 open question。短内容写入 `context_digest.post_plan_updates`；长内容写入 Goo-wiki 项目路径 `context/` 并追加到 `context_artifacts`，Goo-wiki 不可用时写 `.goo/obsidian/<project-slug>/context/`。同步前必须先把旧 plan 复制到 `.goo/plans/history/`；只有新增内容与原 plan 冲突、扩大范围、改变验收标准或涉及危险操作时才问用户确认。确认问题必须优先使用结构化选项：`同步并继续执行`、`先修改 plan`、`停止并保留当前 plan`。
- `goo-start` / `goo-continue` 一旦准备把 plan 从待执行状态推进到执行状态，必须先检查 `.goo/brainstorm.json` 和 `.goo/plan.json` 的 `review.status`。如果仍是 `pending_user_review`，先停下来让用户审阅和确认；确认后如 brainstorm 还没有归档，再派发 `recorder` 归档最终版 brainstorm。该归档完成前，不启动业务 step 调度。
- Subagent prompt 只允许使用当前 step、`context_digest`、相关 `wiki_context`、`context_artifacts` 路径和上游产物摘要；不传完整聊天记录。

## Phase 2: 执行（槽位调度）

**当前 `.goo/plan.json` 是唯一状态源**。派发、完成、失败均实时回写当前 plan。历史 plan 只归档在 `.goo/plans/history/`，不得作为恢复来源，除非用户明确指定。执行时不得依赖主会话隐含上下文；所有执行必需信息必须在当前 plan、引用的 Markdown/context artifact、wiki 摘要或上游产物中。

**Brainstorm/Plan 审阅闸门**：执行调度开始前必须确认 `.goo/brainstorm.json` 和 `.goo/plan.json` 不是待审草案。若 `review.status="pending_user_review"`，先让用户审阅、修改或确认，并优先用结构化选项展示：`确认并继续`、`修改草案`、`停止/稍后再说`；不能自动归档或执行。用户确认后，如果 `.goo/brainstorm.json` 存在且未能证明已归档，再归档最终版 brainstorm，然后开始执行 plan steps。归档内容至少包括候选 goals、推荐顺序、用户最终选择、未选原因或合并依据、前置条件、ready checklist、关键 wiki 证据，以及该 brainstorm 如何转成当前 `.goo/plan.json`；归档完成后回写 `archive.status="completed"`、`archive.task_archive_root`、`archive.brainstorm_dir`、fallback 状态和 `log.md` 更新状态。若当前 plan 已有 `archive.task_archive_root`，brainstorm 必须补写到同一个 root 的 `brainstorm/` 子目录；若没有，则创建 root 并同步写回 plan 与 brainstorm。

**槽位调度模型**：固定 6 个并发槽位 + 动态就绪队列 + 连续下发。agent 完成即释放槽位，其下游立即入队，不用等同层其他 agent。

**主 Agent 总控**：主 Agent 负责整体目标、DAG 拆解、上下文裁剪、调度、验收、冲突处理和最终归档判断；Subagent 只执行被分配的 step，不得自行扩大范围或改写整体计划。

**强制 Subagent 执行**：除 `goo-plan` 只生成计划外，`goo-start` / `goo-continue` 的 `research`、`exec`、`optimize`、`eval`、`review`、`audit`、`archive` 步骤必须派发给对应 Subagent。主 Agent 不得直接替 Subagent 读写步骤产物、运行步骤命令或完成步骤验收。

**Subagent 缺失处理**：如果步骤的 `subagent` 字段缺失或不属于合法角色，先补 plan 或创建新的 Subagent 角色，不由主 Agent 降级代执行。

**Subagent 上下文隔离**：每个 Subagent 默认只拿当前 step、必要项目约束、相关 wiki_context 摘要、上游产物路径、允许读写边界和回写要求。Subagent 之间通过 `.goo/plan.json`、`.goo/logs/`、`.goo/artifacts/` 和产物路径交接，不共享完整会话历史或彼此的推理草稿。

**Subagent 显式分工**：每个 step 必须包含 `subagent` 和 `task_agent` 字段。`subagent` 只允许稳定 Role Agent：`researcher`、`implementer`、`optimizer`、`evaluator`、`reviewer`、`auditor`、`recorder`；`task_agent` 必须从对应 role 的 `agents/tasks/` 目录下选择，例如 `document-analyst`、`feature-builder`、`test-runner`、`code-reviewer`、`evidence-auditor`、`wiki-curator`。调度时先按 `subagent` 选择 role prompt，再按 `task_agent` 叠加细分任务 prompt。若缺失或不合法，先补 plan 或创建新角色/任务画像，不由主 Agent 代执行。

**权限分层**：AutoGoo 不让后台 Subagent 做平凡权限交互。普通读写和低风险命令必须在 plan 的 `allowed_read_paths`、`allowed_write_paths`、`validation`、`requires_user_confirm=false` 与项目命令 allowlist 中提前声明，Subagent 在边界内直接执行。可预见的安装依赖、网络下载、远程执行、长跑任务、端口监听、批量数据改写、跨机器同步或高成本操作，规划阶段必须标记 `requires_user_confirm=true`，由主 Agent 在派发前一次性说明作用域、命令类别、产物位置和风险并取得确认。执行中遇到 `PermissionDenied`、sandbox blocked、approval required、路径越界或命令不在允许范围时，Subagent 不得自行弹窗、不得静默跳过、不得要求主 Agent 直接代做；必须写日志并回写当前 step 为 `blocked`/`needs_user_approval`，说明所需命令、原因、读写路径、风险和建议处理。主 Agent 聚合这些阻塞项后在前台向用户申请许可；用户批准后只在批准范围内重派 Subagent 或执行许可命令，用户拒绝后再标记 failed 或调整 plan。

```
MAX_CONCURRENT = 6 (plan.json 顶层可覆盖)

主循环:
  1. 扫描 status=pending 且 depends_on 全 completed → 按优先级排序 → 入队
  2. 填充空槽位 (间隔 3-5s 错峰)，派发前调用 `goo-status.py --update-status`
  3. 等待任一 agent 完成 → 回写 plan.json → 调用 `goo-status.py --update-status` → 立即回到步骤 1
  4. 心跳巡检每 30s → 超时无心跳标记 failed → 调用 `goo-status.py --update-status` → 释放槽位
  5. 所有 step 完成或失败 → 调用 `goo-status.py --update-status` 做最终状态同步
```

### 心跳与进度（强制）

**主 Agent 派发 Subagent 时，prompt 必须包含 `references/execution-engine.md` 中对应类型的 Heartbeat 分段。** 不包含心跳指令会导致 Subagent 不更新 `heartbeat_at`，被误判为僵尸进程。

**Subagent 必须在以下里程碑调用 `update-step.py --heartbeat --progress <N>`**（非时间驱动，是进度驱动）：

| 里程碑 | progress | 命令 |
|--------|----------|------|
| 启动 | 5 | `--start --progress 5` |
| 读输入完成 | 15 | `--heartbeat --progress 15` |
| 核心过半 | 50 | `--heartbeat --progress 50` |
| 产物接近完成 | 85 | `--heartbeat --progress 85` |
| 完成 | 100 | `--complete` |
| 失败 | - | `--fail --error "<reason>"` |

先从 Claude Code 安装记录解析 AutoGoo 根目录；不要读取环境变量，也不要自动搜索插件目录。不要在 skill 文档中内联 heredoc / file redirection 的 Python 片段；需要回写 step 时，使用插件内置 `skills/auto-goo/scripts/resolve-root.sh` 或同等无 heredoc 封装来定位 root，再调用 `update-step.py`。

`/auto-goo:goo-status` 必须调用 `skills/auto-goo/scripts/goo-status.py` 渲染进度条和心跳告警。

### 失败处理

| 场景 | 处理 |
|------|------|
| 单个 Agent 失败 | 记录错误日志，回写 status="failed"，重试 1 次 |
| 权限/沙箱/approval 阻塞 | 调用 `update-step.py --block --error "needs_user_approval: <命令/原因/读写路径/风险>"`，主 Agent 前台询问用户许可；不得按普通失败重试或主 Agent 直接代做 |
| 重试仍失败 | 标记 ❌ failed，继续不依赖它的步骤 |
| 关键路径失败 | 通知用户，并优先用结构化选项询问：重试、跳过并继续、停止并保留现场 |
| Agent 超时（>5 分钟无心跳） | 视为失败，按失败流程处理 |
| 会话中断（心跳停滞 >= 2min） | `/auto-goo:goo-continue` 恢复时检测僵尸，按产物文件判断真实状态 |

### 日志铁律

每一步执行必须归档。失败也要写日志记录原因。日志时间戳统一使用 `YYYY-MM-DDTHH-MM-SS`。

### 常见偷懒理由

| Shortcut | Required behavior |
|----------|-------------------|
| "任务不大，先不写 plan" | 多步或有依赖就写/更新 `.goo/plan.json`，单步任务才跳过 AutoGoo |
| "归档最后凭记忆补" | 决策形成时写入 `context_digest` 或 `context_artifacts` |
| "直接读完整 wiki 更省事" | 先用 `scripts/wiki-graph-assist.py` 生成紧凑 graph packet |
| "Subagent 会自己补上下文" | 派发前把输入、边界、验收和上游产物写入 plan 或 artifact |

更多 skill 设计、渐进披露和验证门槛 → `references/skill-design.md`

### 命令安全

1. Bash 命令中**禁止出现换行符后接 `#` 的模式**（如多行字符串中的注释），否则会触发 Claude Code 的安全路径验证警告。应改为单行命令或临时文件传参。
2. 激活虚拟环境时**使用 `.` 而非 `source`**，避免触发"参数评估为 shell 代码"的安全扫描。
3. **任何删除文件或目录的操作都必须先问用户并取得明确确认**，包括项目内临时文件、`.goo/` 产物、缓存、日志和远程目录。禁止为了省事执行 `rm -rf`、`find ... -delete`、`git clean` 或等价清理命令。
4. **覆盖已有文件前必须判断来源和风险**：编辑代码/文档可按任务范围进行；但批量覆盖、移动覆盖、重生成配置、替换用户手写内容、覆盖 `.goo/config.json`、`CLAUDE.md`、`.claude/settings*.json` 前必须先说明影响并确认。
5. 禁止运行破坏性 Git 命令，除非用户明确要求具体操作：`git reset --hard`、`git checkout -- <path>`、`git clean`、强推、删除分支、改写历史等都属于高风险命令。发布到默认分支前必须单独确认。
6. **敏感信息只读不显**：不得 `cat`、整段复制或日志化 `secrets.json`、token、password、API key、SSH private key。需要验证时只检查文件是否存在、权限是否合理、JSON 是否可解析、必要字段是否存在，输出必须打码或只给摘要。
7. 使用远程服务器前必须确认任务确实需要远程/GPU/长时间运行，并在 plan step 中写清目标 host、用途、允许命令范围、读写路径和产物同步方式。禁止把 secrets 展开到命令行、日志或 Subagent prompt。
8. Subagent 执行命令前必须遵守当前 step 的允许读写边界；如果 step 缺少 `allowed_read_paths`、`allowed_write_paths` 或危险操作说明，先补 `.goo/plan.json` 或 context artifact，再派发执行。
9. 网络下载、安装依赖、启动长跑任务、后台服务、端口监听、批量数据改写、跨机器同步、`scp`/`rsync` 上传下载，都要在命令前说明作用域和输出位置；涉及外部写入、远程执行或不可逆成本时先确认。
10. Subagent 遇到权限不足、沙箱拒绝、approval required、命令 allowlist 不足或路径边界不匹配时，只能上报 `needs_user_approval`，不得直接请求平凡交互、不得循环重试、不得让主 Agent 在未获许可时降级代执行。

```bash
# ❌ 禁止：换行符后接 # 的安全警告
python3 << 'EOF'
data = {"key": "value"}  # 注释
print(data)
EOF

# ✅ 正确：单行或写入临时文件
python3 -c "data = {'key': 'value'}; print(data)"

# ❌ 禁止：source 触发 shell 代码安全扫描
source venv/bin/activate && python script.py

# ✅ 正确：使用 . 替代 source
. venv/bin/activate && python script.py
```

Subagent prompt 模板（exec / optimize / eval 三种变体）、上下文传递规则 → `references/execution-engine.md`

## Phase 3: 优化迭代

当步骤标记为 `type: "optimize"` 时启动。

**快速跳过条件**（满足任一则跳过）：
- 基线指标已达标（用户认可当前性能）
- 客观无提升空间（IO 瓶颈已达硬件上限）
- 用户明确说"不需要优化"

### 完整循环

1. WebSearch 搜索该领域标准评价指标
2. 实现基线版本并评测（至少 3 次取平均）
3. 瓶颈分析 — cProfile / py-spy / tracemalloc / 大 O 推算，至少一种
4. 优化 → 同指标评测对比
5. 终止判断：提升 < 20% 或连续两轮 < 5% 停止

### 评测约束

- 计时与内存测量分开进行（tracemalloc 拖慢计时）
- 测量前 warmup 至少 3-5 次
- 优先使用 pyperf 减少系统噪声

指标模板、终止条件表、领域推荐指标 → `references/optimization-loop.md`

## Phase 4: Obsidian 归档

每步完成后启动 Recorder Subagent，将执行记录转为 Goo-wiki 格式的 Obsidian 笔记。

- 归档路径：优先使用项目 config 中的 `archive.project_dir`，即 `Goo-wiki/wiki/projects/<project-slug>/`；fallback 使用 `archive.fallback_project_dir`
- 内容输出类命令即使不进入完整执行 DAG，也必须归档到 Goo-wiki 或 fallback。适用范围包括 brainstorm 候选 goals、usage/token 降本分析、日报/周报、改进建议、benchmark 指标、plan 摘要和执行经验；不得只写 `.goo/*.json` 或只在聊天中展示。
- 内容输出对应的 `.goo/*.json` 产物应包含 `archive` 字段，记录归档路径、fallback 状态和 `log.md` 是否更新。
- 如果 Goo-wiki vault 不存在且 `.goo/obsidian/` 也不必要（临时项目），跳过归档，仅保留 `.goo/logs/` 日志
- 如果项目是 Git repo，归档到项目页或任务总览时必须记录 git remote 地址；优先使用 `.goo/config.json.archive.git_remote_url`
- 归档必须维护 Markdown 关联图谱：写入前检索相关项目页、概念页、问题页、周报、历史任务页和 `context_artifacts`；写入任务页时添加高价值 `[[Wikilink]]`；写入后更新项目入口 `<project-slug>.md`（维护 `## 最近任务`、`## 可复用经验`、`## 代码结构` 等小节的双向链接）和 `log.md`，避免新页面孤立
- 归档 step 的完成条件必须包含链接验收：任务页链接项目入口、复用的 `wiki_context` / `context_artifacts` 和关键概念/问题/指标/历史任务页；项目 `<project-slug>.md` 的 `## 最近任务` 包含本次任务页链接，`## 可复用经验` 和 `## 代码结构` 按需更新；`log.md` 反向链接任务页；新增 lessons/metrics 页面链接回任务页或项目入口。缺少这些连接时不得把 archive step 标记为 completed。
- 为节省 token，Recorder 优先在解析 AutoGoo 根目录后调用 `skills/auto-goo/scripts/wiki-graph-assist.py` 生成紧凑 graph packet，并在任务页写好后用该脚本的 `--update-index --append-log` 维护项目入口和活动日志；只有候选链接不足时才读取完整 Markdown
- YAML frontmatter 规范、wikilink 格式、log.md 追加格式 → `references/obsidian-archive.md`

Goo-wiki vault 检测：默认检查 `~/workspace/Goo-wiki/CLAUDE.md`。路径可配置，见 `references/setup.md`。

## Daily Report: 日报/周报

当用户要求"日报"、"写日报"、"生成日报"、"总结今天"、"今天干了什么"、"周报"、"周总结"、"daily report" 或显式调用 `/auto-goo:goo-daily-report` 时，执行日报流程，不需要生成 `.goo/plan.json`。

执行入口：
1. 解析日期：无参数默认今天；"昨天"、"今天"、"本周"转换为具体日期范围。
2. 按 AutoGoo 配置优先级解析 Goo-wiki 路径。
3. 解析 AutoGoo 根目录后运行 `skills/auto-goo/scripts/daily-report-sessions.py --date YYYY-MM-DD` 提取 Claude Code 与 Codex 会话摘要。
4. 必要时读取关键会话尾部补充最终状态，不逐条抄录聊天。
5. 写入或续写 `<wiki_dir>/journal/daily/YYYY-MM-DD.md`，并更新 `<wiki_dir>/log.md`。

完整模板、续写规则和敏感信息规则见 `commands/goo-daily-report.md`。

## Usage Monitor: Token/Usage 统计

当用户要求"usage"、"token 统计"、"Claude 用量"、"消耗监控"或显式调用 `/auto-goo:goo-usage` 时，**只做一件事：运行脚本，原样输出结果**。

**铁律**：不得自己读 JSONL、不得自己算 token、不得自己生成表格或文字摘要。脚本是唯一输出源。

执行：
1. 解析用户意图 → 映射为脚本参数（`--tab`、`--once`、`--view` 等），见 `commands/goo-usage.md`。
2. 解析 AutoGoo 根目录后运行 `skills/auto-goo/scripts/goo-usage.py <参数>`。
3. 原样展示脚本输出。脚本输出已是完整渲染结果，不要追加任何解释、总结或补充。

不要提示用户手动进入插件目录或直跑内部脚本；用户侧推荐使用 `/auto-goo:goo-usage`，脚本路径由命令从 Claude Code 安装记录的 `installPath` 解析，必要时 fallback 到已启用的本地 directory marketplace。

## Phase 5: 自改进 (Self-Improvement)

在每次任务归档后触发。插件自身也需要根据使用情况迭代优化。

### 自动触发（每次任务后）

Phase 4 归档完成后，在任务日志末尾追加 `## 流程问题` 反思记录：

```yaml
## 流程问题
- 问题: "<具体摩擦点>"
  根因: "<分析>"
  改进: "<建议修改的文件>"
  优先级: high | medium | low
```

### 汇总触发（每 5 个任务或 `/auto-goo:goo-improve`）

执行以下改进流程：

1. **采集** — 读取近 5 个任务的 `## 流程问题` 记录
2. **聚类** — 统计高频项（出现 >= 2 次标记为高频）
3. **定位** — 对照修改范围决策表确定目标文件
4. **方案** — 生成具体到文件+行的修改建议
5. **确认** — 展示给用户，并优先用结构化选项询问：`应用修改`、`只保存建议`、`放弃本次改进`；经用户明确确认后执行
6. **记录** — 写入 `.goo/improvements.log`

### 修改范围决策

| 信号 | 修改目标 |
|------|---------|
| 命令频繁弹窗 | `.claude/settings.local.json` allowlist |
| 步骤失败/用户纠正 | 对应 reference 文件 |
| 重复解释 | 补充 reference 内容 |
| 解析遗漏 | `references/task-parsing.md` |
| 技能触发不准 | SKILL.md frontmatter description |

完整自改进规范 → `references/self-improvement.md`

## Python 项目规范

当任务涉及 Python 实现时：
- Python 3.10+，完整类型注解，ruff lint（line-length=100）
- 优先使用标准库，外部依赖在 plan.json 声明 `[dep: <包名>]`
- 不 scope creep — 不做任务描述未要求的功能

完整规范 → `references/python-standards.md`
## 附加资源

### Reference Files
- **`references/setup.md`** — 环境设置、Goo-wiki 路径配置、推荐 SessionStart hooks
- **`references/skill-design.md`** — AutoGoo skill 结构、上下文预算、脚本优先和验证门槛
- **`references/task-parsing.md`** — plan.json schema、解析流程、依赖与并行判断规则
- **`references/execution-engine.md`** — 执行流程、Subagent prompt 模板、错误处理、日志格式、上下文传递
- **`references/optimization-loop.md`** — 完整循环、指标模板、评测规范、终止条件
- **`references/obsidian-archive.md`** — Goo-wiki 归档规范、Recorder prompt、笔记类型与命名
- **`references/self-improvement.md`** — 插件自改进机制、触发条件、流程与决策规则
- **`references/python-standards.md`** — 代码风格、项目结构、核心接口约定

### Examples
- **`examples/csv-analysis-workflow.md`** — 完整工作流示例（CSV 销售数据分析）
- **`examples/optimization-workflow.md`** — 优化迭代示例（JSON 序列化性能优化）
- **`examples/multi-step-orchestration.md`** — 多步骤并行编排示例（ETL 数据管道）

### Scripts
- **`skills/auto-goo/scripts/init-plan.sh`** — 初始化 plan.json 模板；调用前先解析 AutoGoo 根目录
- **`skills/auto-goo/scripts/wiki-graph-assist.py`** — 生成紧凑 Goo-wiki 关联图谱上下文，并可维护项目 index/log 链接；调用前先解析 AutoGoo 根目录
- **`skills/auto-goo/scripts/check-plugin.sh`** — 插件结构完整性自检脚本（安装后运行确认所有组件就绪）；调用前先解析 AutoGoo 根目录
- **`skills/auto-goo/scripts/goo-ssh.sh`** — 连接已配置的远程服务器；有密码时从 `secrets.json` 读取并用 `sshpass`，无密码时走普通 `ssh`。调用前先解析 AutoGoo 根目录

### Agents
- **`../../agents/roles/researcher.md`** — 调研 Role Agent（查资料、读文档、整理约束和方案选项）
- **`../../agents/roles/implementer.md`** — 执行 Role Agent（实现功能或修复）
- **`../../agents/roles/optimizer.md`** — 优化 Role Agent（性能测量、瓶颈分析、局部优化）
- **`../../agents/roles/evaluator.md`** — 评测 Role Agent（运行测试、benchmark、数据质量检查）
- **`../../agents/roles/reviewer.md`** — 审查 Role Agent（审查代码、方案、风险和缺失测试）
- **`../../agents/roles/auditor.md`** — 审计 Role Agent（安全、合规、证据链、可追溯性和交付风险）
- **`../../agents/roles/recorder.md`** — 记录归档 Role Agent（整理日志、产物、评测结果和经验）
- **`../../agents/tasks/audit/security-checker.md`** — auditor 旗下安全检测 Task Agent（扫描注入、XSS、敏感信息泄露、依赖漏洞）
- **`../../agents/tasks/recording/obsidian-recorder.md`** — recorder 旗下 Obsidian 归档 Task Agent（格式化 Goo-wiki 笔记）
