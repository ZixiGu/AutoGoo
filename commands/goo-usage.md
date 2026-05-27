---
name: auto-goo:goo-usage
description: 显示 Claude Code token 和 usage 监控面板 — 多色可视化终端仪表盘
---

## 执行流程

加载此命令后，**先使用 AskUserQuestion 询问用户**：

- 问题: "How do you want to view the usage dashboard?"
- 选项 1: "Browser popup with auto-refresh" — 浏览器 HTML 仪表盘，自动刷新
- 选项 2: "Inline (interactive TUI)" — 当前终端内交互式 TUI

同时提示用户：脚本直跑可用 `cd <AutoGoo> && python3 skills/auto-goo/scripts/goo-usage.py --once`。

```bash
cd <AutoGoo> && python3 skills/auto-goo/scripts/goo-usage.py --once
```

### 选项 1: 浏览器 HTML 仪表盘

启动内建 HTTP 服务器，自动打开浏览器：

```bash
auto_goo_root="$(
  python3 - <<'PY' 2>/dev/null || true
import json
from pathlib import Path
registry = Path.home() / ".claude/plugins/installed_plugins.json"
if registry.exists():
    data = json.loads(registry.read_text(encoding="utf-8"))
    matches = []
    for key, entries in data.get("plugins", {}).items():
        if key.split("@", 1)[0] == "auto-goo":
            for entry in entries:
                path = Path(entry.get("installPath", "")).expanduser()
                if path.exists() and not (path / ".orphaned_at").exists():
                    matches.append((entry.get("lastUpdated", ""), str(path)))
    if matches:
        print(sorted(matches)[-1][1])
PY
)"
if [ -z "$auto_goo_root" ] || [ ! -f "$auto_goo_root/skills/auto-goo/scripts/goo-usage.py" ]; then
  echo "AutoGoo root not configured; install auto-goo so Claude Code records it in ~/.claude/plugins/installed_plugins.json" >&2
  exit 127
fi
python3 "$auto_goo_root/skills/auto-goo/scripts/goo-usage.py" --serve --interval 30
```

然后告知用户浏览器地址 `http://localhost:9876`。

如果 `--serve` 无法自动打开浏览器，手动用以下方式打开：
- VS Code: 用 Simple Browser 或内置浏览器打开 `http://localhost:9876`
- 终端: `xdg-open http://localhost:9876` 或 `open http://localhost:9876`

关闭方式：Ctrl+C 停止服务器，或关闭浏览器后 kill 后台进程。

### 选项 2: 内联 TUI

```bash
auto_goo_root="$(
  python3 - <<'PY' 2>/dev/null || true
import json
from pathlib import Path
registry = Path.home() / ".claude/plugins/installed_plugins.json"
if registry.exists():
    data = json.loads(registry.read_text(encoding="utf-8"))
    matches = []
    for key, entries in data.get("plugins", {}).items():
        if key.split("@", 1)[0] == "auto-goo":
            for entry in entries:
                path = Path(entry.get("installPath", "")).expanduser()
                if path.exists() and not (path / ".orphaned_at").exists():
                    matches.append((entry.get("lastUpdated", ""), str(path)))
    if matches:
        print(sorted(matches)[-1][1])
PY
)"
if [ -z "$auto_goo_root" ] || [ ! -f "$auto_goo_root/skills/auto-goo/scripts/goo-usage.py" ]; then
  echo "AutoGoo root not configured; install auto-goo so Claude Code records it in ~/.claude/plugins/installed_plugins.json" >&2
  exit 127
fi
python3 "$auto_goo_root/skills/auto-goo/scripts/goo-usage.py" --once
```

先让用户 approve 此命令。
`--once` 打印一次快照后退出，避免在 Claude Code 终端内启动交互式 TUI 导致的终端冲突。

## 仪表盘

4 个 Tab，默认打开 Overview：

| Tab | 快捷键 | 内容 |
|-----|--------|------|
| **Overview** | `1` | 今日总览：token 总量、消息数、会话数、token 组成（渐变色条）、模型分布、24 小时活动 sparkline、峰值时段、燃耗率、Top 项目 |
| **Projects** | `2` | 按项目拆分：渐变色条展示各项目 token 占比，消息数、会话数、cost |
| **Models** | `3` | 模型对比：每个模型的 token 量、消息数、效率(tok/msg)、I/O 比、缓存命中率、cost per message |
| **History** | `4` | 7 天趋势：sparkline 总览、逐日渐变色条、3 日趋势箭头（▲/▼ + 变化%）、7 日汇总 |

## 操作

- `←` `→` 或 `Tab` 切换 Tab
- `1` `2` `3` `4` 直接跳转
- `q` 退出
- `--once` 打印一次后退出（不进入 watch 模式）
- `--interval N` 设置刷新间隔（默认 30s）

## 内置价格

脚本内建常见 Claude 模型的官方定价（USD/1M tokens），无需手动传 `--price`：

- claude-opus-4-7: $15/$75 input/output
- claude-sonnet-4-6: $3/$15
- claude-haiku-4-5: $0.80/$4

传 `--no-builtin-pricing` 禁用内建价格；传 `--pricing FILE` 或 `--price MODEL=X,Y,Z` 使用自定义价格。

## 用户意图映射

历史/趋势 → `--tab history`，项目分布 → `--tab projects`，模型分析 → `--tab models`，只看一次 → `--once`。
