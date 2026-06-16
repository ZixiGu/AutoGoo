# AutoGoo

![Claude Code Plugin](https://img.shields.io/badge/Claude%20Code-Plugin-blue)
![Version](https://img.shields.io/badge/version-0.3.9-green)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

AutoGoo 是一个 Claude Code 插件，用来把开放式任务拆成可执行计划、并行调用 subagent、记录运行状态，并把结果同步到 Goo-wiki / Obsidian。

![AutoGoo workflow](docs/assets/autogoo-workflow.svg)

## 适合什么场景

- 复杂任务需要先规划、再执行、再验收。
- 多个独立步骤可以并行交给 subagent。
- 需要用 thread 隔离多条任务线，并在 plan 中保留清晰状态和续跑入口。
- 需要把研究、日报、周报、用量分析或 HTML 产物归档到 Goo-wiki。
- 需要固定交互模板，减少临时口头确认。

## 安装

### 从 marketplace 安装

```text
/plugin marketplace add ZixiGu/AutoGoo
/plugin marketplace update
/plugin install auto-goo@AutoGoo --scope user
/reload-plugins
```

### 从本地 checkout 安装

```text
/plugin marketplace add /path/to/AutoGoo
/plugin install auto-goo@AutoGoo --scope user
/reload-plugins
```

这里 `auto-goo@AutoGoo` 的前半段来自 `.claude-plugin/plugin.json` 的 `name`，后半段来自 `.claude-plugin/marketplace.json` 的 `name`。`/plugin install` 默认安装到用户级；显式 `--scope user` 是为了避免和项目级安装混用。

如果提示 `already installed globally`，说明用户级已安装，直接运行 `/reload-plugins`。如需启用已禁用的用户级插件，在 shell 里运行 `claude plugin enable auto-goo@AutoGoo --scope user`，不要用 `/plugin enable`。

如果已经安装旧版本，先运行：

```text
/plugin marketplace update
/plugin update auto-goo
```

## 快速开始

```text
/auto-goo:goo-init --user
/auto-goo:goo-init --project

/auto-goo:goo-plan "把当前项目整理成可执行发布计划"
/auto-goo:goo-start
/auto-goo:goo-status
/auto-goo:goo-continue
```

常见节奏：

1. `goo-init` 创建用户级或项目级配置。
2. `goo-plan` 自动询问继续当前 thread 还是新建 thread，并生成计划。
3. `goo-start` 执行已确认计划。
4. `goo-status` 查看状态、日志和阻塞项。
5. `goo-continue` 从当前状态续跑。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| [`goo-init`](commands/goo-init.md) | 初始化 AutoGoo 配置和目录。 |
| [`goo-brainstorm`](commands/goo-brainstorm.md) | 先发散方案，再让用户选择。 |
| [`goo-plan`](commands/goo-plan.md) | 生成 `.goo/plan.json` 执行计划。 |
| [`goo-start`](commands/goo-start.md) | 执行当前计划。 |
| [`goo-continue`](commands/goo-continue.md) | 从中断或阻塞状态继续。 |
| [`goo-status`](commands/goo-status.md) | 查看计划状态、日志和下一步。 |
| [`goo-publish`](commands/goo-publish.md) | 发布 HTML 工作流状态页。 |
| [`goo-research`](commands/goo-research.md) | 研究资料和论文归档。 |
| [`goo-usage`](commands/goo-usage.md) | 用量监控和降本分析。 |
| [`goo-daily-report`](commands/goo-daily-report.md) | 生成日报、周报或月报。 |
| [`goo-benchmark`](commands/goo-benchmark.md) | 记录任务质量基线。 |
| [`goo-improve`](commands/goo-improve.md) | 根据历史记录改进流程。 |

## 核心约定

- **Thread 状态**：每条任务线保存在 `.goo/threads/<thread_id>/`；兼容入口 `.goo/plan.json` 指向当前 thread 的 active plan。
- **计划状态**：plan 是任务执行的源头，步骤状态包括 `pending`、`running`、`completed`、`blocked`、`failed`。
- **用户确认**：涉及范围、方案、优先级或不可自动决定的选项时，优先用 `AskUserQuestion` 的固定选项模板。
- **并行执行**：同层级且互不依赖的步骤会优先并行；串行依赖需要在计划里写明原因。
- **日志记录**：subagent 的过程信息写入当前 thread 的 `logs/`，前台只展示摘要、阻塞和下一步。
- **归档记忆**：默认写入 Goo-wiki；没有配置时回退到 `.goo/obsidian/`。
- **安全边界**：敏感信息放在 `.goo/secrets.json` 或 `~/.auto-goo/secrets.json`，不要写入计划、日志或 HTML 发布页。
- **Web 修改请求**：`goo-publish --serve` 可在网页提交修改请求，落盘到 `.goo/change-requests/`，由 AutoGoo 后续读取并让模型修改、审计。

## 配置

AutoGoo 读取两级配置：

- 用户级：`~/.auto-goo/config.json`
- 项目级：`.goo/config.json`

常用配置项：

| 字段 | 用途 |
| --- | --- |
| `wiki_dir` | Goo-wiki / Obsidian 根目录。 |
| `archive` | 归档目录、回退目录和命名规则。 |
| `execution` | 并发数、超时、日志和 heartbeat 行为。 |
| `planning` | 默认执行模式、用户确认策略和计划细节级别。 |
| `publish` | HTML 状态页输出目录和可见字段。 |
| `servers` | 远程机器、角色、路径和连接策略。 |

推荐用 `goo-init` 生成默认配置，再按项目补充少量字段。完整字段说明见 [`references/setup.md`](skills/auto-goo/references/setup.md)。

## 目录

```text
AutoGoo/
├── commands/                 # Claude Code slash command 文档
├── skills/auto-goo/           # 技能说明、脚本和 reference 文档
├── agents/                    # subagent 角色与任务模板
├── hooks/                     # 运行钩子
├── docs/                      # 架构、原型和发布说明
└── scripts/                   # 发布和校验脚本
```

运行时目录一般位于当前项目：

```text
.goo/
├── current_thread.json
├── threads/
├── change-requests/
├── locks/
├── plan.json
├── config.json
├── logs/
├── obsidian/
└── secrets.json
```

## 深入文档

| 主题 | 文档 |
| --- | --- |
| 安装和配置 | [`references/setup.md`](skills/auto-goo/references/setup.md) |
| 任务解析 | [`references/task-parsing.md`](skills/auto-goo/references/task-parsing.md) |
| 执行引擎 | [`references/execution-engine.md`](skills/auto-goo/references/execution-engine.md) |
| heartbeat 和日志 | [`references/heartbeat.md`](skills/auto-goo/references/heartbeat.md) |
| Goo-wiki 归档 | [`references/obsidian-archive.md`](skills/auto-goo/references/obsidian-archive.md) |
| 交互模板 | [`references/interaction-templates.md`](skills/auto-goo/references/interaction-templates.md) |
| subagent 架构 | [`docs/subagent-architecture.md`](docs/subagent-architecture.md) |
| 所有命令 | [`commands/`](commands/) |

## 校验

修改插件后运行：

```bash
bash skills/auto-goo/scripts/check-plugin.sh
```

发布前至少确认：

- manifest、命令、skill 文件存在。
- `.goo/plan.json` 和日志路径可正常生成。
- 版本号在 `README.md`、`pyproject.toml` 和 `.claude-plugin/plugin.json` 中一致。

## 运行要求

- Claude Code 支持插件和 slash command。
- 本机可运行 `bash`、`python3`、`git`。
- 使用 Goo-wiki 时，需要配置 `wiki_dir` 或让 AutoGoo 回退到 `.goo/obsidian/`。

## 版本

当前版本：**v0.3.9**。

## 许可证

MIT
