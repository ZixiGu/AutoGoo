# 示例：CSV 销售数据分析工作流

展示 AutoGoo-Plugin 如何将"分析销售数据"拆解为 DAG 并执行。

## 用户任务

```
分析这份销售数据 CSV，按地区汇总销售额，并生成可视化报告
```

## 解析为 DAG

| ID | 步骤 | 依赖 | 类型 |
|----|------|------|------|
| 1 | 数据加载与清洗 | — | exec / implementer |
| 2 | 地区汇总统计 | 1 | exec / implementer |
| 3 | 生成可视化报告 | 2 | exec / implementer |

## plan.json

```json
{
  "task": "分析销售数据 CSV，按地区汇总并生成报告",
  "created_at": "2026-05-07T10-00-00",
  "steps": [
    {
      "id": 1,
      "tier": 1,
      "name": "数据加载与清洗",
      "description": "读取 CSV 文件，处理缺失值，统一日期格式",
      "depends_on": [],
      "type": "exec",
      "subagent": "implementer",
      "available_skills": []
    },
    {
      "id": 2,
      "tier": 1,
      "name": "地区汇总统计",
      "description": "按地区分组计算销售额总和、平均值、订单数",
      "depends_on": [1],
      "type": "exec",
      "subagent": "implementer",
      "available_skills": []
    },
    {
      "id": 3,
      "tier": 1,
      "name": "生成可视化报告",
      "description": "用 matplotlib 生成柱状图 + 汇总表格 [dep: matplotlib]",
      "depends_on": [2],
      "type": "exec",
      "subagent": "implementer",
      "available_skills": []
    }
  ]
}
```

## 执行过程

```
Round 1: [step-1 数据加载与清洗] — 独立执行
Round 2: [step-2 地区汇总统计] — 等待 step-1 完成
Round 3: [step-3 生成可视化报告] — 等待 step-2 完成
```

## 输出产物

- `.goo/logs/` — 每步执行日志
- 清洗后的数据文件
- 汇总统计表格
- 可视化图表
- Goo-wiki 归档笔记
