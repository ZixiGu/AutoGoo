# AutoGoo 环境设置

## Goo-wiki Obsidian Vault

Goo-wiki 是归档笔记的目标 Obsidian vault。插件在运行时通过文件存在性检测 vault 是否可用。

**非 Git 项目支持**：AutoGoo 完全支持非 Git 项目。所有 Git 相关功能（如记录 remote 地址）都是可选的，仅在项目是 Git repo 时启用。非 Git 项目不会收到任何 Git 相关的错误或警告。

**推荐初始化命令**：

```text
/auto-goo:goo-init
```

该命令支持用户级和项目级配置：

- `/auto-goo:goo-init --user` → `~/.auto-goo/config.json`
- `/auto-goo:goo-init --project` → `.goo/config.json`；自动创建或复用 Goo-wiki 与 `wiki/projects/<project-slug>/` 项目归档根目录，并询问是否更新项目 `CLAUDE.md` 的归档原则段落

初始化采用主 Agent 交互模式：主 Agent 先通过对话确认作用域、wiki 路径、覆盖风险和项目 `CLAUDE.md` 更新意愿，再调用脚本落盘。底层写入仍由初始化脚本完成：

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
if [ -z "$auto_goo_root" ] || [ ! -f "$auto_goo_root/skills/auto-goo/scripts/goo-init.sh" ]; then
  echo "AutoGoo root not configured; install auto-goo or enable a local directory marketplace in ~/.claude/settings.json" >&2
  exit 127
