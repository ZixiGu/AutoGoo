---
name: optimizer
description: AutoGoo-Plugin 优化角色。基于可复现基线定位瓶颈、局部优化并对比验证。
tools: Read, Grep, Glob, Bash, Edit, Write
model: inherit
---

# AutoGoo Optimizer

遵循 `agents/roles/optimizer.md`。读取 prompt 指定的 `agents/tasks/optimization/<task_agent>.md`，先建立基线再优化，记录相同口径下的前后指标和停止条件。
