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

该命令使用 **Agent 交互模式 + 脚本落盘**：

- 主 Agent 收到命令后必须先交互提问，不预先检查环境，不先运行 Bash，不先解析 AutoGoo root。
- 所有缺失参数收集完成后，才进入脚本落盘阶段；脚本内部自行处理已有配置的检测和覆盖确认。
- slash command 的当前工作目录通常是用户项目，不一定是插件目录；最终落盘前必须从 Claude Code 安装记录解析 AutoGoo 根目录，不能拼出 `/skills/...`。
- 禁止在命令正文中直接执行含 heredoc / file redirection 的 root 解析片段。需要解析 root 时，使用插件内置 `skills/auto-goo/scripts/resolve-root.sh`，或等价的无 heredoc 命令封装。

用户没有在命令里显式给出参数时，主 Agent 至少先问两个问题：

1. 配置作用域：`--user` 还是 `--project`
2. Goo-wiki 路径：向用户展示默认路径 `~/workspace/Goo-wiki`；用户不输入或选择默认时就使用该路径，也可输入自定义路径
3. 业务项目目录结构：项目级初始化时必须先问是否创建；默认不创建。用户选择创建时，再让用户选择 `--project-layout standard|ml|data|docs`，或用 `--project-dirs src,data/raw,docs` 指定代码、数据、文档等目录。AutoGoo 自身运行态目录固定在项目 `.goo/` 下。业务目录创建完成后，继续询问是否把目录约定写入项目 `CLAUDE.md`。

项目级初始化时，还应通过 `AskUserQuestion` 确认是否更新项目 `CLAUDE.md`；如果用户创建了业务项目目录结构，必须先单独询问是否把目录约定写入 `CLAUDE.md`。需要远程服务器配置时，由主 Agent 通过 `AskUserQuestion` 逐字段收集，每个问题提供 2 个选项（一个推荐默认值 + 一个常用备选），用户可通过系统自动提供的 "Other" 选项输入自定义值。服务器非敏感参数（类型、名称/别名、SSH host/IP/DNS、端口、用户名、用途）全部收集完成后，再调用脚本进入密码录入。密码不得在聊天中明文输出。

最终落盘阶段运行脚本时，只能在用户已确认参数后执行，形态如下：先解析 AutoGoo root，再运行 `bash "$auto_goo_root/skills/auto-goo/scripts/goo-init.sh" --user|--project --wiki-dir <已确认路径> ...`。远程服务器非敏感参数必须通过可重复的 `--server 'name=<别名>,host=<ssh-host-or-ip>,user=<user>,port=<port>,type=<cpu|gpu>,purpose=<用途>'` 传入；密码不得作为命令参数传入。不得在交互前运行 root 解析命令。

Agent 交互流程：

1. **不要先检查环境，直接开始交互提问。** 收到 `/auto-goo:goo-init` 后，不要先跑 `ls`、`git remote`、`test -f` 等探测命令，而是直接调用 `AskUserQuestion` / 结构化选择 UI 询问用户偏好。不得在 `AskUserQuestion` 可用时用普通文本要求用户手打 `1/2` 或 `--project/--user`。
2. 读取用户已给参数，缺什么问什么；不要一次性抛出长问卷。
3. 所有交互问题必须使用 `AskUserQuestion` / 结构化选择 UI 展示可点击选项；不得只输出“请选择配置作用域”这类问题标题后等待用户，也不得要求用户手打 `1/2` 或 `--project/--user`。如果结构化选择 UI / AskUserQuestion 不可用、调用失败或没有渲染出按钮，才允许降级为明确标注 fallback 的纯文本列表选项，继续收集用户选择。
4. 第一个问题必须优先用 `AskUserQuestion` 呈现以下选项：
   - 项目级 `--project` (Recommended) — 写入当前项目 `.goo/config.json`
   - 用户级 `--user` — 写入 `~/.auto-goo/config.json`
5. 如果无法渲染结构化选项，使用以下纯文本 fallback：
   ```text
   这是 fallback：结构化选择 UI 不可用。请选择配置作用域：
   1. 项目级 --project (Recommended) - 写入当前项目 .goo/config.json
   2. 用户级 --user - 写入 ~/.auto-goo/config.json

   请回复 1/2，或直接回复“项目级”/“用户级”。
   ```
6. 第二个问题必须优先用 `AskUserQuestion` 呈现以下选项：
   - `~/workspace/Goo-wiki` (Recommended)
   - 自定义路径（选择后在 Other 输入）
7. 如果无法渲染结构化选项，使用以下纯文本 fallback：
   ```text
   这是 fallback：结构化选择 UI 不可用。请选择 Goo-wiki 路径：
   1. ~/workspace/Goo-wiki (Recommended)
   2. 自定义路径

   请回复 1/2；如果选择自定义路径，请直接写完整路径。
   ```