fi
bash "$auto_goo_root/skills/auto-goo/scripts/goo-init.sh"
```

主 Agent 应优先自己提问，而不是要求用户进入 Bash 交互。必须先问用户作用域和 wiki 路径，并在问题中展示默认路径 `~/workspace/Goo-wiki`；用户不输入路径时使用默认路径。随后显式传入 `--user/--project` 与 `--wiki-dir <路径>`；不得默认写入项目配置，也不得在未展示默认路径的情况下静默使用默认 wiki 路径。

如果用户确认或输入的 Goo-wiki 路径不存在，初始化脚本必须自动创建该目录，并补齐 `CLAUDE.md`、`log.md`、`wiki/projects/`、`wiki/concepts/`、`wiki/questions/`、`journal/daily/`、`journal/weekly/` 基础结构。路径不存在不是 fallback 条件；只有创建失败、权限不足或后续归档时 wiki 不可写，才使用 `.goo/obsidian/` fallback。

预检查只能作为交互辅助，不得打断初始化。检查现有 `.goo/config.json`、`.goo/`、git remote、wiki 文件等状态时，每个可能失败的命令都必须独立容错，例如 `ls .goo/config.json 2>/dev/null || true`、`git remote -v 2>/dev/null || true`。如果可选探测失败，只提示"未检测到/暂不可用"，继续询问用户。

**路径解析优先级**：

1. 环境变量 `AUTO_GOO_WIKI_DIR`
2. 当前项目 `.goo/config.json` 中的 `wiki_dir`
3. 用户级 `~/.auto-goo/config.json` 中的 `wiki_dir`
4. 默认路径 `~/workspace/Goo-wiki`
5. fallback 归档目录 `.goo/obsidian/`

**默认检测路径**：

```
~/workspace/Goo-wiki/CLAUDE.md
```

各项目通过 `/auto-goo:goo-init` 创建或检测 vault。vault 可用时归档到 `Goo-wiki/wiki/`，后续运行时如果 wiki 不可用才降级为 `.goo/obsidian/` fallback。

## 项目归档根路径

项目级初始化使用 Goo-wiki 时，AutoGoo 会创建或复用项目归档根目录：

```text
<wiki_dir>/wiki/projects/<project-slug>/
```

`project-slug` 默认由项目根目录名生成，也可以通过 `--project-slug <slug>` 指定。项目 `.goo/config.json` 会记录：

- `archive.project_slug`
- `archive.project_dir`，例如 `wiki/projects/<project-slug>`
- `archive.fallback_project_dir`，例如 `.goo/obsidian/<project-slug>`
- `archive.git_remote_url`（仅当项目是 Git repo 且能读取 remote 时）

如果当前项目是 Git repo，初始化时还会读取 `origin` remote（没有 origin 时读取第一个 remote），并将地址写入 `<wiki_dir>/wiki/projects/<project-slug>/index.md` 的 `AUTO-GOO-PROJECT-META` marker 块。该信息用于后续任务归档、迁移、复现和项目溯源；Recorder 写项目页或任务总览时也应保留该 git 地址。

Recorder 和归档步骤应优先写入 `archive.project_dir`，Goo-wiki 不可用时再写入 `archive.fallback_project_dir`。

## 项目 CLAUDE.md 归档原则

项目级初始化使用 Goo-wiki 时，AutoGoo 会询问用户是否在项目根目录 `CLAUDE.md` 中追加或更新由 `AUTO-GOO-WIKI-ARCHIVE` marker 包裹的段落。该段落要求：

- 规划前先从 Goo-wiki 召回相关项目经验、概念页、周报和 `log.md`
- `goo-plan` 的 `.goo/plan.json` 最后保留 `归档到 Goo-wiki` 步骤
- 执行后归档目标、计划、证据、产物路径、验证结果、决策、问题处理和可复用经验
- 任何产生可复用内容的命令最终都必须归档到 Goo-wiki 或 `.goo/obsidian/` fallback；不得只写 `.goo/*.json` 或只在聊天中展示。适用内容包括 usage/token 降本分析、日报/周报、改进建议、benchmark 指标和执行经验。brainstorm 候选目标与 plan 摘要必须先给用户审阅，确认后或进入执行前再归档最终版
- 日报/周报请求通过 `/auto-goo:goo-daily-report` 沉淀到 Goo-wiki `journal/daily/` 并更新 `log.md`；同日日报已存在时只追加新增内容，不整体覆盖已有人工整理
- 如果项目是 Git repo，将 git remote 地址写入 Goo-wiki 项目页或任务总览笔记
- Goo-wiki 不可用时写入 `.goo/obsidian/` fallback
- 归档完成前必须验收 Markdown 连接图谱：任务页链接项目入口、复用知识、上下文材料和关键概念/问题/指标/历史任务页；项目 `index.md` 与 `log.md` 反向链接任务页；新增 concept/lessons/metrics 页面链接回任务页或项目入口
- 归档内容必须服务下一次任务复用，而不是只做事后报告

该更新是幂等的，只替换 AutoGoo marker 内的内容，不覆盖项目已有指引。非交互场景默认不写，需传 `--update-claude-md` 明确写入；需要跳过时传 `--skip-claude-md`。

如果项目配置了远程服务器，AutoGoo marker 块还会写入：

- 远程服务器表格：IP/host、端口、用户名、类型、用途、secrets 来源
- `### 何时使用`：按 `purpose` 或服务器类型说明 CPU/GPU 服务器适用场景
- 远程执行约束：AutoGoo 工具读取 `.goo/config.json` 与 `.goo/secrets.json`，执行任务时必须显式选择目标服务器，不依赖默认第一个
- secrets 约束：不得把密码展开到命令行、日志、计划正文或 subagent prompt

## 配置文件

用户级配置适合统一 wiki 路径和默认执行偏好；项目级配置适合覆盖单个 repo 的并发、归档或 wiki 设置。两者结构相同。

`~/.auto-goo/config.json` 或 `.goo/config.json` 示例：

```json
{
  "version": 1,
  "wiki_dir": "~/workspace/Goo-wiki",
  "wiki": {
    "search_paths": [
      "wiki/projects",
      "wiki/concepts",
      "journal/weekly",
      "log.md"
    ]
  },
  "archive": {
    "enabled": true,
    "fallback_dir": ".goo/obsidian",
    "plan_history_dir": ".goo/plans/history",
    "project_slug": "<project-slug>",
    "project_dir": "wiki/projects/<project-slug>",
    "fallback_project_dir": ".goo/obsidian/<project-slug>",
    "git_remote_url": "https://github.com/<owner>/<repo>.git"
  },
  "execution": {
    "max_concurrent": 6,
    "heartbeat_seconds": 30,
    "stale_after_seconds": 120
  },
  "planning": {
    "recall_wiki": true,
    "require_wiki_context": false
  },
  "init": {
    "prompt_for_scope": true,
    "prompt_for_wiki_dir": true
  },
  "servers": [
    {
      "ip": "192.168.1.100",
      "port": 22,
      "user": "ubuntu",
      "type": "cpu",
      "purpose": "数据预处理与模型评测",
      "secrets_file": ".goo/secrets.json"
    },
    {
      "ip": "192.168.1.101",
      "port": 2222,
      "user": "ubuntu",
      "type": "gpu",
      "purpose": "模型训练与推理",
      "secrets_file": ".goo/secrets.json"
    }
  ]
}
```

### 远程服务器配置

初始化时可以配置远程服务器（算力服务器、普通服务器等）。密码存储在独立的 secrets 文件中，不在 config.json 里保存：

| 作用域 | config 路径 | secrets 路径 |
| --- | --- | --- |
| `--user` | `~/.auto-goo/config.json` | `~/.auto-goo/secrets.json` |
| `--project` | `.goo/config.json` | `.goo/secrets.json` |

secrets 文件权限为 `chmod 600`，项目级 secrets 文件自动加入 `.gitignore`。

config 中只记录 `servers[].{ip, port, user, type, purpose, secrets_file}`，不存储密码。使用服务器时，从 `secrets_file` 读取密码。`port` 默认 22，`type` 为 `cpu` 或 `gpu`，默认 `cpu`。`purpose` 为服务器用途说明，用于 CLAUDE.md 中告知何时使用该服务器。

初始化阶段如果用户配置了服务器，脚本会检查本机是否安装 `sshpass`。未安装时只提醒用户：

```bash
sudo apt install sshpass
```

不会自动安装，也不会中断初始化。自动连接脚本支持按服务器选择：

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
if [ -z "$auto_goo_root" ] || [ ! -f "$auto_goo_root/skills/auto-goo/scripts/goo-ssh.sh" ]; then
  echo "AutoGoo root not configured; install auto-goo or enable a local directory marketplace in ~/.claude/settings.json" >&2
  exit 127
fi
bash "$auto_goo_root/skills/auto-goo/scripts/goo-ssh.sh" --server <ip-or-host>
bash "$auto_goo_root/skills/auto-goo/scripts/goo-ssh.sh" --server <ip-or-host>:<port>
bash "$auto_goo_root/skills/auto-goo/scripts/goo-ssh.sh" --server <user>@<ip-or-host>:<port>
bash "$auto_goo_root/skills/auto-goo/scripts/goo-ssh.sh" --host <ip-or-host> --user <user> --port <port>
```

### 自定义路径

可以用环境变量覆盖 wiki 路径：

```bash
export AUTO_GOO_WIKI_DIR="$HOME/workspace/Goo-wiki"
```

也可以在项目 `.claude/settings.json` 的 SessionStart hook 中修改检测命令：

```json
{
  "hooks": {
    "SessionStart": [{
      "hooks": [{
        "type": "command",
        "command": "ls <你的路径>/CLAUDE.md >/dev/null 2>&1 && echo '✓ Goo-wiki vault ready' || echo '⚠ Goo-wiki not found'"
      }]
    }]
  }
}
```

## 推荐 SessionStart hooks

以下 hooks 在每个会话启动时执行，建议加入项目 `.claude/settings.json`：

```json
{
  "hooks": {
    "SessionStart": [{
      "hooks": [
        {
          "type": "command",
          "command": "ls ~/workspace/Goo-wiki/CLAUDE.md >/dev/null 2>&1 && echo '✓ Goo-wiki vault ready' || echo '⚠ Goo-wiki not found — 使用 .goo/obsidian/ fallback'"
        },
        {
          "type": "command",
          "command": "cat .goo/plan.json 2>/dev/null && echo '⚠ 发现未完成任务，输入 /auto-goo:goo-continue 可继续执行' || true"
        }
      ]
    }]
  }
}
```
