---
name: auto-goo:goo-init
description: 初始化 AutoGoo 配置 — 支持用户级 ~/.auto-goo/config.json 和项目级 .goo/config.json
---

# /auto-goo:goo-init — 初始化配置

第一次使用 AutoGoo 时，可以初始化用户级默认配置；在具体项目里也可以初始化项目级覆盖配置。

**非 Git 项目**：完全支持。Git remote 地址记录是可选功能，仅在项目是 Git repo 时自动启用。

```text
/auto-goo:goo-init
```

## 作用域

| 命令 | 写入位置 | 用途 |
| --- | --- | --- |
| `/auto-goo:goo-init --user` | `~/.auto-goo/config.json` | 当前用户的全局默认配置，适合统一 wiki 路径和执行偏好 |
| `/auto-goo:goo-init --project` | `.goo/config.json`，可选更新 `CLAUDE.md` | 当前项目的局部覆盖配置；Goo-wiki 可用时询问是否写入项目归档原则 |
| `/auto-goo:goo-init` | 交互提问 | 先询问配置到用户级还是项目级，再继续询问 wiki 路径 |

## 行为

该命令使用 **Agent 交互模式 + 脚本落盘**：主 Agent 收到命令后直接开始交互提问，不预先检查环境；脚本内部自行处理已有配置的检测和覆盖确认。slash command 的当前工作目录通常是用户项目，不一定是插件目录；脚本执行前必须从 Claude Code 安装记录解析 AutoGoo 根目录，不能拼出 `/skills/...`：

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
if [ -z "$auto_goo_root" ] || [ ! -f "$auto_goo_root/skills/auto-goo/scripts/goo-init.sh" ]; then
  echo "AutoGoo root not configured; install auto-goo so Claude Code records it in ~/.claude/plugins/installed_plugins.json" >&2
  exit 127
fi
bash "$auto_goo_root/skills/auto-goo/scripts/goo-init.sh" <用户选择的作用域>
```

默认优先由主 Agent 提问，不要求用户进入 Bash 交互。用户没有在命令里显式给出参数时，主 Agent 至少先问两个问题：

1. 配置作用域：`--user` 还是 `--project`
2. Goo-wiki 路径：向用户展示默认路径 `~/workspace/Goo-wiki`；用户不输入或选择默认时就使用该路径，也可输入自定义路径

项目级初始化时，还应通过对话确认是否更新项目 `CLAUDE.md`；需要远程服务器配置时，由主 Agent 通过 `AskUserQuestion` 逐字段收集，每个问题提供 2 个选项（一个推荐默认值 + 一个常用备选），用户可通过系统自动提供的 "Other" 选项输入自定义值。服务器非敏感参数（类型、IP、端口、用户名、用途）全部收集完成后，再调用脚本进入密码录入。密码不得在聊天中明文输出。

例如用户选择 `--user` 且不输入路径（使用默认路径）时，必须运行：

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
if [ -z "$auto_goo_root" ] || [ ! -f "$auto_goo_root/skills/auto-goo/scripts/goo-init.sh" ]; then
  echo "AutoGoo root not configured; install auto-goo so Claude Code records it in ~/.claude/plugins/installed_plugins.json" >&2
  exit 127
fi
bash "$auto_goo_root/skills/auto-goo/scripts/goo-init.sh" --user --wiki-dir ~/workspace/Goo-wiki
```

例如用户选择 `--project` 且输入自定义路径时，必须运行：

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
if [ -z "$auto_goo_root" ] || [ ! -f "$auto_goo_root/skills/auto-goo/scripts/goo-init.sh" ]; then
  echo "AutoGoo root not configured; install auto-goo so Claude Code records it in ~/.claude/plugins/installed_plugins.json" >&2
  exit 127
