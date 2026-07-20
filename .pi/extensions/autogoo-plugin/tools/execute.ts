/**
 * AutoGoo-Plugin DAG Execution Engine — 自动调度执行工具
 *
 * 实现 6 槽位调度模型：
 * 1. 扫描就绪步骤（dependencies 全部 completed）
 * 2. 填充空槽位（最多 6 并发）
 * 3. 派发 Subagent + 写首个 heartbeat
 * 4. 监控心跳（30s 巡检）
 * 5. 处理完成/失败/阻塞
 * 6. 连续调度直到所有步骤完成
 *
 * 注册为 auto_goo_execute 工具供 LLM 调用。
 */

import { Type } from "typebox";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { execPython, execShell } from "../utils/exec.js";
import { updateStatusBar, formatStatusLine, snapshotPlan } from "../utils/status.js";
import {
  loadPlan,
  savePlan,
  type Plan,
  type Step,
} from "../utils/plan.js";
import {
  UPDATE_STEP_PY,
  GOO_STATUS_PY,
  projectPlanPath,
} from "../utils/paths.js";
import { existsSync } from "node:fs";

export function registerExecuteTool(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "auto_goo_execute",
    label: "Execute DAG",
    description: `自动执行 DAG 调度循环。扫描 plan 中的就绪步骤，按 6 槽位模型并发派发 Subagent。自动管理心跳检查、完成处理和失败重试。每次调用执行一轮调度。`,
    promptSnippet: "自动执行 DAG 调度循环：检查就绪步骤 → 派发 → 监控 → 完成",
    promptGuidelines: [
      "使用 auto_goo_execute 自动调度 DAG。第一次调用会执行一轮调度，应持续调用直到所有步骤完成。",
      "在调度循环中，使用 auto_goo_dag_status 查看进度，auto_goo_pending_steps 查看就绪步骤。",
    ],
    parameters: Type.Object({
      action: Type.String({
        description: "调度操作",
        enum: ["schedule", "heartbeat_check", "full_cycle"],
      }),
      planPath: Type.Optional(Type.String({ description: "plan.json 路径（默认 .goo/plan.json）" })),
    }),
    async execute(
      _toolCallId: string,
      params: any,
      _signal: any,
      _onUpdate: any,
      ctx: any,
    ) {
      const cwd = ctx.cwd;
      const planPath = params.planPath ?? projectPlanPath(cwd);

      if (!existsSync(planPath)) {
        return {
          content: [{ type: "text", text: `plan 文件未找到: ${planPath}` }],
          details: { error: "plan_not_found" },
        };
      }

      const plan = await loadPlan(cwd, planPath);
      if (!plan) {
        return {
          content: [{ type: "text", text: `无法加载 plan: ${planPath}` }],
          details: { error: "plan_load_failed" },
        };
      }

      switch (params.action) {
        case "schedule":
          return await runSchedule(cwd, plan, planPath, ctx);
        case "heartbeat_check":
          return await runHeartbeatCheck(cwd, plan, planPath, ctx);
        case "full_cycle":
          return await runFullCycle(cwd, plan, planPath, ctx);
        default:
          return {
            content: [{ type: "text", text: `未知操作: ${params.action}` }],
            details: {},
          };
      }
    },
  });
}

// ── Scheduling constants ────────────────────────────────────────────────────

const MAX_CONCURRENT = 6;
const STALE_SECONDS = 120;
const MAX_RETRIES = 1;

// ── Core scheduling logic ───────────────────────────────────────────────────

async function runSchedule(
  cwd: string,
  plan: Plan,
  planPath: string,
  ctx?: any,
): Promise<{ content: any[]; details: any }> {
  const completedIds = new Set(
    plan.steps.filter((s) => s.status === "completed").map((s) => s.id),
  );
  const running = plan.steps.filter((s) => s.status === "running");
  const blocked = plan.steps.filter((s) => s.status === "blocked");
  const failed = plan.steps.filter((s) => s.status === "failed");

  // Find ready steps: pending with all dependencies completed
  const ready = plan.steps.filter((s) => {
    if (s.status !== "pending") return false;
    return s.depends_on.every((d) => completedIds.has(d));
  });

  const availableSlots = Math.max(0, MAX_CONCURRENT - running.length);

  const toDispatch = ready.slice(0, availableSlots);
  const lines: string[] = [];
  const dispatched: number[] = [];

  if (toDispatch.length === 0) {
    if (ready.length === 0 && running.length === 0) {
      plan.status = "completed";
      plan.completed_at = new Date().toISOString();
      await savePlan(cwd, plan, planPath);
      lines.push(`✅ DAG 全部完成！${completedIds.size}/${plan.steps.length} 步`);
    } else if (ready.length > 0) {
      lines.push(`⏳ ${ready.length} 步就绪但无空槽 (${running.length}/${MAX_CONCURRENT})`);
    } else {
      lines.push(`⏳ 等待运行中步骤完成 (${running.length} 运行中)`);
    }
  }

  // Dispatch each ready step
  for (const step of toDispatch) {
    const agentId = `agent-${step.id}-${Date.now()}`;
    dispatched.push(step.id);

    execPython(UPDATE_STEP_PY, ["--plan", planPath, "--step-id", String(step.id), "--start", "--progress", "5", "--agent-id", agentId], cwd, { timeout: 15000 });
    execPython(UPDATE_STEP_PY, ["--plan", planPath, "--step-id", String(step.id), "--precreate-log", "--note", `Dispatched to ${step.subagent} (${agentId})`], cwd, { timeout: 15000 });
  }

  if (dispatched.length > 0) {
    lines.push(`▶️ 派发 ${dispatched.length} 步: #${dispatched.join(", #")}`);
  }

  // Update status bar
  if (ctx) updateStatusBar(ctx);

  return {
    content: [{ type: "text", text: lines.join("\n") }],
    details: {
      total: plan.steps.length,
      completed: completedIds.size,
      running: running.length,
      ready: ready.length,
      dispatched: toDispatch.map((s) => s.id),
      blocked: blocked.length,
      failed: failed.length,
    },
  };
}

