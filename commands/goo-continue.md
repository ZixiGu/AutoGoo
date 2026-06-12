---
name: auto-goo:goo-continue
description: 从中断处继续执行 AutoGoo 任务 — 读取 .goo/plan.json 的三重检测（状态+文件+心跳）恢复未完成步骤
---

# /auto-goo:goo-continue — 继续执行任务

从上次中断处继续执行。默认读取 `.goo/current_thread.json` 指向的 thread plan；没有 current thread 时读取 `.goo/plan.json`。用三重检测判断每步真实状态，从未完成的步骤开始按 DAG 拓扑重新执行。

`goo-continue` 的执行依据只能是当前 `.goo/threads/<thread_id>/plan.json` 或兼容 `.goo/plan.json`、`context_artifacts` 指向的 Goo-wiki/Markdown、Goo-wiki 摘要、thread logs 和上游产物路径。不要依赖当前 Claude Code 会话还记得之前讨论过什么。

如果存在多个未完成 thread 且无法唯一确定 current thread，必须先用 `AskUserQuestion` 复用 `id=thread_select` 模板让用户选择；用户未选择前不得随意续跑某个 plan。

恢复前必须扫描 `.goo/change-requests/*.json`。对当前 thread 的 `pending_model_update` 请求，把请求同步进 plan 或新增修改 step；对其他 thread 的请求，先用结构化选择让用户决定切换、复制或跳过。模型修改完成后必须增加审计 step，审计通过再把请求状态改为 `completed`；审计失败则改为 `needs_revision`。

恢复时默认先执行 context sync：检查 plan 生成后当前对话是否新增方案、约束、验收标准、用户偏好或 open question。若有增量，先把旧 `.goo/plan.json` 归档到 `.goo/plans/history/`，短内容写入 `context_digest.post_plan_updates`，长内容写入 Goo-wiki 项目路径 `wiki/projects/<project-slug>/context/*.md` 并追加到 `context_artifacts`；Goo-wiki 不可用时写入 `.goo/obsidian/<project-slug>/context/*.md`。只有新增内容与原 plan 冲突、扩大范围、改变验收标准或涉及危险操作时才询问用户确认；该询问必须优先使用结构化选项：`同步并继续执行`、`先修改 plan`、`停止并保留当前 plan`。

如果 `.goo/brainstorm.json` 或 `.goo/plan.json` 的 `review.status` 仍是 `pending_user_review`，恢复前必须先停下来让用户审阅和确认；不得把未确认草案自动归档或继续执行。

恢复执行一旦准备启动业务 step 调度，也必须先检查 `.goo/brainstorm.json`。如果该文件存在且 `archive` 缺失、`archive.status` 不是 `completed`，或归档路径不可验证，先派发 `recorder` 归档 brainstorm 候选 goals、推荐顺序、用户最终选择/合并依据、共同前置条件、ready checklist、wiki 证据和当前 plan 关联；归档完成并回写 `.goo/brainstorm.json.archive` 后，才能继续执行未完成 step。

## 恢复检测流程（按优先级）

对 plan.json 中每一个 step：

### 1. status = "completed" → 直接跳过

plan.json 已标记完成，无需额外检查。

### 2. status = "running" → 三重检测

```
heartbeat_at 距今 < 2 分钟？
  → YES: Agent 可能仍在运行。检查当前会话是否有对应后台任务
    → 有: 等待其完成
    → 无(跨会话恢复): 检查产物文件是否存在
      → 产物存在且非空: 标记为 completed，继续
      → 产物不存在: 重置为 pending，重新派发
  → NO(>= 2 分钟): Agent 已死亡
    → 检查产物文件是否存在
      → 产物存在且非空: 标记为 completed（agent 完成后来不及回写 plan.json）
      → 产物不存在: 重置为 pending，重新派发
```

### 3. status = "failed" → 判断是否关键路径

- 非关键路径（不阻塞其他 pending 步骤）→ 跳过
- 关键路径（阻塞后续步骤）→ 优先用 `AskUserQuestion` / 结构化选择 UI 询问用户是否重试、跳过继续或停止

