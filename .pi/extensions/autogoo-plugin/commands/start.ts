/**
 * AutoGoo-Plugin goo-start — 执行 DAG 计划
 *
 * 负责：加载 plan → context sync → 调度检查 → 进入执行循环
 * 注册自定义工具让 LLM 在运行时调用。
 */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { TEMPLATE_CONTEXT_SYNC_CONFIRM, TEMPLATE_WORKTREE } from "../constants.js";
import { loadPlan, savePlan, getCurrentThreadId, buildDispatchPacket, type Plan, type Step } from "../utils/plan.js";
import { REPO_ROOT, UPDATE_STEP_PY, GOO_STATUS_PY, WIKI_GRAPH_ASSIST_PY, projectPlanPath, projectThreadDir, resolveWikiDir } from "../utils/paths.js";
import { execPython } from "../utils/exec.js";
import { uiSelect, uiConfirm, uiInput } from "../utils/ui.js";
import { updateStatusBar } from "../utils/status.js";
import { existsSync } from "node:fs";
import { join } from "node:path";

// ── Global pi reference, set by setPi() from index.ts ───────────────────────
let _pi: ExtensionAPI | null = null;

export function setPi(pi: ExtensionAPI): void {
  _pi = pi;
}

export async function handleGooStart(args: string, ctx: ExtensionContext): Promise<void> {
  const cwd = ctx.cwd;
  
  // Load plan
  const plan = await loadPlan(cwd);
  if (!plan) {
    ctx.ui.notify("未找到计划。请先使用 /auto-goo:goo-plan 生成计划。", "warning");
    return;
  }

  // Check plan is approved
  if (plan.review?.status !== "approved") {
    ctx.ui.notify("计划尚未确认。请先审阅并确认计划。", "warning");
    return;
  }

  // Check for unfinished steps
  const pendingSteps = plan.steps.filter(s => s.status === "pending" || s.status === "running");
  if (pendingSteps.length === 0) {
    ctx.ui.notify("该计划的所有步骤已完成！", "success");
    return;
  }

  // Context sync check
  const syncChoice = await uiSelect(ctx, TEMPLATE_CONTEXT_SYNC_CONFIRM.header, TEMPLATE_CONTEXT_SYNC_CONFIRM.options);
  if (syncChoice === "sync") {
    // Allow user to add context updates
    const updates = await uiInput(ctx, "新增的上下文（方案、约束、验收标准等，可选）", "");
    if (updates?.trim()) {
      plan.context_digest = plan.context_digest || { found: true, decisions: [], constraints: [], acceptance_criteria: [], open_questions: [] };
      plan.context_digest.decisions.push(`[${new Date().toISOString()}] ${updates}`);
      await savePlan(cwd, plan);
    }
  }

  // Update status bar
  await updateStatusBar(ctx);

  ctx.ui.notify(`开始执行！共 ${pendingSteps.length} 个待执行步骤`, "info");

  // Send execution prompt to LLM with the registered tools
  if (_pi) {
    const pendingList = plan.steps
      .filter(s => s.status === "pending")
      .map(s => `  #${s.id} [${s.subagent}] ${s.name} — ${s.description.slice(0, 60)}`)
      .join("\n");

    _pi.sendUserMessage(
      `## AutoGoo-Plugin 执行指令\n\n` +
      `计划已确认，开始执行 DAG。共有 ${pendingSteps.length} 个待执行步骤。\n\n` +
      `### 执行方式\n` +
      `1. 使用 \`auto_goo_execute\` 全自动调度，或手动使用 \`auto_goo_dispatch\` 逐个派发\n` +
      `2. 使用 \`auto_goo_update_step\` 更新步骤状态和心跳\n` +
      `3. 使用 \`auto_goo_dag_status\` 查看进度\n\n` +
      `### 待执行步骤\n${pendingList}\n\n` +
      `请开始执行！`,
      { deliverAs: "followUp" }
    );
  }
}

// ── goo-status handler ──────────────────────────────────────────────────────

export async function handleGooStatus(args: string, ctx: ExtensionContext): Promise<void> {
  await showStatus(ctx.cwd, ctx);
}

