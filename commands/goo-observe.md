---
name: auto-goo:goo-observe
description: 观察 AutoGoo 后台 subagent、shell 日志和 Agent View 使用入口
---

# /auto-goo:goo-observe — 后台观察

用于执行期间快速观察三类状态：

1. Claude Code Agent View 中的后台 session / shell job。
2. AutoGoo 当前 thread 的 running / blocked / failed step。
3. 当前 step log 和 shell 长任务日志路径。

## 行为

必须优先运行插件脚本，而不是手写临时检查：

```bash
python3 "$auto_goo_root/skills/auto-goo/scripts/goo-observe.py" --root .
```

如果需要给 Web 或其他工具消费，使用：

```bash
python3 "$auto_goo_root/skills/auto-goo/scripts/goo-observe.py" --root . --json
```

## 输出要求

- 顶部展示当前 root、thread、plan、logs、shell logs 和 Claude Code 版本。
- 展示 Agent View 入口：`claude agents`，并说明 `Space` peek、`Enter/Right` attach。
- 明确说明 Agent View 只能看后台 Claude session / shell job；AutoGoo 内部 subagent 不会作为独立 session 行出现，细节看当前 thread plan 和 step logs。
- RUNNING 区展示 step id、名称、progress、heartbeat age、subagent/task_agent、log path 和最近日志尾部。
- BLOCKED / FAILED 区展示需要处理的 step 和日志路径。
- Shell Tracking 区给出推荐模板：`mkdir -p <shell-log-dir> && <command> 2>&1 | tee <shell-log-dir>/<name>-$(date +%Y%m%d-%H%M%S).log`。

## 备注

- 不启动或终止后台任务。
- 不读取 secrets。
- 不替代 `/auto-goo:goo-status`；它是观察入口，`goo-status` 是状态仪表盘。
- `goo-publish` 的 `observe.html` 必须复用同一脚本生成的数据模型。