### 4. status = "pending" → 正常执行

检查 depends_on 是否全部 completed，满足则加入当前执行轮。

关键路径失败提问必须优先使用 `AskUserQuestion` / 结构化选择 UI，并复用 `skills/auto-goo/references/interaction-templates.md` 中 `id=failed_step_action` 的 JSON 模板。如果用户通过 Other 输入替代处理方式，必须先解释影响并确认依赖后再继续。如果结构化选择 UI / AskUserQuestion 不可用、调用失败或按钮没有渲染，使用以下纯文本 fallback：

```text
关键路径步骤失败，会阻塞后续步骤。请选择处理方式：
1. 重试该步骤
2. 跳过并继续可执行的非依赖步骤
3. 停止并保留当前现场

这是 fallback；请回复 1/2/3，或直接回复“重试”/“跳过”/“停止”。
```

## 产物文件存在性检测

对每个 step 的 `output` 字段指定的路径，执行：

```bash
# 对于 .py 文件，还需检查是否有实质内容（非空、非纯注释）
test -f "<output_path>" && [ "$(wc -l < "<output_path>")" -gt 5 ]
```

产物文件存在 + 行数 > 5 → 视为步骤已完成（即使 plan.json 未更新）。

## 执行流程

1. 读取 `.goo/plan.json`
2. 默认执行 context sync：把 plan 后对话增量落到 `context_digest.post_plan_updates` 或 `context_artifacts`
3. 检查 `.goo/brainstorm.json` 是否已归档；未归档则先完成 brainstorm 归档并回写 `archive`
4. 对每个 step 按上述优先级判断真实状态
5. 更新 plan.json（修复僵尸状态为 completed 或 pending）
6. 找出所有 status=pending 且 depends_on 全部 completed 的步骤
7. 检查待执行步骤是否可仅凭 plan/Markdown/wiki 摘要执行；不合格则先补全 plan
8. 校验待执行步骤必须包含 `subagent`、`task_agent`、`depends_on`、`output` 和读写边界；缺失或不合法时先修复 plan，不由主 Agent 代执行
9. 检查 `available_skills`；缺失时可补为空数组，包含不存在或无关 skill 时先修正 plan
10. 为每个待执行 step 构造 Subagent prompt，包含 `available_skills` 作为 skill allowlist，并**必须包含 `references/execution-engine.md` 中对应类型的 Heartbeat 强制分段**
11. 恢复执行时先读当前 thread plan 顶层 `runtime.subagent_isolation`；如果已有 `mode` 且 `project_root` 与当前 AutoGoo 项目根一致，默认复用该缓存，不再重复检查或询问。缓存缺失、`project_root` 不匹配或用户明确切换执行目录时，用 `AskUserQuestion` 复用 `id=git_init_project` 模板询问是否启用 worktree 隔离。用户选择不启用时写 `mode="none"`、`project_root`、`decision="worktree_disabled"` 并继续，后续 Agent tool 省略 `isolation` 参数；如果省略 `isolation` 的实际派发仍报 `Failed to resolve base branch "HEAD"` / `git rev-parse failed`，说明当前 Claude Code Agent 包装层仍要求 Git HEAD，必须写入 `runtime.subagent_isolation.compatibility.agent_requires_git_head=true`，把当前 step 标记 `blocked` / `needs_user_approval`，并重新询问是否启用 worktree，不得重置 heartbeat 后反复重派，也不得创建 probe agent。用户选择启用时写 `mode="worktree"`，只检查当前项目根本身；不要设置 `GIT_DISCOVERY_ACROSS_FILESYSTEM`，不要向父目录、跨文件系统或备用路径寻找 Git root。若不是 Git repo，运行 `git init -b main`，不支持 `-b` 时初始化后立即 `git branch -M main`；若已有 Git 但没有 `HEAD`，复用当前仓库。随后先检查 `git status --short` 和敏感文件风险，确认安全后 `git add -A` 并提交 `chore: initialize repository for AutoGoo worktree isolation`。只有 `HEAD` 可解析后才给 Agent tool 传 `isolation: "worktree"`；启用后仍无 `HEAD` 时标记 workflow blocked，不降级普通派发，也不得循环 probe 或改从父级 Git root 派发。
12. 按 tier 分组，同 tier 内并行派发给对应 Subagent。派发每个 Subagent 前，主 Agent 必须先调用 `update-step.py --start --progress 5 --agent-id <agent>` 写入首个 `heartbeat_at`，再启动 Agent；Subagent 继续按 Heartbeat 强制分段写 15/50/85/complete。Agent 返回 `Done` 时，`0 tool uses` 只能作为可疑信号；文本型 step 可以无工具完成，但必须有结构化最终答复、step log、heartbeat 里程碑或声明产物之一。若 step 声明了 `output`/`outputs`，必须验证产物存在且满足 `validation` 后才能 completed；缺失时记录实际 isolation 参数、plan 隔离模式和缺失路径，标记 blocked/failed，不得当作完成或解锁下游。**每次 step 状态变更后立即调用 `goo-status.py --update-status`**。每次派发批次后、每轮 30s 心跳巡检后，以及任一 Agent 完成后，主 Agent 必须运行 `goo-status.py` 并把 RUNNING/告警摘要展示给用户，避免心跳只存在于 plan 文件里但前台不可见。
13. 按 AutoGoo 标准执行流程继续（Phase 2-4）

