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
5. **审阅与归档闸门** — 一旦 plan 准备开始执行，先检查 `.goo/brainstorm.json` 和 `.cdgoo/plan.json` 的 `review.status`。如果仍是 `pending_user_review`，先让用户审阅和确认，不自动归档或执行。确认后，如果 brainstorm 存在且 `archive` 缺失、`archive.status` 不是 `completed`，或归档路径不可验证，必须先派发 `recorder` 归档最终版 brainstorm；归档完成并回写 `.goo/brainstorm.json.archive` 后，才能进入业务 step 调度
6. **执行前自检** — 确认每个待执行 step 不依赖主会话隐含上下文，只依赖 plan、Markdown/context artifact、wiki 摘要和上游产物；检查每个 step 的 `subagent` 是否合法，并检查 `available_skills` 是否只包含本步骤需要且实际可用的 skill；不合法时先补 plan 或创建角色，不直接降级主 Agent 执行
7. **执行** — 按轮次并行/串行分发 Subagent；除生成 plan 本身外，主 Agent 不得直接代做 `research` / `exec` / `optimize` / `eval` / `review` / `audit` / `archive` 步骤。**每个 Subagent prompt 必须包含 `references/execution-engine.md` 中对应的 Heartbeat 强制分段**，否则 Subagent 不更新 `heartbeat_at`，会被误判为僵尸进程。**每次 step 状态变更后，必须立即调用 `goo-status.py --update-status` 更新 plan 顶层 `status`、`started_at`、`completed_at`**，确保 plan 顶层状态与实际 step 状态一致
8. **优化**（如需要）— 指标搜索 → Baseline → 优化 → 评测对比
9. **归档** — 执行记录和新增经验写入 Goo-wiki

## 参数

任务描述支持自然语言，不限格式。AutoGoo 会自动解析目标、拆解步骤、标注依赖。

如果当前目录已经存在 `.goo/plan.json`，且用户没有提供新的任务描述，优先从当前 plan 执行。执行前默认做一次 context sync：若当前对话在 plan 生成后新增了方案、取舍、约束、验收标准、用户偏好或 open question，先把旧 plan 复制到 `.goo/plans/history/`，再把短内容写入 `context_digest.post_plan_updates`，长内容写入 Goo-wiki/Markdown 并追加到 `context_artifacts` 后执行。只有新增内容与原 plan 冲突、扩大范围、改变验收标准或涉及危险操作时才询问用户确认。

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
- 执行阶段必须使用 plan step 中声明的 `subagent`；若 `subagent` 缺失或不合法，先补 plan 或创建角色，不由主 Agent 直接代执行
- 执行阶段把 plan step 中的 `available_skills` 作为 Subagent prompt 的 skill allowlist；没有额外 skill 时传空数组，不把全部 skill 默认塞给 Subagent
- 优化迭代默认最多 3 轮
- 日志保存在 `.goo/logs/`
- Plan 顶层 `status`（`pending` → `running` → `completed`/`failed`）由 `goo-status.py --update-status` 自动计算更新，主 Agent 在每次 step 状态变更后必须调用
