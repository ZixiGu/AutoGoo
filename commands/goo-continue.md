---
name: auto-goo:goo-continue
description: 从中断处继续执行 AutoGoo 任务 — 读取 .goo/plan.json 的三重检测（状态+文件+心跳）恢复未完成步骤
---

# /auto-goo:goo-continue — 继续执行任务

从上次中断处继续执行。读取 `.goo/plan.json`，用三重检测判断每步真实状态，从未完成的步骤开始按 DAG 拓扑重新执行。

`goo-continue` 的执行依据只能是当前 `.goo/plan.json`、`context_artifacts` 指向的 Goo-wiki/Markdown、Goo-wiki 摘要、`.goo/logs/` 和上游产物路径。不要依赖当前 Claude Code 会话还记得之前讨论过什么。

恢复时默认先执行 context sync：检查 plan 生成后当前对话是否新增方案、约束、验收标准、用户偏好或 open question。若有增量，先把旧 `.goo/plan.json` 归档到 `.goo/plans/history/`，短内容写入 `context_digest.post_plan_updates`，长内容写入 Goo-wiki 项目路径 `wiki/projects/<project-slug>/context/*.md` 并追加到 `context_artifacts`；Goo-wiki 不可用时写入 `.goo/obsidian/<project-slug>/context/*.md`。只有新增内容与原 plan 冲突、扩大范围、改变验收标准或涉及危险操作时才询问用户确认。

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
- 关键路径（阻塞后续步骤）→ 询问用户是否重试

### 4. status = "pending" → 正常执行

检查 depends_on 是否全部 completed，满足则加入当前执行轮。

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
8. 校验待执行步骤必须包含 `subagent`、`depends_on`、`output` 和读写边界；缺失或不合法时先修复 plan，不由主 Agent 代执行
9. 检查 `available_skills`；缺失时可补为空数组，包含不存在或无关 skill 时先修正 plan
10. 为每个待执行 step 构造 Subagent prompt，包含 `available_skills` 作为 skill allowlist，并**必须包含 `references/execution-engine.md` 中对应类型的 Heartbeat 强制分段**
11. 按 tier 分组，同 tier 内并行派发给对应 Subagent。**每次 step 状态变更后立即调用 `goo-status.py --update-status`**
12. 按 AutoGoo 标准执行流程继续（Phase 2-4）

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
- 关键路径上的失败步骤会询问是否跳过继续
- 恢复执行必须派发 Subagent；主 Agent 做状态修复、派发和审核。若 Subagent 角色不存在，先补 plan 或创建角色，不由主 Agent 代执行
- 恢复执行时使用 step 的 `available_skills` 作为 Subagent skill allowlist；缺失时先补为空数组
- 如果 `.goo/brainstorm.json` 或 `.goo/plan.json` 仍是待审草案，恢复执行前必须先让用户确认；确认后如果 brainstorm 未归档，再归档最终版 brainstorm，然后恢复业务 step
- `heartbeat_at` 为空且 status=running 的步骤：说明派发时写了 tier-X-start.json 但 agent 从未真正启动 → 直接重置为 pending
- Plan 顶层 `status`（`pending` → `running` → `completed`/`failed`）由 `goo-status.py --update-status` 自动计算更新，主 Agent 在每次 step 状态变更后必须调用