8. 后续二选一问题也必须优先用 `AskUserQuestion` 提供两个显式选项；只有交互控件不可用时，才允许使用明确标注 fallback 的纯文本列表。凡 `skills/auto-goo/references/interaction-templates.md` 已定义固定 `id` 的问题，必须复用对应模板，不要临场改写。
9. 项目级初始化时，继续询问：
   - 是否创建业务项目目录结构：必须实际调用 `AskUserQuestion` 并复用 `id=project_workspace_create` 模板；默认「不创建 (Recommended)」。用户未选择前不得静默创建目录。
   - 如果用户选择创建，继续实际调用 `AskUserQuestion` 并复用 `id=project_workspace_layout` 模板。选择 `standard`/`ml`/`data` 时分别传 `--project-layout standard|ml|data`；如果用户通过 Other 输入 `docs`，传 `--project-layout docs`；其他 Other 输入按逗号分隔目录处理，复述确认后传 `--project-dirs <用户输入>`。
   - 业务目录创建后，必须实际调用 `AskUserQuestion` 并复用 `id=project_workspace_claude_md` 模板，询问是否把目录约定写入项目 `CLAUDE.md`。
   - 是否把 Goo-wiki 归档原则或服务器使用约定写入项目 `CLAUDE.md`（`AskUserQuestion`，选项：「是 (Recommended)」「跳过」）
   - 是否需要配置远程服务器（`AskUserQuestion`，选项：「否 (Recommended)」「是」）
   - 如果用户选择配置服务器，逐字段使用 `AskUserQuestion` 收集非敏感参数。**每个问题必须至少 2 个显式选项**（系统的自动 Other 不算在内）。用户可直接选用预设值，或通过 "Other" 输入自定义值：
     - **服务器类型**：「GPU 服务器 (Recommended)」「CPU 服务器」
     - **服务器名称/别名**：「gpu-a100」「lab-cpu」
     - **SSH host/IP/DNS**：「gpu-a100」「192.168.1.100」
     - **SSH 端口**：「22 (Recommended)」「2222」
     - **用户名**：「ubuntu (Recommended)」「root」
     - **用途说明**：「模型训练与推理」「数据处理与预处理」
     - **密码**：「稍后手动填入 (Recommended)」「输入密码」— 用户可输入密码，也可选默认跳过。如果跳过，提示用户密码存储在 `<项目级 .goo/secrets.json 或用户级 ~/.auto-goo/secrets.json>`（chmod 600），可稍后编辑该文件补填 `password` 字段。
     - 每台服务器配置完后询问「是否添加另一台服务器？」
     - 所有服务器信息收集完后，汇总展示给用户确认，然后调用脚本落盘。
10. 用户回答完所有问题后，把已确认的 `--user/--project`、`--wiki-dir`、`--project-layout`、`--project-dirs`、`--project-slug`、`--update-claude-md/--skip-claude-md` 等参数传给脚本。脚本内部自行处理已存在配置的检测和覆盖确认。
11. 脚本执行后读取结果摘要，向用户说明最终生效配置和 fallback 情况。

脚本落盘行为：

1. **选择作用域** — 用户级或项目级；未传 `--user/--project` 时交互提问
2. **创建配置目录** — 用户级确保 `~/.auto-goo/`；项目级确保 `.goo/`
3. **读取已有配置** — 脚本自行检测目标配置是否已存在，存在时展示当前配置并询问是否更新
4. **配置 Wiki 路径** — 必须向用户提供默认路径 `~/workspace/Goo-wiki`；用户不输入则使用默认路径，也允许用户输入自定义路径，并按优先级解析：
   - `AUTO_GOO_WIKI_DIR`
   - 项目级 `.goo/config.json` 的 `wiki_dir`
   - 用户级 `~/.auto-goo/config.json` 的 `wiki_dir`
   - 默认 `~/workspace/Goo-wiki`
