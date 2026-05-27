# 多步骤编排示例：数据管道 ETL

## 任务描述

从 CSV 提取数据，清洗后计算统计指标，生成可视化报告。

## 解析结果 (plan.json)

```json
{
  "task": "数据 ETL 管道：CSV 提取 → 清洗 → 统计 → 可视化",
  "created_at": "2026-05-07T10-00-00",
  "steps": [
    {
      "id": 1,
      "tier": 1,
      "name": "数据提取",
      "description": "读取 CSV 文件，验证列名和数据完整性",
      "depends_on": [],
      "type": "exec",
      "subagent": "implementer",
      "available_skills": []
    },
    {
      "id": 2,
      "tier": 1,
      "name": "数据清洗",
      "description": "处理缺失值、去重、类型转换",
      "depends_on": [1],
      "type": "exec",
      "subagent": "implementer",
      "available_skills": []
    },
    {
      "id": 3,
      "tier": 1,
      "name": "统计分析",
      "description": "计算均值、中位数、标准差等统计指标",
      "depends_on": [2],
      "type": "exec",
      "subagent": "implementer",
      "available_skills": []
    },
    {
      "id": 4,
      "tier": 1,
      "name": "可视化生成",
      "description": "生成分布图、箱线图、趋势图",
      "depends_on": [2],
      "type": "exec",
      "subagent": "implementer",
      "available_skills": []
    },
    {
      "id": 5,
      "tier": 1,
      "name": "汇总报告",
      "description": "合并统计结果和图表为最终报告",
      "depends_on": [3, 4],
      "type": "exec",
      "subagent": "implementer",
      "available_skills": []
    }
  ]
}
```

## DAG 拓扑

```
Tier 1: [1 数据提取]
                ↓
Tier 2: [2 数据清洗]
               ↙     ↘
Tier 3: [3 统计分析]  [4 可视化]
               ↘     ↙
Tier 4:    [5 汇总报告]
```

## 并行执行策略

| 轮次 | 步骤 | 说明 |
|------|------|------|
| 1 | 1 | 数据提取（单步） |
| 2 | 2 | 数据清洗（单步，依赖步骤 1） |
| 3 | 3, 4 | 并行！统计分析和可视化无依赖关系 |
| 4 | 5 | 汇总报告（依赖步骤 3 和 4 都完成） |

## Subagent 分发示例 (轮次 3)

```
Agent A (步骤 3):
  → 任务: 对清洗后数据计算统计指标
  → 输入: .goo/logs/step-2-output.json
  → 交付: .goo/logs/step-3-output.json + stats.json

Agent B (步骤 4):
  → 任务: 基于清洗后数据生成可视化图表
  → 输入: .goo/logs/step-2-output.json
  → 交付: .goo/logs/step-4-output.json + charts/
```

## 上下文传递

每一步的输出包含在下游步骤的 Subagent prompt 中：

- 步骤 2 获取步骤 1 的 `output_file` 路径
- 步骤 3 和 4 获取步骤 2 的 `cleaned_data_path`
- 步骤 5 获取步骤 3 的 `stats_path` 和步骤 4 的 `charts_dir`

## 输出产物

- `.goo/logs/` — 5 个步骤日志
- `output/stats.json` — 统计结果
- `output/charts/` — 可视化图表
- `output/report.md` — 汇总报告
- `Goo-wiki/wiki/projects/etl-pipeline/` — 归档