fi
bash "$auto_goo_root/skills/auto-goo/scripts/goo-init.sh" --project --wiki-dir /path/to/Goo-wiki
```

带参数示例：

```bash
bash "$auto_goo_root/skills/auto-goo/scripts/goo-init.sh" --user
bash "$auto_goo_root/skills/auto-goo/scripts/goo-init.sh" --project --wiki-dir ~/workspace/Goo-wiki
bash "$auto_goo_root/skills/auto-goo/scripts/goo-init.sh" --project --wiki-dir ~/workspace/Goo-wiki --project-slug my-project
bash "$auto_goo_root/skills/auto-goo/scripts/goo-init.sh" --project --wiki-dir ~/workspace/Goo-wiki --update-claude-md
bash "$auto_goo_root/skills/auto-goo/scripts/goo-init.sh" --project --wiki-dir ~/workspace/Goo-wiki --skip-claude-md
bash "$auto_goo_root/skills/auto-goo/scripts/goo-init.sh" --project --wiki-dir ~/workspace/Goo-wiki
```

Agent 交互流程：

1. **不要先检查环境，直接开始交互提问。** 收到 `/auto-goo:goo-init` 后，不要先跑 `ls`、`git remote`、`test -f` 等探测命令，而是直接用 AskUserQuestion 或对话方式询问用户偏好。
2. 读取用户已给参数，缺什么问什么；不要一次性抛出长问卷。
3. 第一个问题：配置作用域，选项：「项目级 --project (Recommended)」「用户级 --user」
4. 第二个问题：Goo-wiki 路径，选项：「~/workspace/Goo-wiki (Recommended)」「自定义路径（选择后在下方 Other 输入）」
5. 项目级初始化时，继续询问：
   - 是否更新项目 `CLAUDE.md`（`AskUserQuestion`，选项：「是 (Recommended)」「跳过」）
   - 是否需要配置远程服务器（`AskUserQuestion`，选项：「否 (Recommended)」「是」）
   - 如果用户选择配置服务器，逐字段使用 `AskUserQuestion` 收集非敏感参数。**每个问题必须至少 2 个显式选项**（系统的自动 Other 不算在内）。用户可直接选用预设值，或通过 "Other" 输入自定义值：
     - **服务器类型**：「GPU 服务器 (Recommended)」「CPU 服务器」
     - **IP 地址**：「192.168.1.100」「10.0.0.1」
     - **SSH 端口**：「22 (Recommended)」「2222」
     - **用户名**：「ubuntu (Recommended)」「root」
     - **用途说明**：「模型训练与推理」「数据处理与预处理」
     - **密码**：「稍后手动填入 (Recommended)」「输入密码」— 用户可输入密码，也可选默认跳过。如果跳过，提示用户密码存储在 `<项目级 .goo/secrets.json 或用户级 ~/.auto-goo/secrets.json>`（chmod 600），可稍后编辑该文件补填 `password` 字段。
     - 每台服务器配置完后询问「是否添加另一台服务器？」
     - 所有服务器信息收集完后，汇总展示给用户确认，然后调用脚本落盘。
6. 用户回答完所有问题后，把已确认的 `--user/--project`、`--wiki-dir`、`--project-slug`、`--update-claude-md/--skip-claude-md` 等参数传给脚本。脚本内部自行处理已存在配置的检测和覆盖确认。
7. 脚本执行后读取结果摘要，向用户说明最终生效配置和 fallback 情况。

脚本落盘行为：

1. **选择作用域** — 用户级或项目级；未传 `--user/--project` 时交互提问
2. **创建配置目录** — 用户级确保 `~/.auto-goo/`；项目级确保 `.goo/`
3. **读取已有配置** — 脚本自行检测目标配置是否已存在，存在时展示当前配置并询问是否更新
4. **配置 Wiki 路径** — 必须向用户提供默认路径 `~/workspace/Goo-wiki`；用户不输入则使用默认路径，也允许用户输入自定义路径，并按优先级解析：
   - `AUTO_GOO_WIKI_DIR`
   - 项目级 `.goo/config.json` 的 `wiki_dir`
   - 用户级 `~/.auto-goo/config.json` 的 `wiki_dir`
   - 默认 `~/workspace/Goo-wiki`
5. **配置远程服务器** — Wiki 路径配置后，询问用户是否有远程服务器需要配置；用户确认后逐个交互输入服务器类型（cpu/gpu）、IP、端口（默认 22）、用户名、用途说明和密码（密码隐藏输入）。密码存储在独立的 secrets 文件中（项目级 `.goo/secrets.json`，用户级 `~/.auto-goo/secrets.json`），文件权限设为 `chmod 600`；项目级 secrets 文件自动加入 `.gitignore`。config 中只记录 `servers[].{ip, port, user, type, purpose, secrets_file}`，不存储密码。支持配置多个服务器。配置服务器后必须检查本机是否安装 `sshpass`；缺失时提醒用户运行 `sudo apt install sshpass`，但不中断初始化。
6. **确保 Goo-wiki 存在** — 如果用户确认或输入的 `<wiki_dir>` 不存在，自动创建该目录，并补齐 `CLAUDE.md`、`log.md`、`wiki/projects/`、`wiki/concepts/`、`wiki/questions/`、`journal/daily/`、`journal/weekly/` 基础结构；不得因为路径不存在而改用 `.goo/obsidian/` fallback
7. **确定项目归档根路径** — `--project` 时默认用项目根目录名生成 `project_slug`，也可传 `--project-slug <slug>`；创建 `<wiki_dir>/wiki/projects/<project_slug>/`
8. **记录 Git 地址** — `--project` 且当前项目是 Git repo 时，读取 `origin` remote（没有 origin 时读取第一个 remote），写入 `.goo/config.json.archive.git_remote_url`，并同步到 Goo-wiki 项目页 `wiki/projects/<project_slug>/index.md`
9. **写入配置** — 生成目标配置文件；项目级配置写入 `archive.project_slug`、`archive.project_dir`、`archive.fallback_project_dir`，以及可用时的 `archive.git_remote_url`；有算力服务器时写入 `compute_servers`
10. **项目归档原则** — `--project` 且 Goo-wiki 可用时，询问用户是否幂等更新项目 `CLAUDE.md`，加入 Goo-wiki 召回与归档要求；非交互场景默认不写，需传 `--update-claude-md` 明确写入；如需明确跳过，传 `--skip-claude-md`
11. **提示 hooks** — 展示推荐的 `.claude/settings.json` SessionStart hooks，由用户决定是否复制/合并

## 默认配置

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

## 输出要求

- 不覆盖已有 `.goo/config.json`，除非用户明确确认；但保留 config 时仍可按 `--update-claude-md` 更新项目 `CLAUDE.md`
- 不覆盖已有 `~/.auto-goo/config.json`，除非用户明确确认
- 不删除任何已有 `.goo/` 内容
- `--project` 且 Goo-wiki 可用时，必须创建或复用 `<wiki_dir>/wiki/projects/<project_slug>/` 作为项目归档根路径
- `--project` 且项目是 Git repo 时，必须把 git remote 地址写入 `.goo/config.json.archive.git_remote_url`；Goo-wiki 可用时同步写入 `<wiki_dir>/wiki/projects/<project_slug>/index.md`
- `--project` 且 Goo-wiki 可用时，必须先询问用户是否更新 `CLAUDE.md`；用户同意后只追加或更新由 AutoGoo marker 包裹的归档原则段落，不重写其他内容
- 初始化交互由主 Agent 负责；不得派发 Subagent 或用临时代码替代脚本写配置
- 配置完成后，脚本不得尝试连接服务器（不做 ssh、ping、端口探测等网络连接）；仅写入配置文件
- 最终落盘必须先解析 `auto_goo_root`，再运行 `bash "$auto_goo_root/skills/auto-goo/scripts/goo-init.sh"`，并传入主 Agent 已确认的参数；不得在根目录变量为空时运行 `/skills/auto-goo/scripts/goo-init.sh`
- 用户回答了 `--user` 或 `--project` 后，必须把该参数传给脚本
- 用户确认或输入 wiki 路径后，必须把 `--wiki-dir <路径>` 传给脚本
- 如果用户输入的 Goo-wiki 路径不存在，自动创建该路径和基础 vault 文件；只有创建失败或后续归档时 wiki 不可写，才提示使用 `.goo/obsidian/` fallback
- 最终输出用户级、项目级和最终生效配置摘要
- 有远程服务器时，密码必须存储在独立 secrets 文件中（项目级 `.goo/secrets.json`，用户级 `~/.auto-goo/secrets.json`），文件权限 `chmod 600`；config 中只记录 `{ip, user, secrets_file}`，不存储密码；如果本机未安装 `sshpass`，必须提示用户安装后才能使用自动填密码的 `goo-ssh.sh`
- 项目级 secrets 文件必须自动加入 `.gitignore`，防止密码泄露到版本控制