async function showStatus(cwd: string, ctx: ExtensionContext): Promise<void> {
  if (!existsSync(GOO_STATUS_PY)) {
    ctx.ui.notify("goo-status.py 未找到", "error");
    return;
  }

  try {
    const result = execPython(GOO_STATUS_PY, ["--plan", projectPlanPath(cwd)], cwd);
    ctx.ui.notify((result.stdout || "状态加载中...").slice(0, 500), "info");
    if (result.stderr) ctx.ui.notify(result.stderr.slice(0, 200), "warning");
  } catch (err: any) {
    ctx.ui.notify(`状态查询失败: ${err.message}`, "error");
  }
}

// ── Custom tools registration ───────────────────────────────────────────────

export function registerExecutionTools(pi: any): void {
  // Tool: auto_goo_update_step
  pi.registerTool({
    name: "auto_goo_update_step",
    label: "Update Step",
    description: "更新 DAG 步骤状态、进度、心跳。Subagent 和主 Agent 都可通过此工具更新步骤状态。",
    promptSnippet: "更新 DAG 步骤状态、进度和心跳",
    promptGuidelines: [
      "使用 auto_goo_update_step 更新步骤状态：--start 开始步骤，--heartbeat 更新进度，--complete 完成，--fail 标记失败",
      "heartbeat 必须带 --note 描述进展，空 heartbeat 无效",
    ],
    parameters: Type.Object({
      stepId: Type.Integer({ description: "步骤 ID" }),
      action: Type.String({
        description: "操作类型",
        enum: ["start", "heartbeat", "complete", "fail", "block"],
      }),
      progress: Type.Optional(Type.Integer({ description: "进度 0-100" })),
      note: Type.Optional(Type.String({ description: "进展描述（heartbeat 必填）" })),
      error: Type.Optional(Type.String({ description: "失败原因" })),
      agentId: Type.Optional(Type.String({ description: "Agent ID" })),
    }),
    async execute(_toolCallId: string, params: any, _signal: any, _onUpdate: any, ctx: any) {
      const cwd = ctx.cwd;
      const args = [
        UPDATE_STEP_PY,
        "--plan", projectPlanPath(cwd),
        "--step-id", String(params.stepId),
      ];

      switch (params.action) {
        case "start":
          args.push("--start");
          if (params.agentId) { args.push("--agent-id", params.agentId); }
          if (params.progress !== undefined) { args.push("--progress", String(params.progress)); }
          break;
        case "heartbeat":
          args.push("--heartbeat");
          if (params.progress !== undefined) { args.push("--progress", String(params.progress)); }
          if (params.note) { args.push("--note", params.note); }
          break;
        case "complete":
          args.push("--complete");
          break;
        case "fail":
          args.push("--fail");
          if (params.error) { args.push("--error", params.error); }
          break;
        case "block":
          args.push("--block");
          if (params.error) { args.push("--error", params.error); }
          break;
      }

      try {
        const result = execPython(args[0], args.slice(1), cwd, { timeout: 30000 });
        await updateStatusBar(ctx);
        return {
          content: [{ type: "text", text: result.stdout || "步骤已更新" }],
          details: { stepId: params.stepId, action: params.action },
        };
      } catch (err: any) {
        await updateStatusBar(ctx);
        return {
          content: [{ type: "text", text: `更新失败: ${err.message}` }],
          details: { stepId: params.stepId, action: params.action, error: err.message },
          isError: true,
        };
      }
    },
  });

  // Tool: auto_goo_dag_status
  pi.registerTool({
    name: "auto_goo_dag_status",
    label: "DAG Status",
    description: "查看 DAG 计划的状态仪表盘，包括所有步骤的进度、心跳和告警。",
    promptSnippet: "查看 DAG 步骤的状态仪表盘",
    parameters: Type.Object({}),
    async execute(_toolCallId: string, _params: any, _signal: any, _onUpdate: any, ctx: any) {
      const cwd = ctx.cwd;
      try {
        const result = execPython(GOO_STATUS_PY, ["--plan", projectPlanPath(cwd)], cwd);
        return {
          content: [{ type: "text", text: result.stdout || "无状态数据" }],
          details: { output: result.stdout },
        };
      } catch (err: any) {
        return {
          content: [{ type: "text", text: `状态查询失败: ${err.message}` }],
          details: { error: err.message },
        };
      }
    },
  });

  // Tool: auto_goo_dispatch
  pi.registerTool({
    name: "auto_goo_dispatch",
    label: "Dispatch Subagent",
    description: "派发 Subagent 执行 DAG 步骤。通过向对话发送用户消息触发模型处理该步骤。",
    promptSnippet: "派发 Subagent 执行 DAG 步骤",
    promptGuidelines: [
      "使用 auto_goo_dispatch 将步骤派发给 Subagent 执行。派发前先调用 auto_goo_update_step --start 写首个 heartbeat。",
      "派发完成后 Subagent 的第一动作是调用 auto_goo_update_step --heartbeat --progress 15 --note '<已开工>'",
    ],
    parameters: Type.Object({
      stepId: Type.Integer({ description: "步骤 ID" }),
      role: Type.String({
        description: "Subagent 角色",
        enum: ["researcher", "implementer", "optimizer", "evaluator", "reviewer", "auditor", "recorder"],
      }),
      task: Type.String({ description: "步骤任务描述" }),
      taskAgent: Type.Optional(Type.String({
        description: "具体任务 agent",
        enum: ["document-analyst", "feature-builder", "test-runner", "code-reviewer", "evidence-auditor", "wiki-curator"],
      })),
      stepType: Type.Optional(Type.String({
        description: "步骤类型（影响默认 wiki_paths / memory_layer）",
        enum: ["research", "exec", "optimize", "eval", "review", "audit", "archive"],
      })),
    }),
    async execute(_toolCallId: string, params: any, _signal: any, _onUpdate: any, ctx: any) {
      const cwd = ctx.cwd;

      // 1. Pre-create log skeleton via update-step.py
      try {
        const planPath = projectPlanPath(cwd);
        execPython(
          UPDATE_STEP_PY,
          ["--plan", planPath, "--step-id", String(params.stepId), "--precreate-log", "--note", `Dispatched to ${params.role}`],
          cwd,
          { timeout: 15000 },
        );
      } catch {}

      // 2. Build Subagent prompt
      const rolePrompt = getRolePrompt(params.role);
      const taskPrompt = params.taskAgent ? getTaskAgentPrompt(params.taskAgent) : "";

      // 2.1 Compute dispatch packet (on-demand wiki + memory layer)
      //    镜像 Claude Code execution-engine.md 的 wiki_paths 注入逻辑。
      //    主 Agent 调用本工具时,wiki_graph_packet_path 还没生成;
      //    本函数只计算路径,实际生成由主 Agent 派发前用 wiki-graph-assist.py 完成。
      const activeThreadId = await getCurrentThreadId(cwd);
      const projectSlug =
        (await getCurrentThreadId(cwd))  // touch to ensure no dead-code warning
          ? require("node:path").basename(cwd) || "autogoo-plugin"
          : "autogoo-plugin";
      // 简化:sl 直接走 cwd basename;若 plan 提供 override 可再扩展
      const packet = buildDispatchPacket(
        { id: params.stepId, type: params.stepType || "exec" },
        projectSlug,
        activeThreadId || "current",
      );

      // 2.2 Generate wiki graph packet (实际调用 wiki-graph-assist.py)
      //     失败 fallback:只传 path,不阻塞 dispatch。
      let packetGenerated = false;
      try {
        const wikiDir = await resolveWikiDir(cwd);
        const searchPathArgs = packet.wiki_paths.flatMap((p: string) => ["--search-path", p]);
        const r = execPython(
          WIKI_GRAPH_ASSIST_PY,
          [
            "--wiki-dir", wikiDir,
            "--project-slug", projectSlug,
            "--query", params.task || `step ${params.stepId} dispatch`,
            "--title", `step-${params.stepId}-dispatch`,
            ...searchPathArgs,
            "--max-pages", "12",
            "--format", "md",
          ],
          cwd,
          { timeout: 30000 },  // < 30s 双重约束
        );
        if (r.exitCode === 0 && r.stdout) {
          const fs = await import("node:fs/promises");
          const fullPath = join(cwd, packet.wiki_graph_packet_path);
          await fs.mkdir(join(fullPath, ".."), { recursive: true });
          await fs.writeFile(fullPath, r.stdout);
          packetGenerated = true;
        } else {
          console.warn(`[AutoGoo-Plugin] wiki-graph-assist.py 失败 (exit=${r.exitCode}): ${(r.stderr || "").slice(0, 200)}`);
        }
      } catch (e: any) {
        console.warn(`[AutoGoo-Plugin] wiki-graph-assist.py 异常: ${(e?.message ?? String(e)).slice(0, 200)}`);
      }

      const prompt = [
        `## AutoGoo-Plugin Subagent: ${params.role}`,
        ``,
        rolePrompt,
        taskPrompt ? `\n${taskPrompt}\n` : "",
        `## 任务`,
        ``,
        params.task,
        ``,
        `## 按需读取 wiki(对齐 SKILL.md "按需调用原则")`,
        `- 本 step 的 wiki_paths glob(只读这些,不要"读全部 wiki"):`,
        `  ${packet.wiki_paths.join("\n  ")}`,
        packetGenerated
          ? `- 紧凑 graph packet 已生成在 ${packet.wiki_graph_packet_path};优先 Read 它代替自行 grep/glob 全量扫描`
          : `- ⚠️ graph packet 生成失败(超时或 wiki-graph-assist.py 错误),fallback 到按 wiki_paths glob 自行 Read(遵守字符预算 < 20k)`,
        `- 单次 Read/Grep 受字符预算 (< 20k) + 超时 (< 30s) 双重约束;超出时用 Read + limit/offset 或 Grep -n`,
        `- memory_layer 默认 ${packet.memory_layer};L0 原始日志、L3 项目画像只按 step 显式需要才读`,
        `- 跨 step 引用用 [[Wikilink]] 按需点开;不要 Read 整篇 wiki 笔记`,
        ``,
        `## 执行要求`,
        `1. 第一件事：调用 auto_goo_update_step --heartbeat --progress 15 --note "已开工"`,
        `2. 每完成一个里程碑调用 auto_goo_update_step --heartbeat 更新进度`,
        `3. 完成后调用 auto_goo_update_step --complete`,
        `4. 失败时调用 auto_goo_update_step --fail --error "<原因>"`,
        `5. 在 step log 中记录关键决策、产物路径和验证结果`,
        `6. 不要扩大范围：只完成当前步骤的任务`,
      ].filter(Boolean).join("\n");

      // 3. Send user message to trigger agent
      pi.sendUserMessage(prompt, { deliverAs: "followUp" });
      await updateStatusBar(ctx);

      return {
        content: [{ type: "text", text: `已派发 step ${params.stepId} 给 ${params.role}${params.taskAgent ? ` (${params.taskAgent})` : ""}` }],
        details: { stepId: params.stepId, role: params.role, taskAgent: params.taskAgent },
      };
    },
  });

  // Tool: auto_goo_prepare_dispatch
  pi.registerTool({
    name: "auto_goo_prepare_dispatch",
    label: "Prepare Dispatch",
    description: "为派发 Subagent 做准备：更新 step 状态为 running、写首个 heartbeat、创建 log 骨架。",
    promptSnippet: "为派发 Subagent 做准备：start step + precreate log",
    parameters: Type.Object({
      stepId: Type.Integer({ description: "步骤 ID" }),
      role: Type.String({ description: "Subagent 角色" }),
      agentId: Type.Optional(Type.String({ description: "Agent ID" })),
    }),
    async execute(_toolCallId: string, params: any, _signal: any, _onUpdate: any, ctx: any) {
      const cwd = ctx.cwd;
      const planPath = projectPlanPath(cwd);
      const stepId = String(params.stepId);
      const agentId = params.agentId || `agent-${params.stepId}-${Date.now()}`;

      const results: string[] = [];

      // Start step
      try {
        const r1 = execPython(
          UPDATE_STEP_PY,
          ["--plan", planPath, "--step-id", stepId, "--start", "--progress", "5", "--agent-id", agentId],
          cwd,
          { timeout: 15000 },
        );
        results.push(`start: ${r1.stdout?.slice(0, 100)}`);
      } catch (err: any) {
        results.push(`start error: ${err.message}`);
      }

      // Precreate log
      try {
        const r2 = execPython(
          UPDATE_STEP_PY,
          ["--plan", planPath, "--step-id", stepId, "--precreate-log", "--note", `Main Agent preparing dispatch to ${params.role} (${agentId})`],
          cwd,
          { timeout: 15000 },
        );
        results.push(`log: ${r2.stdout?.slice(0, 100)}`);
      } catch (err: any) {
        results.push(`log error: ${err.message}`);
      }

      await updateStatusBar(ctx);
      return {
        content: [{ type: "text", text: `Prepared step ${params.stepId}:\n${results.join("\n")}` }],
        details: { stepId: params.stepId, agentId, results },
      };
    },
  });

  // Tool: auto_goo_pending_steps
  pi.registerTool({
    name: "auto_goo_pending_steps",
    label: "Pending Steps",
    description: "查看当前 plan 中待执行的就绪步骤（所有依赖已完成的 pending 步骤）。",
    promptSnippet: "查看 DAG 中可执行的就绪步骤列表",
    parameters: Type.Object({}),
    async execute(_toolCallId: string, _params: any, _signal: any, _onUpdate: any, ctx: any) {
      const cwd = ctx.cwd;
      const plan = await loadPlan(cwd);
      if (!plan) {
        return { content: [{ type: "text", text: "未找到 plan" }], details: {} };
      }

      const completedIds = new Set(
        plan.steps.filter(s => s.status === "completed").map(s => s.id),
      );

      const pending = plan.steps.filter(s => {
        if (s.status !== "pending") return false;
        return s.depends_on.every(d => completedIds.has(d));
      });

      if (pending.length === 0) {
        return { content: [{ type: "text", text: "没有就绪步骤。所有步骤已完成或依赖未满足。" }], details: {} };
      }

      const lines = pending.map(s =>
        `  #${s.id} [${s.subagent}] ${s.name} — ${s.description.slice(0, 60)}`
      );
      return {
        content: [{ type: "text", text: `就绪步骤 (${pending.length}):\n${lines.join("\n")}` }],
        details: { pending: pending.map(s => ({ id: s.id, name: s.name, subagent: s.subagent })) },
      };
    },
  });
}

