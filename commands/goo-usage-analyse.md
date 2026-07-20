---
name: auto-goo:goo-usage-analyse
description: 分析 Claude Code usage 与 Goo-wiki 项目知识，找出可落地的 token 开销节省方式
---

# /auto-goo:goo-usage-analyse — 基于 Wiki 的 Token 降本分析

当用户想知道“哪个项目最耗 token、为什么耗、怎么省”时，使用：

```text
/auto-goo:goo-usage-analyse [项目/时间范围/问题]
```

## 交互提问

收到 `/auto-goo:goo-usage-analyse` 后，不要直接运行全量分析，必须先通过交互提问确认分析范围。所有交互问题必须使用 `AskUserQuestion` / 结构化选择 UI 渲染可点击选项；不得只输出标题后等待用户，也不得要求用户手打编号。

1. 第一个问题——分析范围：
   - header: 分析范围
   - question: 请选择本次 token 降本分析的范围。
   - options:
     - label: 全部项目 (Recommended)
       description: 扫描所有项目的 usage 数据，找出整体可优化点。
     - label: 指定项目
       description: 通过 Other 输入项目名或路径，聚焦单个高耗项目。
     - label: 近 N 天
       description: 通过 Other 输入天数（如 7、30），分析近期趋势。

如果结构化选择 UI / AskUserQuestion 不可用、调用失败或按钮没有渲染，使用以下纯文本 fallback：

```
请选择分析范围：
1. 全部项目 (默认)
2. 指定项目
3. 近 N 天
```

## 行为

1. 通过交互提问确认分析范围（见上方）。
2. **Usage 快照** — 调用 `skills/auto-goo/scripts/goo-usage.py` 获取项目、模型、时间段和 token 类型分布。默认先用 `--once --no-color`，需要趋势时再读取 `daily` 或 `monthly` 聚合。
2. **Wiki 召回** — 按 AutoGoo-Plugin 配置优先级解析 Goo-wiki，优先用 `scripts/wiki-graph-assist.py` 检索高耗项目相关的项目页、`log.md`、日报/周报、问题页、流程规范和历史任务页。
3. **成本归因** — 把 usage 热点和 wiki 信号对齐，识别导致 token 消耗的模式，例如反复读大文档、缺少项目入口页、plan 上下文未沉淀、subagent 输入过宽、重复排查同类问题、日报/归档缺失、模型选择不匹配、cache 命中低。
4. **节省方案生成** — 输出按优先级排序的节省机会，每项包含依据、预计节省机制、改动位置、验证方式和风险。
5. **本地落盘** — 写入 `.goo/goo-usage-analyse.json`，并生成 `.goo/reports/goo-usage-analyse-<timestamp>.md`。
6. **Wiki 归档** — 把 Markdown 报告归档到 Goo-wiki 项目路径，并更新项目入口或 `log.md`；Goo-wiki 不可用时写入 `.goo/obsidian/<project-slug>/` fallback。
7. **不自动改业务文件** — 默认只给诊断和候选改动；只有用户明确要求“执行/修复/写入规则”时，才进入 `/auto-goo:goo-plan` 或 `/auto-goo:goo-start`。

## 推荐命令

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
        if key.split("@", 1)[0] != "autogoo-plugin":
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
            if plugin != "autogoo-plugin":
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
if [ -z "$auto_goo_root" ] || [ ! -f "$auto_goo_root/skills/auto-goo/scripts/goo-usage.py" ] || [ ! -f "$auto_goo_root/skills/auto-goo/scripts/wiki-graph-assist.py" ]; then
  echo "AutoGoo-Plugin root not configured; install autogoo-plugin or enable a local directory marketplace in ~/.claude/settings.json" >&2
  exit 127
fi
python3 "$auto_goo_root/skills/auto-goo/scripts/goo-usage.py" --once --no-color
python3 "$auto_goo_root/skills/auto-goo/scripts/wiki-graph-assist.py" --query "<高耗项目或关键词>"
```

如果用户指定时间范围，先让 `goo-usage.py` 用对应参数生成快照；如果脚本暂不支持该范围，退化为读取最近可用的 daily/monthly 聚合，并在报告里标注限制。

## 输出要求

`.goo/goo-usage-analyse.json` 应包含：

- `task`：用户给出的项目、时间范围或问题。
- `usage_snapshot`：总 token、Top 项目、Top 模型、输入/输出/cache 组成、峰值时间段。
- `wiki_context.sources`：用于归因的 Goo-wiki 页面、`log.md`、日报/周报或 fallback 笔记。
- `cost_drivers[]`：高耗原因，每项包含 `driver`、`evidence`、`related_projects`、`token_signal`、`wiki_signal`。
- `saving_opportunities[]`：节省机会，每项包含 `id`、`priority`、`action`、`why`、`expected_saving_mechanism`、`where_to_change`、`validation`、`risk`。
- `candidate_workflow_rules[]`：可沉淀进 AutoGoo-Plugin/项目 wiki 的默认规则，例如“长文档先 graph packet 再全文阅读”、“重复问题先查问题页”、“执行前同步 context_artifacts”。
- `archive`：归档目标、任务页路径或 fallback 路径、是否更新 `log.md`。
- `next_actions[]`：建议用户选择的后续动作，可指向 `/auto-goo:goo-plan <节省方案>`。

## 分析边界

- 不把 token 降本只理解成“少说话”；优先找流程层面的复用、召回、摘要、缓存、模型路由和 subagent 输入边界。
- 不读取整个 wiki。先用 `wiki-graph-assist.py` 生成紧凑 graph packet，只有证据不足时才读取少量完整 Markdown。
- 不输出敏感路径中的密钥、令牌、凭据。
- 不自动修改 `CLAUDE.md` 或业务文件；Goo-wiki 只写入本次分析报告、相关链接和 `log.md` 活动记录。
- 不删除 usage 日志、wiki 笔记或 `.goo` 产物。