## 示例

```
/auto-goo:goo-continue
```

输出示例：
```
检测 plan.json (14 步):
  1. schemas.py        status=running, heartbeat=3min前 → 僵尸, 产物存在 → 标记 completed
  2. bbox_utils.py     status=running, heartbeat=3min前 → 僵尸, 产物存在 → 标记 completed
  3. constraints.py    status=running, heartbeat=3min前 → 僵尸, 产物存在 → 标记 completed
  4. annotation.py     status=running, heartbeat=3min前 → 僵尸, 产物不存在 → 重置 pending
  5. gen_p1.py         status=running, heartbeat=3min前 → 僵尸, 产物不存在 → 重置 pending
  ...

已修复 3 个僵尸状态，可恢复 4 个步骤
继续执行 tier 2 (步骤 4-7)...
```

## 备注

- 如果所有步骤已完成，提示"没有未完成的任务"
- 关键路径上的失败步骤必须优先用结构化选择 UI 询问是否重试、跳过继续或停止
- 恢复执行必须派发 Subagent；主 Agent 做状态修复、派发和审核。若 `subagent` 或 `task_agent` 不存在，先补 plan 或创建角色/任务画像，不由主 Agent 代执行
- 恢复执行必须尊重缓存的 Subagent worktree 配置：优先读取 `runtime.subagent_isolation.mode` 和 `project_root`；缓存存在且根目录一致时直接复用。缓存缺失、根目录不匹配或执行目录明确变更时才重新询问是否启用 worktree。值为 `worktree` 才给 Agent tool 传 `isolation: "worktree"`，值为 `none` 则省略 `isolation`。若 `mode=none` 仍触发 `Failed to resolve base branch "HEAD"`，立即记录 `compatibility.agent_requires_git_head=true` 并阻塞等待用户选择启用 worktree；不得向父目录寻找 Git root，也不得重复 probe。
- 恢复执行时使用 step 的 `available_skills` 作为 Subagent skill allowlist；缺失时先补为空数组
- 如果 `.goo/brainstorm.json` 或 `.goo/plan.json` 仍是待审草案，恢复执行前必须先展示摘要并优先用结构化选择 UI 让用户确认、修改或停止；确认后如果 brainstorm 未归档，再归档最终版 brainstorm，然后恢复业务 step
- `heartbeat_at` 为空且 status=running 的步骤：说明派发时写了 tier-X-start.json 但 agent 从未真正启动 → 直接重置为 pending
- Plan 顶层 `status`（`pending` → `running` → `blocked` → `completed`/`failed`）由 `goo-status.py --update-status` 自动计算更新，主 Agent 在每次 step 状态变更后必须调用
- Thread 状态由当前 plan 推导；每次 step 状态变更后同步 `.goo/threads/<thread_id>/thread.json` 和 `.goo/threads/index.json`
