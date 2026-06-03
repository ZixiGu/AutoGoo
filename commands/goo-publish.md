---
name: auto-goo:goo-publish
description: 将 AutoGoo 工作流状态发布为静态 HTML 站点 — 包含 activity 热力图、token 消耗、brainstorm、plan、DAG、运行状态和产物索引
---

# /auto-goo:goo-publish — HTML 工作流发布

把当前项目 `.goo/` 中的 brainstorm、plan、history、logs、artifacts、fallback 归档索引成一个可浏览的单页 HTML 站点，并默认启动本地 server、尝试弹出浏览器。默认同时支持 localhost 和远程机器 IP 访问：

```text
http://127.0.0.1:9877/
http://<server-ip>:9877/
```

默认静态站点输出：

```text
.goo/site/index.html
```

publish 页面模板位于：

```text
skills/auto-goo/templates/publish/workflow-*.html
```

默认内容完整保留在 `index.html`，左侧工作区导航按模板展示总览、头脑风暴、计划、运行状态、子代理和产物归档；Overview 包含 Token Activity 热力图，可切换 Daily、Weekly 和 Cumulative。Activity 会把当前项目 Claude Code usage 日志中的 token 消耗按 turn/session 聚合进时间线，只显示 token、模型和记录数，不显示对话正文。需要拆分页面时，把 `.goo/config.json` 里的 `publish.split_pages` 设置为 `true`。

`goo-publish.py` 必须以 `skills/auto-goo/templates/publish/workflow-*.html` 为页面外壳和视觉契约来源：生成 HTML 时复用模板的 sidebar、工作区导航、topbar、主题切换、基础 CSS token、卡片/表格/详情块样式。脚本只负责把 `.goo/` 的实时数据填入模板风格的内容区，不得另起一套独立 UI。

必须优先运行插件脚本，不要手写临时 HTML：

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
if [ -z "$auto_goo_root" ] || [ ! -f "$auto_goo_root/skills/auto-goo/scripts/goo-publish.py" ]; then
  echo "AutoGoo root not configured; install auto-goo or enable a local directory marketplace in ~/.claude/settings.json" >&2
  exit 127
fi
python3 "$auto_goo_root/skills/auto-goo/scripts/goo-publish.py" --root . --output .goo/site/index.html --serve --host 0.0.0.0 --port 9877
```

启动后告诉用户浏览器地址和静态文件路径：

```text
http://127.0.0.1:9877/
http://<server-ip>:9877/
.goo/site/index.html
```

如果 `9877` 被占用，脚本会自动尝试后续端口，并在输出中打印实际地址。server 默认直接读取已生成的 `.goo/site/index.html`，打开页面很快；需要每次刷新都重新扫描 `.goo/` 时再加 `--live`。

## 发布内容

- `index.html`：默认单页首页，Overview 显示整体概述，顶部 tabs 切换到 Status、Plan、Brainstorm、Activity、Subagents 和 Artifacts；内容仍都保留在同一个 HTML 中。
- 配置 `publish.split_pages=true` 时，额外拆出 `plan.html`、`activity.html`、`brainstorm.html` 和 `artifacts.html`。

## 规则

- 只读取 `.goo/` 和项目配置，不修改 plan、brainstorm、logs 或 Goo-wiki 正文。
- 输出默认是静态单页 HTML，内容完整保留在 `index.html`，同时可通过内建本地 server 预览。
- 内建 server 默认绑定 `0.0.0.0`，适配 VS Code Remote / SSH 场景；浏览器无法自动弹出时，把脚本打印的 URL 告诉用户。
- 默认请求不重新扫描 `.goo/`；需要实时重建时使用 `--live`，大项目可能变慢。
- 如果 `.goo/plan.json` 或 `.goo/brainstorm.json` 不存在，页面显示空状态，不报错。
- 如果用户要求公开发布到远端或 GitHub Pages，必须先确认目标分支、目录和是否允许提交/推送，并优先用 `AskUserQuestion` / 结构化选择 UI 收尾，选项为：

  - 只生成本地 HTML，不提交不推送
  - 提交并推送到指定分支/目录
  - 取消发布

  仅当交互控件不可用时，才使用纯文本 fallback：

```text
公开发布会写入远端或 GitHub Pages。请选择处理方式：
1. 只生成本地 HTML，不提交不推送
2. 提交并推送到指定分支/目录
3. 取消发布

请回复 1/2/3，并确认目标分支和目录。
```