5. **配置业务项目目录结构** — AutoGoo 自身状态目录固定为 `.goo/`，配置中的 `workspace.paths` 只描述 AutoGoo 运行态路径。项目级初始化时，先询问是否创建业务目录；用户选择创建后，传 `--project-layout standard|ml|data|docs` 或 `--project-dirs <逗号分隔目录>`，脚本创建这些业务目录并写入 `project_workspace.{layout,dirs}`。默认 `project_workspace.layout="none"`，不创建业务目录，避免污染已有项目。业务目录创建后，必须继续询问是否把目录约定写入项目 `CLAUDE.md`。
6. **配置远程服务器** — Wiki 路径配置后，询问用户是否有远程服务器需要配置；用户确认后逐个交互输入服务器类型（cpu/gpu）、名称/别名、SSH host/IP/DNS、端口（默认 22）、用户名、用途说明和密码处理方式。主 Agent 已通过 `AskUserQuestion` 收集到非敏感参数时，调用脚本必须传 `--server 'name=<别名>,host=<ssh-host-or-ip>,user=<user>,port=<port>,type=<cpu|gpu>,purpose=<用途>'`，可重复传入多台服务器。密码不得在聊天或命令行中明文传递；脚本会创建独立 secrets 文件占位（项目级 `.goo/secrets.json`，用户级 `~/.auto-goo/secrets.json`），文件权限设为 `chmod 600`，用户稍后手动填入密码。项目级 secrets 文件自动加入 `.gitignore`。config 中记录 `servers[].{name, host, ip?, port, user, type, purpose, secrets_file}`，不存储密码。支持配置多个服务器。配置服务器后必须检查本机是否安装 `sshpass`；缺失时提醒用户运行 `sudo apt install sshpass`，但不中断初始化。
7. **确保 Goo-wiki 存在** — 如果用户确认或输入的 `<wiki_dir>` 不存在，自动创建该目录，并补齐 `CLAUDE.md`、`log.md`、`wiki/projects/`、`wiki/concepts/`、`wiki/questions/`、`journal/daily/`、`journal/weekly/` 基础结构；不得因为路径不存在而改用 `.goo/obsidian/` fallback
8. **确定项目归档根路径** — `--project` 时默认用项目根目录名生成 `project_slug`，也可传 `--project-slug <slug>`；创建 `<wiki_dir>/wiki/projects/<project_slug>/`
8. **记录 Git 地址** — `--project` 且当前项目是 Git repo 时，读取 `origin` remote（没有 origin 时读取第一个 remote），写入 `.goo/config.json.archive.git_remote_url`，并同步到 Goo-wiki 项目页 `wiki/projects/<project_slug>/<project_slug>.md`
9. **写入配置** — 生成目标配置文件；项目级配置写入 `archive.project_slug`、`archive.project_dir`、`archive.fallback_project_dir`、固定 `.goo` 的 `workspace.paths`、可选 `project_workspace`，以及可用时的 `archive.git_remote_url`；有远程服务器时写入 `servers[]`
10. **项目 CLAUDE.md 约定** — `--project` 且创建了业务目录时，询问是否幂等更新项目 `CLAUDE.md`，写入 `project_workspace` 目录语义、读写边界和 `.goo/` 状态目录边界；`--project` 且 Goo-wiki 可用时，另询问是否加入 Goo-wiki 召回与归档要求。非交互场景默认不写，需传 `--update-claude-md` 明确写入；如需明确跳过，传 `--skip-claude-md`
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
  "workspace": {
    "root": ".goo",
    "layout": "standard",
    "paths": {
      "threads_dir": ".goo/threads",
      "logs_dir": ".goo/logs",
      "artifacts_dir": ".goo/artifacts",
      "reports_dir": ".goo/reports",
      "locks_dir": ".goo/locks",
      "change_requests_dir": ".goo/change-requests",
      "site_dir": ".goo/site"
    }
  },
  "project_workspace": {
    "layout": "ml",
    "dirs": ["src", "configs", "scripts", "notebooks", "data/raw", "data/processed", "models", "outputs", "reports", "docs", "tests"]
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
- `--project` 且项目是 Git repo 时，必须把 git remote 地址写入 `.goo/config.json.archive.git_remote_url`；Goo-wiki 可用时同步写入 `<wiki_dir>/wiki/projects/<project_slug>/<project_slug>.md`
- `--project` 且创建业务目录时，必须先用 `AskUserQuestion` 复用 `id=project_workspace_claude_md` 模板询问用户是否把目录约定写入 `CLAUDE.md`；Goo-wiki 可用或配置服务器时，再询问是否写入归档原则或服务器使用约定。用户同意后只追加或更新由 AutoGoo marker 包裹的段落，不重写其他内容
- 初始化交互由主 Agent 负责；不得派发 Subagent 或用临时代码替代脚本写配置
- 配置完成后，脚本不得尝试连接服务器（不做 ssh、ping、端口探测等网络连接）；仅写入配置文件
- 最终落盘必须先解析 `auto_goo_root`，再运行 `bash "$auto_goo_root/skills/auto-goo/scripts/goo-init.sh"`，并传入主 Agent 已确认的参数；不得在根目录变量为空时运行 `/skills/auto-goo/scripts/goo-init.sh`
- 用户回答了 `--user` 或 `--project` 后，必须把该参数传给脚本
- 用户确认或输入 wiki 路径后，必须把 `--wiki-dir <路径>` 传给脚本
- 用户指定业务项目目录结构后，必须把 `--project-layout <standard|ml|data|docs>` 或 `--project-dirs <逗号分隔目录>` 传给脚本；未指定时不创建业务目录。该询问必须用 `id=project_workspace_create` 和 `id=project_workspace_layout` 两个固定 `AskUserQuestion` 模板完成。AutoGoo 自身状态目录始终使用项目 `.goo/`
- 如果用户输入的 Goo-wiki 路径不存在，自动创建该路径和基础 vault 文件；只有创建失败或后续归档时 wiki 不可写，才提示使用 `.goo/obsidian/` fallback
- 最终输出用户级、项目级和最终生效配置摘要
- 有远程服务器时，密码必须存储在独立 secrets 文件中（项目级 `.goo/secrets.json`，用户级 `~/.auto-goo/secrets.json`），文件权限 `chmod 600`；config 中只记录 `{name, host, ip?, port, user, type, purpose, secrets_file}`，不存储密码；非敏感参数通过 `--server` 写入，密码由用户稍后手动填入 secrets；如果本机未安装 `sshpass`，必须提示用户安装后才能使用自动填密码的 `goo-ssh.sh`
- 项目级 secrets 文件必须自动加入 `.gitignore`，防止密码泄露到版本控制
