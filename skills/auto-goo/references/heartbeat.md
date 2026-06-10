# Subagent Heartbeat 协议

## 为什么需要心跳

后台 Agent 随主会话死亡（`/exit` 或超时时所有 run_in_background agent 被 kill）。没有心跳就无法区分"agent 死了"和"agent 还在跑"。

## 规则

- 主 Agent 派发 Agent 前先写第一次 `heartbeat_at` + `progress=5`，命令为 `update-step.py --start --progress 5 --agent-id <agent>`
- Subagent 启动后不要重复 `--start`；之后按里程碑更新 `heartbeat_at` + `progress (0-100)`
- 进度估算：agent 在任务开头拆 3-5 个里程碑，每过一个里程碑更新进度
- 心跳通过 `skills/auto-goo/scripts/resolve-root.sh` 调用 `update-step.py` 更新当前 thread plan，不要手写临时 JSON 修改代码，也不要在命令文档里内联 root 解析 heredoc。
- `update-step.py` 会自动创建并追加当前 thread 的 `logs/{timestamp}_step-{id}_{name}.md`，并把 `log_path` 写回当前 step
- 心跳必须前台可见：主 Agent 每次派发批次后、每轮 30s 巡检后、任一 Agent 完成后都运行 `goo-status.py`，展示 RUNNING/告警摘要

## 命令模板

派发前首个 heartbeat 由主 Agent 写入：

```bash
bash "$auto_goo_root/skills/auto-goo/scripts/resolve-root.sh" \
  --plan .goo/threads/<thread_id>/plan.json \
  --step-id <id> \
  --start \
  --progress 5 \
  --agent-id <agent>
```

后续里程碑将 `<id>` 和 `<0-100>` 替换为实际值：

```bash
bash "$auto_goo_root/skills/auto-goo/scripts/resolve-root.sh" \
  --plan .goo/threads/<thread_id>/plan.json \
  --step-id <id> \
  --heartbeat \
  --progress <0-100> \
  --note "<短进展>"
```

上面的 `auto_goo_root` 必须由主 Agent 在派发前通过 Claude Code 安装记录或本地 directory marketplace 解析并注入；Subagent 不要自己扫描当前目录或猜 checkout 路径。如果 prompt 中没有已解析的 `auto_goo_root`，必须先报告 blocked，而不是手写一段新的 root 解析代码。

## 里程碑模板

通用里程碑（适用于大多数 agent）：

| 里程碑 | `--progress` | 时机 |
|--------|-------------|------|
| 派发前启动 | `5` (`--start`) | 主 Agent 在启动 Agent 前写入；Subagent 发现缺失时才补救 |
| 理解上下文 | `15` | 读完输入、wiki、上游产物后 |
| 核心过半 | `50` | 主要工作过半时 |
| 产物接近完成 | `85` | 写完输出、自查前 |
| 完成/失败 | `100` + `--complete` 或 `--fail` | 最终状态 |

**主 Agent 已在派发前用 `--start --progress 5` 写入启动心跳。Subagent 不要重复调用 `--start`；只有发现当前 step 仍不是 running 或没有 `heartbeat_at` 时，才用 `--start --progress 5` 补救。中间里程碑用 `--heartbeat --progress <N>`，完成用 `--complete`。** 需要记录关键决策、产物路径或耗时时，加 `--note "<短进展>"`；不要另写一套临时日志创建逻辑。

## 进度判断

| progress 状态 | 含义 |
|---------------|------|
| 0 | 刚启动，尚未开始实质工作 |
| 5 | 主 Agent 已派发，Agent 可能刚启动 |
| 15-25 | 读输入、理解上下文阶段 |
| 30-70 | 核心实现阶段 |
| 75-95 | 收尾、自查、写日志 |
| 100 | 完成（与 status=completed 同步） |
| 停滞 >= 3 轮心跳（约 90s） | 可能卡住，发出警告 |

## 心跳判断（跨会话恢复时使用）

| heartbeat_at 状态 | 判断 |
|-------------------|------|
| 距今 < 2 分钟 | Agent 可能仍在运行（如果会话还在） |
| 距今 >= 2 分钟 | Agent 已死亡（僵尸进程），可重新派发 |
| 为空（从未启动） | 步骤从未被执行 |

这 2 分钟判断只用于 `/auto-goo:goo-continue` 的跨会话恢复。正常执行中的失败超时使用 `heartbeat_timeout_min`，默认 15 分钟；不要把运行中超过 2 分钟未更新心跳直接标记为 failed。

## 超时配置

默认心跳超时 15 分钟。可在 plan.json 顶层自定义：

```json
{
  "task": "...",
  "heartbeat_timeout_min": 20,
  "steps": [...]
}
```

主 Agent 每 30s 巡检一次 running agent，超过 `heartbeat_timeout_min` 分钟无心跳更新则标记 `failed` 并释放槽位。建议范围 10-30 分钟；太短容易误杀长时间计算任务，太长会延迟失败恢复。
