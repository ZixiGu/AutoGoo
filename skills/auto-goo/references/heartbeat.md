# Subagent Heartbeat 协议

## 为什么需要心跳

后台 Agent 随主会话死亡（`/exit` 或超时时所有 run_in_background agent 被 kill）。没有心跳就无法区分"agent 死了"和"agent 还在跑"。

## 规则

- Agent 启动后立即写第一次 `heartbeat_at` + `progress=5`
- 之后每 30 秒更新：`heartbeat_at` + `progress (0-100)`
- 进度估算：agent 在任务开头拆 3-5 个里程碑，每过一个里程碑更新进度
- 心跳通过 `update-step.py` 更新 plan.json，不要手写临时 JSON 修改代码

## 命令模板

将 `<id>` 和 `<0-100>` 替换为实际值：

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
if [ -z "$auto_goo_root" ] || [ ! -f "$auto_goo_root/skills/auto-goo/scripts/update-step.py" ]; then
  echo "AutoGoo root not configured; install auto-goo or enable a local directory marketplace in ~/.claude/settings.json" >&2
  exit 127
fi
python3 "$auto_goo_root/skills/auto-goo/scripts/update-step.py" --plan .goo/plan.json --step-id <id> --heartbeat --progress <0-100>
```

## 里程碑模板

通用里程碑（适用于大多数 agent）：

| 里程碑 | `--progress` | 时机 |
|--------|-------------|------|
| 启动 | `5` (`--start`) | 第一步，读输入之前 |
| 理解上下文 | `15` | 读完输入、wiki、上游产物后 |
| 核心过半 | `50` | 主要工作过半时 |
| 产物接近完成 | `85` | 写完输出、自查前 |
| 完成/失败 | `100` + `--complete` 或 `--fail` | 最终状态 |

**启动和完成必须分别用 `--start --progress 5` 和 `--complete`，中间里程碑用 `--heartbeat --progress <N>`。**

## 进度判断

| progress 状态 | 含义 |
|---------------|------|
| 0 | 刚启动，尚未开始实质工作 |
| 5-25 | 读输入、理解上下文阶段 |
| 30-70 | 核心实现阶段 |
| 75-95 | 收尾、自查、写日志 |
| 100 | 完成（与 status=completed 同步） |
| 停滞 >= 3 轮心跳（约 90s） | 可能卡住，发出警告 |

## 心跳判断（恢复时使用）

| heartbeat_at 状态 | 判断 |
|-------------------|------|
| 距今 < 2 分钟 | Agent 可能仍在运行（如果会话还在） |
| 距今 >= 2 分钟 | Agent 已死亡（僵尸进程），可重新派发 |
| 为空（从未启动） | 步骤从未被执行 |

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
