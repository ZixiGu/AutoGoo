---
name: auto-goo:goo-brainstorm
description: 基于 Goo-wiki 和当前项目上下文 brainstorm 候选 goals，不生成执行 DAG
---

# /auto-goo:goo-brainstorm — 先找目标，再计划

当用户还不知道明确目标，只想基于 Goo-wiki、项目历史或当前方向找下一步时，使用：

```text
/auto-goo:goo-brainstorm <方向/项目/问题>
```

## 行为

1. **Wiki 经验召回** — 按 AutoGoo 配置优先级解析 Goo-wiki，检索项目页、概念页、周报和 `log.md`。
2. **信号提取** — 提取未完成事项、反复问题、风险、近期计划、指标缺口、文档缺口、测试缺口、发布阻塞和可复用经验。
3. **前置条件识别** — 提炼所有候选目标共同需要的资源、权限、数据、环境、指标、人工决策和安全确认。
4. **候选目标生成** — 生成 3-7 个候选 goals，每个 goal 都要有依据、产物、验收标准、风险、第一步、前置要求和 ready checklist。
5. **推荐排序** — 给出 `recommended_goal_ids` 和排序理由。
6. **本地落盘** — 写入 `.goo/brainstorm.json`，标记为待用户审阅。
7. **等待用户审阅** — 展示候选 goals、推荐顺序、共同前置条件和关键风险，让用户选择、合并、改写或要求继续 brainstorm。必须优先用 `AskUserQuestion` / 结构化选择 UI 展示候选 goal 的 ID/编号和动作选项；不得在交互控件可用时只用普通文本要求用户手打回复。
8. **确认后归档** — 用户确认候选目标后，再将最终版本、选择依据、共同前置条件和关键 wiki 证据归档到 Goo-wiki 项目路径，并更新项目入口或 `log.md`；Goo-wiki 不可用时写入 `.goo/obsidian/<project-slug>/` fallback。不要在用户还可能修改候选目标时急着归档。

如果 `.goo/brainstorm.json` 已存在，写入新的 brainstorm 前，先把旧文件原样复制到 `.goo/brainstorms/history/brainstorm-<timestamp>.json`。该目录是本地 JSON 历史快照，和 Goo-wiki/fallback 知识归档不同；知识归档仍写入同一任务归档根的 `brainstorm/` 子目录。

## 输出要求

`.goo/brainstorm.json` 必须包含：

- `task`：用户给出的方向、项目或问题。
- `status: "pending_decision"`。
- `wiki_context.sources` 和 `wiki_context.signals`。
- `global_prerequisites[]`：开始任何候选 goal 前共同需要确认的条件，例如数据路径、账号权限、远程资源、评价指标、用户取舍、安全确认。
- `candidate_goals[]`，每项包含：
  - `id`
  - `name`
  - `why`
  - `expected_output`
  - `acceptance_criteria`
  - `evidence`
  - `risk`
  - `prerequisites`
  - `readiness_checklist`
  - `first_step`
  - `priority_hint`
- `recommended_goal_ids`
- `decision_needed: true`
- `review`：写 `{"status": "pending_user_review", "summary": "<给用户看的简短摘要>"}`；用户确认后改为 `confirmed`，用户要求修改时保持 `pending_user_review` 并记录修改要求。
- `next_action`：用户明确一个或多个 goals 后，调用 `/auto-goo:goo-plan <明确目标>`
- `archive`：归档目标、任务页路径或 fallback 路径、是否更新 `log.md`，以及 `status`。初次 brainstorm 生成后默认写 `{"status": "pending_user_review", ...}`，不要写成 `completed`。用户确认最终候选目标后再归档；如果暂时无法归档，写明 `status: "pending"` 或 `status: "failed"` 和原因，后续 `/auto-goo:goo-start` / `/auto-goo:goo-continue` 在执行 plan 前必须先补归档。
  - 默认归档到同一任务归档根的 `brainstorm/` 子目录，例如 `wiki/projects/<project-slug>/tasks/<YYYY-MM-DDTHH-MM-SS-task-slug>/brainstorm/`。
  - `archive.task_archive_root` 记录任务归档根；后续由该 brainstorm 生成的 `.goo/plan.json.archive.task_archive_root` 必须复用同一目录，并把正式计划写入 `plan/` 子目录。
  - fallback 时使用 `.goo/obsidian/<project-slug>/tasks/<task-slug>/brainstorm/`，并同样保留 `task_archive_root`。
  - 本地历史快照另存到 `.goo/brainstorms/history/`，不要和 Goo-wiki/fallback 归档路径混用。

## 审阅提问格式

展示候选目标后，必须优先用 `AskUserQuestion` / 结构化选择 UI 收尾，并复用 `skills/auto-goo/references/interaction-templates.md` 中 `id=brainstorm_review` 的 JSON 模板。动态 `<goal_id>` 必须替换为本次推荐候选的真实 ID；其他 goal、合并列表和修改要求通过 Other 输入，输入后必须校验或复述确认。选项至少包含：

- 选择推荐目标 `<goal_id>`
- 选择其他目标
- 合并多个目标
- 修改候选目标
- 继续 brainstorm

仅当交互控件不可用时，才使用纯文本 fallback：

```text
请选择下一步：
1. 选择推荐目标 <goal_id>
2. 选择其他目标（回复 goal ID，例如 g2）
3. 合并多个目标（回复例如：合并 g1,g3）
4. 修改候选目标（回复：修改: <你的要求>）
5. 继续 brainstorm

这是 fallback；也可以直接回复 goal ID、编号或上面的动作文本。
```

如果候选 goal 已经有稳定 `id`，优先展示和接受 `id`；没有时使用本次消息中的编号，并在写回 `.goo/brainstorm.json.review` 时记录用户选择来源。

### checklist 规则

- `prerequisites` 写“开工前必须具备什么”，例如数据、权限、配置、算力、依赖、指标定义、用户决策。
- `readiness_checklist` 写可逐项勾选的问题，使用短句，并尽量能通过文件、命令、wiki 页面或用户确认验证。
- 如果某个前置条件缺失但不阻塞 brainstorm，把它写入对应候选 goal 的 `risk` 和 `readiness_checklist`，不要假装已经满足。

## 边界

- 不写 `.goo/plan.json`。
- 不生成执行 DAG。
- 不派发 Subagent 执行。
- 不修改业务文件；用户确认前只允许写 `.goo/brainstorm.json`，不要写 Goo-wiki/fallback 归档笔记。
- 不运行实现、评测、训练、安装、远程或删除命令。

用户选定一个或多个 goals 后，再进入：

```text
/auto-goo:goo-plan <明确后的 goal 或 goal 列表>
```
