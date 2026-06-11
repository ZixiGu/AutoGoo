---
name: auto-goo:goo-start
description: 启动 AutoGoo 完整工作流 — 召回 wiki 经验、生成 DAG、执行、验证并归档
---

# /auto-goo:goo-start — 启动 AutoGoo 工作流

输入 `/auto-goo:goo-start <任务描述>` 启动完整工作流。若只想生成计划、不执行，请使用 `/auto-goo:goo-plan`。

## 工作流阶段

1. **Wiki 经验召回** — 读取已有项目知识和历史经验
2. **对话方案固化** — 把当前对话中已经确认的方案、约束、取舍和验收标准写入 `.goo/plan.json.context_digest`；大段内容写入 Goo-wiki 项目路径 `wiki/projects/<project-slug>/context/*.md`，Goo-wiki 不可用时降级到 `.goo/obsidian/<project-slug>/context/*.md`
3. **任务解析** — 将任务拆解为 DAG 步骤；写入新的 `.goo/plan.json` 前，先把已有 plan 归档到 `.goo/plans/history/`
4. **执行前上下文同步** — 如果当前 `.goo/plan.json` 已存在，默认检查 plan 生成后新增的对话方案、约束、验收标准和用户偏好；有增量时先把旧 plan 复制到 `.goo/plans/history/`，再写入 `context_digest.post_plan_updates` 或 `context_artifacts`，然后再执行
5. **审阅与归档闸门** — 一旦 plan 准备开始执行，先检查 `.goo/brainstorm.json` 和 `.goo/plan.json` 的 `review.status`。如果仍是 `pending_user_review`，先展示摘要并优先用 `AskUserQuestion` / 结构化选择 UI 让用户确认、修改或停止，不自动归档或执行。确认后，如果 brainstorm 存在且 `archive` 缺失、`archive.status` 不是 `completed`，或归档路径不可验证，必须先派发 `recorder` 归档最终版 brainstorm；归档完成并回写 `.goo/brainstorm.json.archive` 后，才能进入业务 step 调度
6. **执行前自检** — 确认每个待执行 step 不依赖主会话隐含上下文，只依赖 plan、Markdown/context artifact、wiki 摘要和上游产物；检查每个 step 的 `subagent` 和 `task_agent` 是否合法，并检查 `available_skills` 是否只包含本步骤需要且实际可用的 skill；不合法时先补 plan 或创建角色，不直接降级主 Agent 执行
7. **远程执行自检** — 对 `execution_target="remote"` 的 step，先从 `.goo/config.json` 或 `~/.auto-goo/config.json` 读取 `servers[]`，确认 `remote_server` 能唯一匹配配置项、secrets 文件存在且不展开密码；派发前用结构化确认向用户说明远程命令类别、目标服务器、远程路径、产物位置和风险。未获确认时标记 `blocked` / `needs_user_approval`，不得自动改成本地执行。
8. **Subagent 隔离策略初始化** — 启动业务 step 调度前先读当前 thread plan 顶层 `runtime.subagent_isolation`；如果已有 `mode` 且 `project_root` 与当前 AutoGoo 项目根一致，直接复用该缓存，不再做 Git 检查或再次询问。缓存缺失、`project_root` 不匹配或用户明确切换执行目录时，才检查一次当前项目根本身是否是 Git repo 且 `HEAD` 可解析；不要设置 `GIT_DISCOVERY_ACROSS_FILESYSTEM`，不要向父目录、跨文件系统或备用路径寻找 Git root。Git worktree 隔离的目的只是让 Subagent 在独立 worktree 中修改，便于 diff、回滚和并行写入隔离；非 Git 项目没有 commit/HEAD 可作为隔离基线，因此不需要也不能使用 worktree 隔离。若当前项目根不是 Git repo，优先复用同 thread 已记录的 `decision="continue_non_git"`；没有记录时才用 `AskUserQuestion` 复用 `id=git_init_project` 模板询问是否运行 `git init`。用户选择“继续非 Git 执行”时写入 `{"mode":"none","project_root":"<path>","checked_at":"<iso>","decision":"continue_non_git","reason":"project_not_git_user_declined_init"}` 并继续；选择“运行 git init”时优先运行 `git init -b main`，不支持 `-b` 的 Git 版本必须在初始化后立即把默认分支设为 `main`，且不自动 `git add` 或 commit，随后重新检查 `HEAD`：若已有可解析 HEAD 才写 `mode="worktree"`，否则写 `{"mode":"none","project_root":"<path>","decision":"git_init_without_head","reason":"git_initialized_without_head"}` 并继续普通非 Git 执行；选择“停止执行”时标记 workflow blocked/paused，不派发步骤。只有 `mode="worktree"` 时，后续 Agent tool 才允许传 `isolation: "worktree"`；`mode="none"` 时必须省略 `isolation` 参数，并在 Subagent prompt 中说明当前项目是普通非 Git 执行、只能写 `allowed_write_paths`、不得执行破坏性操作。不得在每次派发前重复运行 git 检查；如果 Agent 工具仍报 `Failed to resolve base branch "HEAD"`，最多记录一次失败并标记当前调度为 blocked/需要用户选择，不得循环 probe。
9. **Thread 资源锁检查** — 派发任何会写文件、wiki、server 或 port 的 step 前，调用 `thread-locks.py check-plan --plan <thread-plan>` 或按 step 逐项 `acquire` 检查冲突。只读同一资源不冲突；写同一文件、同一 wiki 页面、同一端口或同一远程长任务资源冲突时，把 step 标记为 `blocked` 并让主 Agent 前台询问用户处理方式。
10. **执行** — 按轮次并行/串行分发 Subagent；除生成 plan 本身外，主 Agent 不得直接代做 `research` / `exec` / `optimize` / `eval` / `review` / `audit` / `archive` 步骤。远程 step 通过 `skills/auto-goo/scripts/goo-ssh.sh --config <config> --server <remote_server> -- <remote command>` 执行；命令只能引用 plan 中已声明的远程路径和产物，不把密码写入 prompt、日志或命令行。派发每个 Subagent 前，主 Agent 必须先调用 `update-step.py --start --progress 5 --agent-id <agent>` 写入首个 `heartbeat_at`，再启动 Agent；这样即使 Agent 启动慢，前台 status 也能立即看到心跳。**每个 Subagent prompt 必须包含 `references/execution-engine.md` 中对应的 Heartbeat 强制分段**，否则 Subagent 不更新 `heartbeat_at`，会被误判为僵尸进程。Agent 返回 `Done` 时，`0 tool uses` 只能作为可疑信号；文本型 step 可以无工具完成，但必须有结构化最终答复、step log、heartbeat 里程碑或声明产物之一。若 step 声明了 `output`/`outputs`，必须验证产物存在且满足 `validation` 后才能 completed；缺失时记录实际 isolation 参数、plan 隔离模式和缺失路径，标记 blocked/failed，不得解锁下游。**每次 step 状态变更后，必须立即调用 `goo-status.py --update-status` 更新 plan 顶层 `status`、`started_at`、`completed_at`**，确保 plan 顶层状态与实际 step 状态一致。每次派发批次后、每轮 30s 心跳巡检后，以及任一 Agent 完成后，主 Agent 必须运行 `goo-status.py` 并把 RUNNING/告警摘要展示给用户；不得只在后台静默更新 plan。
11. **优化**（如需要）— 指标搜索 → Baseline → 优化 → 评测对比
12. **归档** — 执行记录和新增经验写入 Goo-wiki