// ── Prompt helpers ──────────────────────────────────────────────────────────

function getRolePrompt(role: string): string {
  const prompts: Record<string, string> = {
    researcher: `你是 AutoGoo-Plugin Researcher。你的任务是深入调研和资料收集。
- 搜索相关文档、论文、代码库和最佳实践
- 整理调研结果，形成结构化报告
- 标注信息来源和可信度
- 提出可行的技术方案和建议`,
    implementer: `你是 AutoGoo-Plugin Implementer。你的任务是编码实现。
- 严格按照 step 描述和验收标准实现
- 编写可读、可测试、可维护的代码
- 遵循项目已有的代码风格和架构约定
- 实现完成后运行验证命令确认正确性`,
    optimizer: `你是 AutoGoo-Plugin Optimizer。你的任务是性能优化。
- 先建立指标和基线，再做改动
- 使用 profiler 定位瓶颈
- 每次优化后对比基线，记录提升幅度
- 达到目标或边际收益过低时停止`,
    evaluator: `你是 AutoGoo-Plugin Evaluator。你的任务是评测和验证。
- 定义评测指标和数据集
- 运行评测并记录结果
- 与基线对比，生成评测报告
- 分析失败案例，提出改进建议`,
    reviewer: `你是 AutoGoo-Plugin Reviewer。你的任务是代码审查。
- 检查代码正确性、安全性和性能
- 验证是否满足验收标准
- 指出潜在问题并给出改进建议
- 输出审查报告`,
    auditor: `你是 AutoGoo-Plugin Auditor。你的任务是证据审计。
- 检查步骤产物是否完整
- 验证日志、产物路径和验收结果的一致性
- 检查是否遵循了项目约束和规范
- 输出审计报告`,
    recorder: `你是 AutoGoo-Plugin Recorder。你的任务是归档和知识沉淀。
- 将任务目标、计划、关键证据和产物归档到 Goo-wiki
- 补充 Wikilink/backlink 关系
- 记录可复用的经验、命令、路径和决策
- 更新 log.md 和项目入口页`,
  };
  return prompts[role] || `你是 AutoGoo-Plugin ${role}。请按照步骤描述完成任务。`;
}

function getTaskAgentPrompt(taskAgent: string): string {
  const prompts: Record<string, string> = {
    "document-analyst": `你擅长分析文档、论文和结构化文本。提取关键信息、约束和验收标准。`,
    "feature-builder": `你擅长从零开始构建新功能模块。编写完整的实现代码并添加必要的测试。`,
    "test-runner": `你擅长运行测试和验证功能正确性。分析失败原因并补充测试用例。`,
    "code-reviewer": `你擅长审查代码质量和安全。检查常见安全漏洞和性能问题。`,
    "evidence-auditor": `你擅长审计和验证执行证据。检查产物的完整性和一致性。`,
    "wiki-curator": `你擅长 Obsidian 知识库的维护和归档。创建符合规范的归档页面并维护链接关系。`,
  };
  return prompts[taskAgent] || "";
}


