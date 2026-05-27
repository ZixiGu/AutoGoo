# 优化迭代工作流示例：JSON 序列化性能优化

## 任务描述

优化 Python JSON 序列化性能，要求处理 10 万条记录时延迟 < 2s。

## 解析结果 (plan.json)

```json
{
  "task": "优化 Python JSON 序列化性能",
  "created_at": "2026-05-07T10-00-00",
  "steps": [
    {
      "id": 1,
      "tier": 1,
      "name": "搜索评价指标",
      "description": "WebSearch 搜索 JSON 序列化基准测试标准指标",
      "depends_on": [],
      "type": "exec",
      "subagent": "research",
      "available_skills": []
    },
    {
      "id": 2,
      "tier": 1,
      "name": "实现基线版本",
      "description": "标准 json.dumps 实现，100k 条数据评测 3 次取平均",
      "depends_on": [1],
      "type": "exec",
      "subagent": "implementer",
      "available_skills": []
    },
    {
      "id": 3,
      "tier": 1,
      "name": "基线评测",
      "description": "执行基线评测，记录延迟和内存",
      "depends_on": [2],
      "type": "eval",
      "subagent": "evaluator",
      "available_skills": []
    },
    {
      "id": 4,
      "tier": 1,
      "name": "瓶颈分析",
      "description": "cProfile 分析热点，定位瓶颈",
      "depends_on": [2, 3],
      "type": "exec",
      "subagent": "optimizer",
      "available_skills": []
    },
    {
      "id": 5,
      "tier": 1,
      "name": "实现优化",
      "description": "基于瓶颈分析结果进行优化（orjson / ujson / 自定义）",
      "depends_on": [4],
      "type": "optimize",
      "subagent": "optimizer",
      "available_skills": []
    },
    {
      "id": 6,
      "tier": 1,
      "name": "优化评测对比",
      "description": "同基线指标评测优化版本，对比提升",
      "depends_on": [5],
      "type": "eval",
      "subagent": "evaluator",
      "available_skills": []
    }
  ]
}
```

## DAG 执行顺序

```
Tier 1: [1]                    Tier 2: [2, 3]         Tier 3: [4]
                                       ↓
Tier 4: [5]                    Tier 5: [6]
```

- 步骤 1 (搜索指标) → 步骤 2 (基线) + 步骤 3 (评测)
- 步骤 4 (瓶颈分析) 依赖步骤 2 和 3
- 步骤 5 (优化) 依赖步骤 4
- 步骤 6 (对比) 依赖步骤 5

## 优化终止判断

| 轮次 | 基线 | 优化后 | 提升 | 继续? |
|------|------|--------|------|-------|
| 1 | 3.2s | 1.8s | 43.7% | 是 (>=20%) |
| 2 | 1.8s | 1.6s | 11.1% | 是 (<20% 但 >=5%) |
| 3 | 1.6s | 1.55s | 3.1% | 否 (<5%) |

## 输出产物

- `.goo/logs/step-*.log` — 每步执行日志
- `.goo/benchmark-results.json` — 评测数据
- `Goo-wiki/wiki/projects/json-optimization/` — 归档笔记