## 参数

任务描述支持自然语言，不限格式。AutoGoo 会自动解析目标、拆解步骤、标注依赖。

如果当前目录已经存在 `.goo/plan.json`，且用户没有提供新的任务描述，优先从当前 plan 执行。执行前默认做一次 context sync：若当前对话在 plan 生成后新增了方案、取舍、约束、验收标准、用户偏好或 open question，先把旧 plan 复制到 `.goo/plans/history/`，再把短内容写入 `context_digest.post_plan_updates`，长内容写入 Goo-wiki/Markdown 并追加到 `context_artifacts` 后执行。只有新增内容与原 plan 冲突、扩大范围、改变验收标准或涉及危险操作时才询问用户确认；该询问必须优先使用结构化选项：`同步并继续执行`、`先修改 plan`、`停止并保留当前 plan`。

如果 `.goo/current_thread.json` 存在，`goo-start` 默认执行 current thread 的 active plan；如果用户提供新的任务描述且 current thread/plan 未完成，必须先用 `AskUserQuestion` 复用 `id=thread_action` 模板询问“新建 thread / 继续当前 thread / 取消”。用户选择新建 thread 时，生成新的 `.goo/threads/<thread_id>/plan.json` 并把 thread id 写入 plan；用户选择继续当前 thread 时，才允许合并或更新当前 thread 的 plan。执行过程中每次调用 `update-step.py` 或 `goo-status.py --update-status` 后，都必须同步 `.goo/threads/<thread_id>/thread.json.status` 和 `.goo/threads/index.json`。

