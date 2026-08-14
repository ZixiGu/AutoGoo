/**
 * Demo: Subagent Dispatch via Message Injection
 *
 * 验证 pi 插件分发 Subagent 的最小示例。
 * 机制（与 AutoGoo-Plugin auto_goo_dispatch 相同）：
 *
 *   1. 工具 execute() 里 pi.sendUserMessage(prompt, { deliverAs: "followUp" })
 *   2. 返回 { terminate: true } 结束当前 turn
 *   3. 外层循环消费 followUp 队列 → LLM 以独立 turn 执行 Subagent 任务
 *   4. Subagent 完成后用 SUBAGENT_DONE 标记返回
 *
 * 用法：
 *   /demo-subagent <task>            # 命令触发（idle 时直接注入）
 *   demo_subagent_dispatch 工具      # 工具触发（streaming 时 followUp + terminate）
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const SUBAGENT_MARKER = "SUBAGENT_DONE";

/** 构建 Subagent 任务 prompt（角色 + 任务 + 返回契约） */
function buildSubagentPrompt(task: string): string {
  return [
    `## 演示 Subagent（消息注入机制）`,
    ``,
    `你是被主 Agent 通过 pi.sendUserMessage 派发的 Subagent，请执行：`,
    ``,
    task,
    ``,
    `## 返回契约`,
    `- 只完成本任务，不要扩大范围`,
    `- 完成后以 "${SUBAGENT_MARKER}: <结构化结果>" 开头汇报`,
  ].join("\n");
}

export default function (pi: ExtensionAPI) {
  // ── 1. 命令触发：/demo-subagent <task> ──────────────────────────────────
  // idle 时 sendUserMessage 立即发送并触发新 turn
  pi.registerCommand("demo-subagent", {
    description: "注入一个 Subagent 任务（消息注入机制演示）",
    handler: async (args, ctx) => {
      const task = args.trim() || "用一句话解释什么是 DAG，并给出一个实际例子。";
      ctx.ui.notify(`[demo] 注入 Subagent 任务: ${task.slice(0, 60)}...`, "info");
      pi.sendUserMessage(buildSubagentPrompt(task));
    },
  });

  // ── 2. 工具触发：demo_subagent_dispatch（与 auto_goo_dispatch 同机制）──
  pi.registerTool({
    name: "demo_subagent_dispatch",
    label: "Demo Subagent Dispatch",
    description: "通过消息注入派发一个演示 Subagent。sendUserMessage(followUp) + terminate:true，验证 turn 交接机制。",
    promptSnippet: "派发演示 Subagent 验证消息注入机制",
    parameters: Type.Object({
      task: Type.String({ description: "要交给 Subagent 执行的任务" }),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      // 1) 任务消息入队（等当前 turn 所有工具完成后投递）
      pi.sendUserMessage(buildSubagentPrompt(params.task), { deliverAs: "followUp" });

      // 2) 结束当前 turn → 外层循环消费 followUp → Subagent 独立执行
      return {
        content: [{ type: "text", text: `[demo] 已派发 Subagent 任务: ${params.task.slice(0, 60)}...` }],
        details: { task: params.task, deliverAs: "followUp", terminate: true },
        terminate: true,
      };
    },
  });

  // ── 3. 观察 Subagent 返回标记 ───────────────────────────────────────────
  pi.on("input", async (event) => {
    const text = event.text?.trim?.() ?? "";
    if (!text.startsWith(SUBAGENT_MARKER)) return { action: "continue" };
    // 这里可以截获 Subagent 的返回结果做后处理（归档、校验等）
    return { action: "continue" };
  });
}