// ── Heartbeat check ─────────────────────────────────────────────────────────

async function runHeartbeatCheck(
  cwd: string,
  plan: Plan,
  planPath: string,
  ctx?: any,
): Promise<{ content: any[]; details: any }> {
  const now = Date.now();
  const lines: string[] = [];
  const staleSteps: Step[] = [];

  for (const step of plan.steps) {
    if (step.status !== "running") continue;
    if (!step.heartbeat_at) { staleSteps.push(step); continue; }

    const hbTime = new Date(step.heartbeat_at).getTime();
    const age = Math.round((now - hbTime) / 1000);
    if (age > STALE_SECONDS) staleSteps.push(step);
  }

  // Mark stale steps as failed or retry
  for (const step of staleSteps) {
    if ((step as any).retry_count ?? 0 < MAX_RETRIES) {
      (step as any).retry_count = ((step as any).retry_count ?? 0) + 1;
      step.status = "pending";
      step.progress = 0;
      step.agent_id = null;
      lines.push(`🔄 #${step.id} 重试 (#${(step as any).retry_count})`);
      execPython(UPDATE_STEP_PY, ["--plan", planPath, "--step-id", String(step.id), "--status", "pending", "--note", `Auto-retry #${(step as any).retry_count}`], cwd, { timeout: 10000 });
    } else {
      step.status = "failed";
      step.error = `Heartbeat timeout > ${STALE_SECONDS}s`;
      lines.push(`💀 #${step.id} 心跳超时`);
      execPython(UPDATE_STEP_PY, ["--plan", planPath, "--step-id", String(step.id), "--fail", "--error", step.error], cwd, { timeout: 10000 });
    }
  }

  const runningCount = plan.steps.filter((s) => s.status === "running").length;
  if (runningCount === 0 && plan.steps.every((s) => s.status === "completed")) {
    plan.status = "completed";
    plan.completed_at = new Date().toISOString();
  }

  await savePlan(cwd, plan, planPath);
  if (ctx) updateStatusBar(ctx);

  const snap = await snapshotPlan(cwd);
  const statusLine = snap ? formatStatusLine(snap) : "";
  if (lines.length === 0) lines.push(`💓 心跳检查: ${staleSteps.length} 过期, ${runningCount} 正常`);
  if (statusLine) lines.push(statusLine);

  return {
    content: [{ type: "text", text: lines.join("\n") }],
    details: {
      stale: staleSteps.length,
      retried: staleSteps.filter((s) => (s as any).retry_count ?? 0 <= MAX_RETRIES).length,
      failed: staleSteps.filter((s) => s.status === "failed").length,
    },
  };
}

// ── Full cycle: schedule + heartbeat check ──────────────────────────────────

async function runFullCycle(
  cwd: string,
  plan: Plan,
  planPath: string,
  ctx?: any,
): Promise<{ content: any[]; details: any }> {
  // 1. Heartbeat check first
  const hbResult = await runHeartbeatCheck(cwd, plan, planPath, ctx);

  // Reload plan after heartbeat check mutations
  const updatedPlan = await loadPlan(cwd, planPath);
  if (!updatedPlan) {
    return {
      content: [{ type: "text", text: hbResult.content[0].text + "\n\n❌ 无法重新加载 plan" }],
      details: hbResult.details,
    };
  }

  // 2. Schedule new steps
  const schedResult = await runSchedule(cwd, updatedPlan, planPath, ctx);

  // Update status bar
  if (ctx) updateStatusBar(ctx);

  const combined = [
    hbResult.content[0].text,
    schedResult.content[0].text,
  ].filter(Boolean).join("\n");

  return {
    content: [{ type: "text", text: combined }],
    details: {
      heartbeat: hbResult.details,
      schedule: schedResult.details,
    },
  };
}