执行前必须扫描 `.goo/change-requests/*.json`。对当前 thread 的 `pending_model_update` 请求，把请求同步进 plan 或新增修改 step；对其他 thread 的请求，先用结构化选择让用户决定切换、复制或跳过。模型修改完成后必须增加审计 step，审计通过再把请求状态改为 `completed`；审计失败则改为 `needs_revision`。

审阅或冲突确认必须优先使用 `AskUserQuestion` / 结构化选择 UI，并复用 `skills/auto-goo/references/interaction-templates.md` 中 `id=start_plan_review` 的 JSON 模板。新增约束或修改要求通过 Other 输入，输入后必须写入 `context_digest` 或更新 plan。如果结构化选择 UI / AskUserQuestion 不可用、调用失败或按钮没有渲染，使用以下纯文本 fallback：

```text
执行前需要确认当前 plan。请选择处理方式：
1. 确认并继续执行
2. 修改 plan / 同步新增约束
3. 停止并保留当前现场

这是 fallback；请回复 1/2/3，或直接写修改要求。
```

## 示例

```
/auto-goo:goo-start 用 Python 实现一个 CSV 解析器，支持大文件
/auto-goo:goo-start 优化项目中 JSON 序列化的性能
/auto-goo:goo-start 分析销售数据并按地区汇总
/auto-goo:goo-start 写一个斐波那契数列的单元测试
/auto-goo:goo-start 把这个 Markdown 文件转成 PDF 报告
```

## 备注

- 如果用户明确使用 `/auto-goo:goo-start`，即使任务只有单步，也生成一个带 `subagent` 的 step 并派发执行；只有未进入 AutoGoo 工作流的普通单步问答/小改动才可直接处理
- 执行阶段不能依赖聊天记录里的隐含方案；默认先同步 plan 后对话增量，发现信息缺失时先补 plan 或写 Goo-wiki 项目路径 `context/*.md`
- 如果 `.goo/brainstorm.json` 或 `.goo/plan.json` 的 `review.status` 仍是 `pending_user_review`，执行开始前必须先停下来让用户审阅和确认；不得把未确认草案自动归档或直接执行
- 如果 `.goo/brainstorm.json` 存在且已经被用户确认，执行开始前必须确认 brainstorm 已归档；未归档时先归档最终确认版 brainstorm，再启动业务 step
- 执行阶段必须使用 plan step 中声明的 `subagent` 和 `task_agent`；若任一字段缺失或不合法，先补 plan 或创建角色/任务画像，不由主 Agent 直接代执行
- 执行阶段把 plan step 中的 `available_skills` 作为 Subagent prompt 的 skill allowlist；没有额外 skill 时传空数组，不把全部 skill 默认塞给 Subagent
- 执行阶段必须记录当前 `thread.id`；thread plan 使用 `.goo/threads/<thread_id>/plan.json`，日志写 `.goo/threads/<thread_id>/logs/`，并在执行完成、失败或阻塞后更新 thread 状态
- 执行阶段必须尊重 `.goo/locks/` 中的资源锁；冲突时不要并行写同一资源
- 执行阶段尊重 plan step 的 `execution_target`；远程 step 必须使用配置中的 `remote_server` 和 `goo-ssh.sh`，并在用户授权后执行，不从聊天记录猜默认服务器
- 执行阶段必须尊重缓存的 Subagent 隔离策略：启动或恢复时写入 `runtime.subagent_isolation.mode`，后续派发只读取该字段；值为 `worktree` 才给 Agent tool 传 `isolation: "worktree"`，值为 `none` 则按普通非 Git 项目执行并省略 `isolation`。不得把非 Git 项目提升到父级 Git root 下派发，也不得围绕 `Failed to resolve base branch "HEAD"` 做重复探测。
- 优化迭代默认最多 3 轮
- 日志保存在当前 thread 的 `.goo/threads/<thread_id>/logs/`；旧 `.goo/logs/` 仅作为兼容读取路径
- Plan 顶层 `status`（`pending` → `running` → `blocked` → `completed`/`failed`）由 `goo-status.py --update-status` 自动计算更新，主 Agent 在每次 step 状态变更后必须调用
