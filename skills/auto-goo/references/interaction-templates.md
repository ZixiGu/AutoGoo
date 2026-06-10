# AskUserQuestion interaction templates

本文件是 AutoGoo 的固定交互模板库。任何需要用户选择、确认、重试、跳过、合并、改写或授权的步骤，都必须优先实际调用 `AskUserQuestion`，让 Claude Code 渲染方向键移动、Enter 确认的选择控件；不得只把 JSON 写给用户看。

通用规则：

- 能固定的问题必须复用下方 JSON 模板，不要临场改写 `header`、`id`、`question` 或固定选项文案。
- 推荐项必须放第一项，且 `label` 包含 `(Recommended)`。
- 每个问题至少提供两个显式选项；系统自动提供的 Other 只用于自定义输入，不算显式选项。
- 需要用户输入路径、IP、端口、用户名、goal ID、分支、目录或修改要求时，必须先提供固定选项，再允许 Other 输入；不得用占位值静默落盘。
- Other 输入必须被主 Agent 明确解释、校验或复述确认后再进入脚本、plan、日志或归档。路径要展开 `~` 并传给脚本；服务器地址要校验非空；端口要校验为整数；goal ID 要能匹配候选；分支/目录要先确认风险。
- 密码、token、密钥不允许写入聊天、命令行、plan、日志或 config。默认选择“稍后手动填入”；只有客户端提供安全输入能力时，才允许进入安全输入流程。
- 如果 `AskUserQuestion` 不可用、调用失败或按钮没有渲染，才使用命令文档中的文本列表 fallback，并明确标注这是 fallback。

## goo-init

```json
{
  "header": "配置作用域",
  "id": "config_scope",
  "question": "请选择 AutoGoo 配置写入位置。",
  "options": [
    {
      "label": "项目级 --project (Recommended)",
      "description": "写入当前项目 .goo/config.json，只影响当前项目。"
    },
    {
      "label": "用户级 --user",
      "description": "写入 ~/.auto-goo/config.json，作为所有项目的默认配置。"
    }
  ]
}
```

## git preflight

```json
{
  "header": "Git 初始化",
  "id": "git_init_project",
  "question": "当前项目不是 Git 仓库，是否要先初始化 Git？",
  "options": [
    {
      "label": "继续非 Git 执行 (Recommended)",
      "description": "不运行 git init；按普通项目执行，不使用 worktree 隔离。"
    },
    {
      "label": "运行 git init",
      "description": "只在当前项目根创建 .git，默认分支为 main；不自动 add 或 commit，直到有提交前仍不使用 worktree 隔离。"
    },
    {
      "label": "停止执行",
      "description": "保留当前 plan，不初始化 Git，也不派发执行。"
    }
  ]
}
```

```json
{
  "header": "Wiki 路径",
  "id": "wiki_dir",
  "question": "请选择 Goo-wiki 路径。",
  "options": [
    {
      "label": "~/workspace/Goo-wiki (Recommended)",
      "description": "使用默认 Goo-wiki 路径；不存在时初始化脚本会创建基础目录。"
    },
    {
      "label": "自定义路径",
      "description": "选择后在 Other 中输入路径；必须展开路径并传给 --wiki-dir。"
    }
  ]
}
```

```json
{
  "header": "项目说明",
  "id": "update_claude_md",
  "question": "是否更新当前项目 CLAUDE.md 的 AutoGoo 归档说明？",
  "options": [
    {
      "label": "更新 CLAUDE.md (Recommended)",
      "description": "只更新 AutoGoo marker 包裹段落，不覆盖已有项目指引。"
    },
    {
      "label": "跳过",
      "description": "不改 CLAUDE.md；脚本参数传 --skip-claude-md。"
    }
  ]
}
```

```json
{
  "header": "远程服务器",
  "id": "configure_servers",
  "question": "是否需要配置远程服务器？",
  "options": [
    {
      "label": "不配置 (Recommended)",
      "description": "只写本地 AutoGoo 配置。"
    },
    {
      "label": "配置服务器",
      "description": "继续收集服务器类型、IP、端口、用户名、用途和密码处理方式。"
    }
  ]
}
```

```json
{
  "header": "服务器类型",
  "id": "server_type",
  "question": "请选择服务器类型。",
  "options": [
    {
      "label": "GPU 服务器 (Recommended)",
      "description": "用于模型训练、推理或其他 GPU 长任务。"
    },
    {
      "label": "CPU 服务器",
      "description": "用于数据处理、预处理或普通远程执行。"
    }
  ]
}
```

```json
{
  "header": "服务器 IP",
  "id": "server_ip",
  "question": "请输入或选择服务器 IP 地址。",
  "options": [
    {
      "label": "通过 Other 输入 (Recommended)",
      "description": "在 Other 中输入真实 IP 或主机名；不要使用占位值落盘。"
    },
    {
      "label": "稍后手动补填",
      "description": "先跳过 IP，配置落盘后手动编辑 config/secrets；不得连接服务器。"
    }
  ]
}
```

