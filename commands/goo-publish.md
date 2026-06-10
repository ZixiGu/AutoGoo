---
name: auto-goo:goo-publish
description: 将 AutoGoo 工作流状态发布为静态 HTML 站点 — 包含活动热力图、token 消耗、头脑风暴、计划、DAG、运行状态和产物索引
---

# /auto-goo:goo-publish — HTML 工作流发布

把当前项目 `.goo/` 中的 brainstorm、plan、history、logs、artifacts、fallback 归档索引成一个可浏览的多页 HTML 站点，并默认启动本地 server、尝试弹出浏览器。无需先运行 `goo-init`，也无需创建或修改 `.goo/config.json`。默认同时支持 localhost 和远程机器 IP 访问：

```text
http://127.0.0.1:9877/
http://<server-ip>:9877/
```

默认静态站点输出：

```text
.goo/site/index.html
```

唯一运行时页面外壳模板位于：

```text
skills/auto-goo/templates/publish/workflow-shell.html
```

正式发布主题位于 `skills/auto-goo/templates/publish/workflow-theme.css`。`goo-publish.py` 每次构建都必须把它复制为站点目录中的 `workflow-theme.css`，由运行时 shell 自动引用；不得依赖发布后手工注入 CSS 或 `/tmp` 中的概念稿样式。

默认生成 `index.html`、`threads.html`、`plan.html`、`activity.html`、`brainstorm.html`、`status.html`、`agents.html`、`artifacts.html` 和 `requests.html`。左侧工作区导航展示总览、Threads、头脑风暴、计划、运行状态、代理执行、产物归档和修改请求；总览包含 Token 活动热力图和文本型工作流活动，悬浮格子显示该日或周期的消耗明细，点击或聚焦格子会在下方说明所选时间段实际完成的工作。活动页会把当前项目 Claude Code usage 日志中的 token 消耗按 turn/session 聚合进时间线，列表显示对应用户任务摘要，点击记录后展开完整用户任务原文和使用详情；不发布 assistant 回复或完整对话正文。

`goo-publish --serve` 支持在 Web 上提交修改请求，但只写入 `.goo/change-requests/*.json`，不会直接改业务文件、plan、brainstorm 或 Goo-wiki。后续由 AutoGoo 主 Agent 读取请求、同步到 thread plan 或 context artifact，再派发模型修改并审计。

`goo-publish.py` 必须以 `workflow-shell.html` 为唯一运行时页面外壳，并使用 `workflow-theme.css` 作为唯一正式视觉主题：shell 维护 sidebar、工作区导航容器、页头、主题按钮和主题引用；主题文件维护紧凑工作台布局、浅色/暗色变量、页面语义色、指标卡配色和响应式覆盖。脚本只填充标题、活动导航链接、正文、输出路径和交互脚本，并复制主题文件。其余 `workflow-*.html` 是内容与视觉参考页，不得作为第二套运行时 shell。

桌面端固定左侧导航，并把页面标题、生成时间、实时状态和主题按钮组成吸顶页头；导航区域可独立滚动。移动端恢复自然文档流，避免固定区域遮挡正文。

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

- `index.html`：总览、任务流程和最近执行记录。
- `threads.html`：所有 thread 的 id、状态、plan 路径、logs 路径和进度。
- `status.html`：当前计划运行状态和步骤进度。
- `agents.html`：本次代理执行、状态、耗时、产出和日志。
- `plan.html`：当前计划、目标、计划步骤、任务流程图和 DAG。
- `activity.html`：工作流活动和 token 使用记录。
- `brainstorm.html`：当前或最近一次头脑风暴。
- `artifacts.html`：最近产物索引。
- `requests.html`：用户提交的修改请求队列；字段包含 `thread_id`、`target`、`title`、`request` 和 `status=pending_model_update`。

## 规则

- 只读取 `.goo/`；已有项目配置时仅把发布字段作为可选覆盖，不修改 plan、brainstorm、logs 或 Goo-wiki 正文。
- 输出默认是静态多页 HTML，无需 `.goo/config.json`，同时可通过内建本地 server 预览。
- 内建 server 默认绑定 `0.0.0.0`，适配 VS Code Remote / SSH 场景；浏览器无法自动弹出时，把脚本打印的 URL 告诉用户。
- 默认请求不重新扫描 `.goo/`；需要实时重建时使用 `--live`，大项目可能变慢。
- 如果 `.goo/plan.json` 或 `.goo/brainstorm.json` 不存在，页面显示空状态，不报错。
- 如果用户要求公开发布到远端或 GitHub Pages，必须先确认目标分支、目录和是否允许提交/推送，并优先用 `AskUserQuestion` / 结构化选择 UI 收尾，复用 `skills/auto-goo/references/interaction-templates.md` 中 `id=publish_public_confirm` 的 JSON 模板。目标分支、目录和任何推送要求必须通过 Other 输入或后续确认问题收集，并在提交/推送前再次说明风险和范围。选项为：

  - 只生成本地 HTML，不提交不推送
  - 提交并推送到指定分支/目录
  - 取消发布

  仅当交互控件不可用时，才使用纯文本 fallback：

```text
这是 fallback：结构化选择 UI 不可用。
公开发布会写入远端或 GitHub Pages。请选择处理方式：
1. 只生成本地 HTML，不提交不推送
2. 提交并推送到指定分支/目录
3. 取消发布

请回复 1/2/3，并确认目标分支和目录。
```
