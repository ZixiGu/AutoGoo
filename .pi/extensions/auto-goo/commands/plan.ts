/**
 * AutoGoo goo-plan — 生成 DAG 执行计划
 *
 * 负责：thread 检查 → wiki 召回 → 输入识别 → goal 抽取 → DAG 拆解
 * → 并行审计 → context 固化 → plan 落盘 → 用户确认
 *
 * This is the core "value" command. It guides the LLM through planning
 * by invoking Python scripts and presenting structured UI.
 */

import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  TEMPLATE_THREAD_ACTION,
  TEMPLATE_PLAN_REVIEW_START,
  TEMPLATE_CONTEXT_SYNC_CONFIRM,
  TEMPLATE_REMOTE_RESOURCE_USAGE,
} from "../constants.js";
import {
  loadPlan,
  savePlan,
  archiveOldPlan,
  getCurrentThreadId,
  setCurrentThreadId,
  generateThreadId,
  generateTimestamp,
  loadThreadMeta,
  saveThreadMeta,
  updateThreadsIndex,
  type Plan,
  type Step,
  type Goal,
} from "../utils/plan.js";
import {
  REPO_ROOT,
  RESOLVE_ROOT_SH,
  REMOTE_RESOURCES_PY,
  WIKI_GRAPH_ASSIST_PY,
  projectPlanPath,
  projectBrainstormPath,
  projectThreadsDir,
  projectThreadDir,
} from "../utils/paths.js";
import { existsSync } from "node:fs";
import { mkdir, writeFile, readFile, copyFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { execShell, execPython } from "../utils/exec.js";
import { uiSelect } from "../utils/ui.js";

export async function handleGooPlan(taskDescription: string, ctx: ExtensionContext): Promise<void> {
  const cwd = ctx.cwd;
  const pi = ctx as any;

  if (!taskDescription?.trim()) {
    ctx.ui.notify("请输入任务描述。例如：/auto-goo:goo-plan 实现一个用户登录功能", "warning");
    return;
  }

  // ── Step 1: Check existing plan / thread ───────────────────────────────────
  const { threadAction, threadId } = await resolveThread(cwd, ctx);
  if (threadAction === "cancel") {
    ctx.ui.notify("已取消规划。", "info");
    return;
  }

  const activeThreadId = threadId || generateThreadId();
  const isNewThread = threadAction === "new";

  // ── Step 2: Wiki recall ───────────────────────────────────────────────────
  ctx.ui.notify("正在召回 Goo-wiki 经验...", "info");
  const wikiContext = await recallWiki(cwd, taskDescription, ctx);

  // ── Step 3: Check for brainstorm reference ─────────────────────────────────
  let brainstormGoals: Goal[] = [];
  const brainstormRef = taskDescription.match(/--brainstorm(?:-id)?\s+(\S+)/);
  if (brainstormRef) {
    const bs = await loadBrainstorm(cwd, brainstormRef[1]);
    if (bs?.candidate_goals) {
      brainstormGoals = bs.candidate_goals.map((g: any, i: number) => ({
        id: `g${i + 1}`,
        name: g.name || `Goal ${i + 1}`,
        description: g.why || "",
        priority: i + 1,
        status: "pending",
        acceptance_criteria: g.acceptance_criteria || [],
        outputs: g.expected_output ? [g.expected_output] : [],
        depends_on: [],
      }));
    }
  }

  // ── Step 4: Generate plan structure ────────────────────────────────────────
  ctx.ui.notify("正在生成 DAG 计划...", "info");
  const plan = await generatePlan(cwd, taskDescription, wikiContext, brainstormGoals, activeThreadId, isNewThread, ctx);

  if (!plan) {
    ctx.ui.notify("计划生成失败，请重试。", "error");
    return;
  }

  // ── Step 5: Remote resource check ─────────────────────────────────────────
  await checkRemoteResources(cwd, plan, ctx);

  // ── Step 6: Save plan ──────────────────────────────────────────────────────
  // Create thread directories
  const threadDir = join(projectThreadDir(cwd, activeThreadId));
  await mkdir(threadDir, { recursive: true });
  await mkdir(join(threadDir, "logs"), { recursive: true });
  await mkdir(join(threadDir, "artifacts"), { recursive: true });

  // Save plan
  plan.thread = {
    id: activeThreadId,
    plan_path: join(threadDir, "plan.json"),
    logs_dir: join(threadDir, "logs"),
    artifacts_dir: join(threadDir, "artifacts"),
  };
  plan.review = { status: "pending_user_review" };
  await savePlan(cwd, plan, join(threadDir, "plan.json"));

  // Save thread meta
  await saveThreadMeta(cwd, {
    id: activeThreadId,
    status: "pending",
    created_at: plan.created_at,
    plan_path: join(threadDir, "plan.json"),
    logs_dir: join(threadDir, "logs"),
    artifacts_dir: join(threadDir, "artifacts"),
    task: plan.task,
  });

  // Update current thread and index
  await setCurrentThreadId(cwd, activeThreadId);
  await updateThreadsIndex(cwd);

  // Also save compat plan.json
  await savePlan(cwd, plan);

  // ── Step 7: Show plan in editor and get confirmation ───────────────────────
  // Show plan summary in the editor so user can see the full content
  const planSummary = formatPlanSummary(plan);
  ctx.ui.setEditorText(
    `📋 计划已生成，请审阅并确认：\n\n${planSummary}\n\n` +
    `─────────────────\n` +
    `请在下方选择操作：`
  );
  ctx.ui.notify(`📋 计划已生成！共 ${plan.steps.length} 步，请在编辑器中查看并确认。`, "info");

  const reviewChoice = await uiSelect(ctx, TEMPLATE_PLAN_REVIEW_START.header, TEMPLATE_PLAN_REVIEW_START.options);

  if (reviewChoice === "cancel") {
    ctx.ui.setEditorText("");
    ctx.ui.notify("计划已保存，等待后续使用。", "info");
    return;
  }

  if (reviewChoice === "modify") {
    ctx.ui.setEditorText(
      `请修改以下计划，然后重新运行 /goo-plan：\n\n${planSummary}`
    );
    ctx.ui.notify("请在编辑器中修改计划后重新运行 /goo-plan。", "info");
    return;
  }

  // confirm: approve plan
  if (brainstormGoals.length > 0) {
    await archiveBrainstorm(cwd, brainstormRef![1], activeThreadId, ctx);
  }

  plan.review = { status: "approved" };
  await savePlan(cwd, plan, join(threadDir, "plan.json"));
  await savePlan(cwd, plan);
  ctx.ui.setEditorText("");

  ctx.ui.notify(`✅ 计划已确认！线程 ID: ${activeThreadId}`, "success");
  ctx.ui.notify("使用 /goo-start 执行，或 /goo-status 查看详情", "info");
}

// ── Thread resolution ──────────────────────────────────────────────────────

async function resolveThread(cwd: string, ctx: ExtensionContext): Promise<{ threadAction: string; threadId: string | null }> {
  const currentPlan = await loadPlan(cwd);
  if (!currentPlan) return { threadAction: "new", threadId: null };

  // Check if any step is not completed
  const hasUnfinished = currentPlan.steps?.some(s => s.status !== "completed");
  if (!hasUnfinished) return { threadAction: "new", threadId: null };

  const unfinishedCount = currentPlan.steps.filter(s => s.status !== "completed").length;
  const currentThreadId = await getCurrentThreadId(cwd);

  ctx.ui.notify(`当前 thread 还有 ${unfinishedCount} 个未完成步骤。`, "warning");

  const choice = await uiSelect(ctx, TEMPLATE_THREAD_ACTION.header, TEMPLATE_THREAD_ACTION.options);
  if (!choice || choice === "cancel") return { threadAction: "cancel", threadId: null };
  if (choice === "continue") return { threadAction: "continue", threadId: currentThreadId };

  // "new": archive old plan
  await archiveOldPlan(cwd, currentPlan);
  return { threadAction: "new", threadId: null };
}

// ── Wiki recall ────────────────────────────────────────────────────────────

interface WikiContext {
  found: boolean;
  sources: string[];
  reused_knowledge: string[];
}

async function recallWiki(cwd: string, task: string, ctx: ExtensionContext): Promise<WikiContext> {
  const wikiScript = join(REPO_ROOT, "skills/auto-goo/scripts/wiki-graph-assist.py");
  if (!existsSync(wikiScript)) {
    return { found: false, sources: [], reused_knowledge: [] };
  }

  try {
    const result = execPython(wikiScript, ["--compact", "--query", task], cwd);
    const lines = result.stdout?.split("\n").filter(Boolean) || [];
    return {
      found: lines.length > 2,
      sources: lines.filter(l => l.startsWith("source:")).map(l => l.slice(7).trim()),
      reused_knowledge: lines.filter(l => !l.startsWith("source:") && !l.startsWith("[")),
    };
  } catch {
    return { found: false, sources: [], reused_knowledge: [] };
  }
}

// ── Brainstorm loading ──────────────────────────────────────────────────────

async function loadBrainstorm(cwd: string, brainstormId?: string): Promise<any> {
  try {
    const p = projectBrainstormPath(cwd);
    const raw = await readFile(p, "utf-8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

async function archiveBrainstorm(cwd: string, brainstormId: string, threadId: string, ctx: ExtensionContext): Promise<void> {
  // Archive brainstorm to Goo-wiki
  ctx.ui.notify("正在归档 Brainstorm...", "info");
}

// ── Plan generation ─────────────────────────────────────────────────────────

async function generatePlan(
  cwd: string,
  task: string,
  wikiContext: WikiContext,
  brainstormGoals: Goal[],
  threadId: string,
  isNewThread: boolean,
  ctx: ExtensionContext,
): Promise<Plan | null> {
  const now = generateTimestamp();

  // Build goals
  const goals: Goal[] = brainstormGoals.length > 0 ? brainstormGoals : [
    {
      id: "g1",
      name: "主要目标",
      description: task,
      priority: 1,
      status: "pending",
      acceptance_criteria: ["任务完成"],
      outputs: [],
      depends_on: [],
    },
  ];

  // Build initial steps (LLM will refine these via tools)
  const steps: Step[] = [
    {
      id: 1,
      goal_ids: goals.map(g => g.id),
      tier: 1,
      name: "任务分析与方案设计",
      description: "分析任务需求，确定技术方案和实现路径",
      depends_on: [],
      type: "research",
      subagent: "researcher",
      task_agent: "document-analyst",
      available_skills: [],
      status: "pending",
      progress: 0,
      inputs: [],
      outputs: [],
      allowed_read_paths: ["."],
      allowed_write_paths: [".goo/"],
      validation: "输出方案文档或 design.md",
      risk_level: "low",
      requires_user_confirm: false,
      agent_id: null,
      heartbeat_at: null,
    },
    {
      id: 2,
      goal_ids: goals.map(g => g.id),
      tier: 2,
      name: "实现与开发",
      description: "根据方案设计进行编码实现",
      depends_on: [1],
      type: "exec",
      subagent: "implementer",
      task_agent: "feature-builder",
      available_skills: [],
      status: "pending",
      progress: 0,
      inputs: [],
      outputs: [],
      allowed_read_paths: ["."],
      allowed_write_paths: ["."],
      validation: "代码编写完成，能通过编译/语法检查",
      risk_level: "medium",
      requires_user_confirm: false,
      agent_id: null,
      heartbeat_at: null,
    },
    {
      id: 3,
      goal_ids: goals.map(g => g.id),
      tier: 3,
      name: "测试验证",
      description: "运行测试，验证功能正确性",
      depends_on: [2],
      type: "eval",
      subagent: "evaluator",
      task_agent: "test-runner",
      available_skills: [],
      status: "pending",
      progress: 0,
      inputs: [],
      outputs: [],
      allowed_read_paths: ["."],
      allowed_write_paths: [".goo/"],
      validation: "测试通过",
      risk_level: "medium",
      requires_user_confirm: false,
      agent_id: null,
      heartbeat_at: null,
    },
    {
      id: 4,
      goal_ids: goals.map(g => g.id),
      tier: 4,
      name: "归档到 Goo-wiki",
      description: "将任务目标、计划、关键证据、产物路径、验证结果和可复用经验归档到 Goo-wiki",
      depends_on: [3],
      type: "archive",
      subagent: "recorder",
      task_agent: "wiki-curator",
      available_skills: [],
      status: "pending",
      progress: 0,
      inputs: [],
      outputs: [],
      allowed_read_paths: [".goo/"],
      allowed_write_paths: [],
      validation: "归档页存在",
      risk_level: "low",
      requires_user_confirm: false,
      agent_id: null,
      heartbeat_at: null,
    },
  ];

  return {
    task,
    goals,
    status: "pending",
    created_at: now,
    steps,
    wiki_context: wikiContext,
    context_digest: {
      found: false,
      decisions: [],
      constraints: [],
      acceptance_criteria: [],
      open_questions: [],
    },
    review: { status: "pending_user_review" },
  };
}

// ── Remote resource check ───────────────────────────────────────────────────

async function checkRemoteResources(cwd: string, plan: Plan, ctx: ExtensionContext): Promise<void> {
  // Check if servers configured
  const configPath = join(cwd, ".goo/config.json");
  if (!existsSync(configPath)) return;

  try {
    const raw = await readFile(configPath, "utf-8");
    const config = JSON.parse(raw);
    if (!config.servers?.length) return;

    // Probe remote resources
    const probeScript = join(REPO_ROOT, "skills/auto-goo/scripts/remote-resources.py");
    let probeResult = "";
    if (existsSync(probeScript)) {
      try {
        const result = execPython(probeScript, ["--probe"], cwd);
        probeResult = result.stdout || "";
      } catch {}
    }

    ctx.ui.notify(`检测到远程服务器: ${config.servers.map((s: any) => s.name).join(", ")}`, "info");
    if (probeResult) ctx.ui.notify(probeResult.slice(0, 300), "info");

    const choice = await uiSelect(ctx, TEMPLATE_REMOTE_RESOURCE_USAGE.header, TEMPLATE_REMOTE_RESOURCE_USAGE.options);
    if (choice === "remote") {
      // Mark steps that require heavy compute as remote
      for (const step of plan.steps) {
        if (step.type === "exec" || step.type === "optimize") {
          step.execution_target = "remote";
          step.remote_server = config.servers[0]?.name;
          step.remote_reason = "user confirmed remote execution";
          step.requires_user_confirm = true;
        }
      }
    }
  } catch {}
}

// ── Plan summary formatter ──────────────────────────────────────────────────

function formatPlanSummary(plan: Plan): string {
  const lines: string[] = [
    `📋 计划摘要`,
    `─────────────────`,
    `任务: ${plan.task}`,
    `状态: ${plan.status}`,
    `线程: ${plan.thread?.id || "—"}`,
    `目标数: ${plan.goals.length}`,
    `步骤数: ${plan.steps.length}`,
    ``,
    `步骤概览:`,
  ];

  for (const step of plan.steps) {
    const deps = step.depends_on.length > 0 ? ` [依赖: ${step.depends_on.join(", ")}]` : "";
    const remote = step.execution_target === "remote" ? " 🖥️远程" : "";
    lines.push(`  ${step.id}. ${step.name}${deps}${remote}`);
    lines.push(`     ${step.description.slice(0, 60)}${step.description.length > 60 ? "…" : ""}`);
  }

  if (plan.wiki_context?.found) {
    lines.push(``, `📚 Wiki 召回: ${plan.wiki_context.sources.length} 个来源`);
  }

  if (plan.context_digest?.decisions?.length) {
    lines.push(``, `📝 已确认方案: ${plan.context_digest.decisions.length} 项`);
  }

  return lines.join("\n");
}