```json
{
  "header": "SSH 端口",
  "id": "server_port",
  "question": "请选择 SSH 端口。",
  "options": [
    {
      "label": "22 (Recommended)",
      "description": "使用默认 SSH 端口。"
    },
    {
      "label": "2222",
      "description": "使用常见备用 SSH 端口；其他端口通过 Other 输入。"
    }
  ]
}
```

```json
{
  "header": "用户名",
  "id": "server_user",
  "question": "请选择 SSH 用户名。",
  "options": [
    {
      "label": "ubuntu (Recommended)",
      "description": "常见云服务器默认用户。"
    },
    {
      "label": "root",
      "description": "使用 root 用户；其他用户名通过 Other 输入。"
    }
  ]
}
```

```json
{
  "header": "服务器用途",
  "id": "server_purpose",
  "question": "请选择服务器用途说明。",
  "options": [
    {
      "label": "模型训练与推理 (Recommended)",
      "description": "用于 GPU 训练、推理、评测或长跑任务。"
    },
    {
      "label": "数据处理与预处理",
      "description": "用于数据转换、清洗、批处理或 CPU 任务。"
    }
  ]
}
```

```json
{
  "header": "密码处理",
  "id": "server_password",
  "question": "如何处理服务器密码？",
  "options": [
    {
      "label": "稍后手动填入 (Recommended)",
      "description": "不在聊天中输入密码；稍后编辑 secrets 文件并保持 chmod 600。"
    },
    {
      "label": "现在输入",
      "description": "仅在交互控件支持安全输入时使用；密码不得写入聊天日志或 config。"
    }
  ]
}
```

```json
{
  "header": "继续添加",
  "id": "add_another_server",
  "question": "是否继续添加另一台服务器？",
  "options": [
    {
      "label": "完成服务器配置 (Recommended)",
      "description": "汇总已收集服务器信息并进入最终确认。"
    },
    {
      "label": "再添加一台",
      "description": "重复服务器字段收集流程。"
    }
  ]
}
```

## brainstorm and goal selection

候选 goal 是动态数据。模板必须保留固定动作，具体 goal ID 写入 label 或 description。

```json
{
  "header": "候选目标",
  "id": "brainstorm_review",
  "question": "请选择下一步。",
  "options": [
    {
      "label": "选择推荐目标 <goal_id> (Recommended)",
      "description": "使用推荐目标继续进入 plan；把实际 goal ID 写入 <goal_id>。"
    },
    {
      "label": "选择其他目标",
      "description": "通过 Other 输入 goal ID，例如 g2；必须匹配候选 goals。"
    },
    {
      "label": "合并多个目标",
      "description": "通过 Other 输入要合并的 goal ID，例如 g1,g3。"
    },
    {
      "label": "修改候选目标",
      "description": "通过 Other 输入修改要求，更新 brainstorm 后再次审阅。"
    },
    {
      "label": "继续 brainstorm",
      "description": "继续探索更多候选目标，不进入 plan。"
    }
  ]
}
```

```json
{
  "header": "选择目标",
  "id": "existing_brainstorm_goal",
  "question": "检测到已有 brainstorm 候选目标。请选择用于 plan 的目标。",
  "options": [
    {
      "label": "使用推荐目标 <goal_id> (Recommended)",
      "description": "使用 recommended_goal_ids 中的首选目标；把实际 goal ID 写入 <goal_id>。"
    },
    {
      "label": "选择其他目标",
      "description": "通过 Other 输入 goal ID，例如 g2；必须匹配候选 goals。"
    },
    {
      "label": "合并多个目标",
      "description": "通过 Other 输入合并指令，例如 g1,g3。"
    },
    {
      "label": "回到 brainstorm",
      "description": "不生成 plan，回到目标探索和改写。"
    }
  ]
}
```

## plan, start, continue

```json
{
  "header": "任务线",
  "id": "thread_action",
  "question": "检测到当前 thread 或 plan 还未完成。请选择本次任务归属。",
  "options": [
    {
      "label": "新建 thread (Recommended)",
      "description": "为新任务创建独立 thread_id、plan、logs 和 artifacts，不覆盖当前执行现场。"
    },
    {
      "label": "继续当前 thread",
      "description": "把新需求合并到当前 thread 的 plan，保留已有步骤、日志和产物。"
    },
    {
      "label": "取消",
      "description": "保留当前 thread 和 plan，不写入新计划。"
    }
  ]
}
```

```json
{
  "header": "Thread 选择",
  "id": "thread_select",
  "question": "请选择要查看或继续的 AutoGoo thread。",
  "options": [
    {
      "label": "当前 thread <thread_id> (Recommended)",
      "description": "使用 .goo/current_thread.json 中记录的 thread；把实际 thread_id 写入 <thread_id>。"
    },
    {
      "label": "选择其他 thread",
      "description": "通过 Other 输入 thread_id；必须能在 .goo/threads/index.json 中匹配。"
    },
    {
      "label": "查看全部 threads",
      "description": "运行 goo-status --threads 后再选择。"
    }
  ]
}
```

