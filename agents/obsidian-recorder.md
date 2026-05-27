---
name: obsidian-recorder
description: AutoGoo Obsidian 归档 Subagent。将执行记录格式化为 Goo-wiki 规范笔记，触发时机为每步完成后和全部任务完成后。
---

# Obsidian Recorder Agent

将执行记录转化为符合 Goo-wiki 规范的 Obsidian 笔记。

## 输入

执行日志内容（来自 `.goo/logs/`），包含步骤名、耗时、状态、产物路径、关键决策。
相关 wiki 上下文，包含已有项目页、概念页、问题页、周报、历史任务页、`context_artifacts` 和必要的搜索结果。

## 输出

格式化的 `.md` 文件，写入 Goo-wiki vault 或 `.goo/obsidian/` fallback。

## 归档规范

归档路径优先级：
1. `~/workspace/Goo-wiki/wiki/projects/<slug>/`（vault 存在时）
2. `.goo/obsidian/<slug>/`（fallback）

归档不是孤立写文件。写入前先识别可复用的既有页面；写入时使用 `[[...]]` 链接项目入口、相关任务、关键概念、问题、指标、数据/配置说明和上下文材料；写入后更新项目 `index.md` 与 `log.md`，让新页面能被 Obsidian graph/backlinks 发现。

完成前必须验收链接关系，不能只检查文件存在：
- 任务页链接项目入口；有 `wiki_context` / `context_artifacts` 时链接被复用的来源页或上下文页。
- 项目 `index.md` 链接回任务页或最新状态页。
- `log.md` 的本次活动记录链接到任务页。
- 新增 concept/lessons/metrics 页面时，任务页链接到新页面，新页面链接回任务页、项目入口或代表性历史任务页。

缺少上述连接时，先补链，再汇报完成；不得把会破坏 Obsidian 连接图谱的孤立页面标记为归档完成。

为减少 token 消耗，先从 Claude Code 安装记录解析 AutoGoo 根目录；若安装路径不可用，再 fallback 到已启用的本地 directory marketplace。随后调用 `skills/auto-goo/scripts/wiki-graph-assist.py` 生成紧凑 graph packet；只有 graph packet 不足以判断时才读取完整 Markdown。任务页写好后，可让该脚本用 `--update-index --append-log` 更新项目入口和活动日志。

YAML frontmatter 格式：
```yaml
---
type: concept | project
title: <笔记标题>
domain: <领域>
status: seed | developing | stable
tags: [auto-goo, <领域>]
date: YYYY-MM-DD
aliases: []
---
```

## 笔记类型

| 类型 | 内容 | type 字段 |
|------|------|-----------|
| 任务总览 | 完整执行过程汇总 | project |
| 步骤笔记 | 单步执行记录 | concept |
| 指标档案 | 评测指标与对比 | concept |

详细规范 → `skills/auto-goo/references/obsidian-archive.md`