```json
{
  "header": "现有计划",
  "id": "existing_plan_action",
  "question": "当前 .goo/plan.json 还未完成。请选择处理方式。",
  "options": [
    {
      "label": "修改当前 plan (Recommended)",
      "description": "把新需求合并到现有 .goo/plan.json，保留已完成步骤和执行证据。"
    },
    {
      "label": "新建 plan",
      "description": "先归档旧 .goo/plan.json，再写入新的 .goo/plan.json。"
    },
    {
      "label": "取消",
      "description": "保留当前 plan，不写入新计划。"
    }
  ]
}
```

```json
{
  "header": "计划审阅",
  "id": "plan_review",
  "question": "请审阅计划并选择下一步。",
  "options": [
    {
      "label": "确认计划 (Recommended)",
      "description": "确认当前 DAG，可归档后进入执行。"
    },
    {
      "label": "修改计划",
      "description": "通过 Other 输入修改要求，更新 .goo/plan.json 后再次审阅。"
    },
    {
      "label": "拆分/合并步骤",
      "description": "通过 Other 输入具体拆分或合并要求。"
    },
    {
      "label": "回到 brainstorm",
      "description": "暂停 plan，返回目标选择或目标改写。"
    }
  ]
}
```

```json
{
  "header": "执行确认",
  "id": "start_plan_review",
  "question": "执行前需要确认当前 plan。请选择处理方式。",
  "options": [
    {
      "label": "确认并继续执行 (Recommended)",
      "description": "同步必要上下文后开始执行可运行步骤。"
    },
    {
      "label": "修改 plan / 同步新增约束",
      "description": "通过 Other 输入新增约束或修改要求，先更新 plan。"
    },
    {
      "label": "停止并保留当前现场",
      "description": "不执行步骤，保留当前 .goo/plan.json 和日志。"
    }
  ]
}
```

```json
{
  "header": "关键路径失败",
  "id": "failed_step_action",
  "question": "关键路径步骤失败，会阻塞后续步骤。请选择处理方式。",
  "options": [
    {
      "label": "重试该步骤 (Recommended)",
      "description": "保留当前 plan，重试失败 step。"
    },
    {
      "label": "跳过并继续",
      "description": "仅继续不依赖该失败 step 的可执行步骤。"
    },
    {
      "label": "停止并保留当前现场",
      "description": "停止恢复调度，等待用户进一步处理。"
    }
  ]
}
```

## research, usage, publish, improve

```json
{
  "header": "研究后续",
  "id": "research_followup",
  "question": "检测到需要确认的后续动作。请选择处理方式。",
  "options": [
    {
      "label": "只记录步骤 (Recommended)",
      "description": "只记录下载、申请或受限资源处理步骤，不立即执行。"
    },
    {
      "label": "执行可访问性检查",
      "description": "执行小型元数据或可访问性检查，不下载大文件。"
    },
    {
      "label": "进入 goo-plan 规划",
      "description": "进入 /auto-goo:goo-plan 规划下载、复现或资源申请任务。"
    },
    {
      "label": "跳过受限资源",
      "description": "不处理这些受限资源，只保留当前研究笔记。"
    }
  ]
}
```

```json
{
  "header": "Usage 视图",
  "id": "usage_view",
  "question": "请选择 usage 面板打开方式。",
  "options": [
    {
      "label": "浏览器面板 (Recommended)",
      "description": "启动 HTML 仪表盘并自动刷新，适合持续观察 token 消耗。"
    },
    {
      "label": "内联快照",
      "description": "在当前终端打印一次 usage 快照，不进入交互式 watch 模式。"
    }
  ]
}
```

```json
{
  "header": "公开发布",
  "id": "publish_public_confirm",
  "question": "公开发布会写入远端或 GitHub Pages。请选择处理方式。",
  "options": [
    {
      "label": "只生成本地 HTML (Recommended)",
      "description": "不提交、不推送，只生成本地 .goo/site 多页站点。"
    },
    {
      "label": "提交并推送到指定分支/目录",
      "description": "通过 Other 输入目标分支和目录；必须再次确认风险后才能 git commit/push。"
    },
    {
      "label": "取消发布",
      "description": "不生成公开发布产物，不提交不推送。"
    }
  ]
}
```

```json
{
  "header": "改进确认",
  "id": "improve_confirm",
  "question": "请选择如何处理本次 AutoGoo 改进方案。",
  "options": [
    {
      "label": "应用修改 (Recommended)",
      "description": "按上面的方案编辑插件文件。"
    },
    {
      "label": "只保存建议",
      "description": "记录到 .goo/improvements.log，不改插件文件。"
    },
    {
      "label": "放弃本次改进",
      "description": "不写入、不修改。"
    }
  ]
}
```

## permissions and approval blocks

```json
{
  "header": "执行许可",
  "id": "permission_block_action",
  "question": "执行遇到需要用户许可的操作。请选择处理方式。",
  "options": [
    {
      "label": "批准本次操作 (Recommended)",
      "description": "仅批准本次列出的命令类别、路径和风险范围。"
    },
    {
      "label": "修改 plan 后再执行",
      "description": "通过 Other 输入限制条件或替代方案，先更新 plan。"
    },
    {
      "label": "拒绝并停止相关步骤",
      "description": "不执行该操作，把相关 step 标记为 blocked 或 failed。"
    }
  ]
}
```
