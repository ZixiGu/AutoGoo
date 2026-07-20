/**
 * AutoGoo Pi Extension v0.4 — 主入口
 *
 * DAG 驱动的多智能体编排框架，从 Claude Code 插件迁移。
 *
 * 功能：
 * - 14 个命令（/auto-goo:goo-xxx 和 /goo-xxx 两种方式）
 * - 13 个自定义工具（执行、调度、SSH、worktree、状态管理）
 * - ctx.ui 替代 AskUserQuestion 进行交互
 * - Python 脚本原样复用
 * - 自动 session 恢复检测
 * - DAG 自动调度引擎
 * - Git worktree 执行隔离
 * - 远程服务器 SSH 集成
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// Commands
import { handleGooInit } from "./commands/init.js";
import { handleGooPlan } from "./commands/plan.js";
import { handleGooBrainstorm } from "./commands/brainstorm.js";
import {
  handleGooStart,
  handleGooStatus,
  registerExecutionTools,
  setPi as setStartPi,
} from "./commands/start.js";
import {
  handleGooObserve,
  handleGooPublish,
  handleGooResearch,
  handleGooUsage,
  handleGooUsageAnalyse,
  handleGooDailyReport,
  handleGooImprove,
  handleGooBenchmark,
  handleGooContinue,
  setPi as setOtherPi,
} from "./commands/other.js";

// Tools
import { registerExecuteTool } from "./tools/execute.js";
import { registerSshTools } from "./tools/ssh.js";
import { registerWorktreeTools } from "./tools/worktree.js";

// Utils
import { REPO_ROOT, isRepoValid } from "./utils/paths.js";
import { AUTOGOO_SYSTEM_PROMPT } from "./constants.js";

// ── Command routing table ───────────────────────────────────────────────────

interface CommandEntry {
  description: string;
  handler: (args: string, ctx: any) => Promise<void>;
}

const COMMANDS: Record<string, CommandEntry> = {
  "goo-init": {
    description: "初始化 AutoGoo 配置（用户级或项目级）",
    handler: handleGooInit,
  },
  "goo-brainstorm": {
    description: "目标不明确时通过头脑风暴生成候选目标",
    handler: handleGooBrainstorm,
  },
  "goo-plan": {
    description: "生成 DAG 执行计划（召回 wiki → 拆解 → 审阅）",
    handler: handleGooPlan,
  },
  "goo-start": {
    description: "执行 DAG 计划（加载 → context sync → 调度）",
    handler: handleGooStart,
  },
  "goo-continue": {
    description: "恢复中断的执行（检测僵尸步骤 → 继续调度）",
    handler: handleGooContinue,
  },
  "goo-status": {
    description: "查看工作流状态仪表盘",
    handler: handleGooStatus,
  },
  "goo-observe": {
    description: "后台观察运行中的步骤和心跳",
    handler: handleGooObserve,
  },
  "goo-publish": {
    description: "发布工作流为静态 HTML 站点",
    handler: handleGooPublish,
  },
  "goo-research": {
    description: "启动研究任务（论文深读、代码搜索等）",
    handler: handleGooResearch,
  },
  "goo-usage": {
    description: "查看 token/usage 统计",
    handler: handleGooUsage,
  },
  "goo-usage-analyse": {
    description: "分析 token 消耗并生成降本方案",
    handler: handleGooUsageAnalyse,
  },
  "goo-daily-report": {
    description: "生成日报/周报并归档到 Goo-wiki",
    handler: handleGooDailyReport,
  },
  "goo-improve": {
    description: "AutoGoo 自改进审查",
    handler: handleGooImprove,
  },
  "goo-benchmark": {
    description: "启动性能评测与优化迭代",
    handler: handleGooBenchmark,
  },
};

// ── Extension Entry Point ───────────────────────────────────────────────────

export default function (pi: ExtensionAPI) {
  // ── Share pi reference with command handlers ──────────────────────────────
  setStartPi(pi);
  setOtherPi(pi);

  // ── Validate AutoGoo repo ─────────────────────────────────────────────────
  if (!isRepoValid()) {
    console.warn(
      "[AutoGoo] ⚠️ AutoGoo repo structure not found at",
      REPO_ROOT,
      "- some features may not work"
    );
  }

  // ── Input interception for /auto-goo: commands ────────────────────────────
  //
  // Catches /auto-goo:goo-xxx patterns before they reach the LLM.
  // Routes to the appropriate TypeScript handler.

  pi.on("input", async (event, ctx) => {
    const text = event.text.trim();
    const match = text.match(/^\/auto-goo:(goo-\S+)(?:\s+(.*))?$/s);
    if (!match) return { action: "continue" };

    const cmdName = match[1];
    const args = (match[2] || "").trim();
    const cmd = COMMANDS[cmdName];

    if (!cmd) {
      ctx.ui.notify(`[AutoGoo] 未知命令: ${cmdName}`, "warning");
      return { action: "handled" };
    }

    try {
      await cmd.handler(args, ctx);
    } catch (err: any) {
      ctx.ui.notify(`[AutoGoo] ${cmdName} 执行失败: ${err.message}`, "error");
    }
    return { action: "handled" };
  });

  // ── Register short commands (without /auto-goo: prefix) ───────────────────
  //
  // All 14 commands are also available as /goo-xxx for convenience.

  for (const [name, entry] of Object.entries(COMMANDS)) {
    pi.registerCommand(name, {
      description: entry.description,
      handler: async (args, ctx) => {
        await entry.handler(args, ctx);
      },
    });
  }

  // ── Register execution tools ──────────────────────────────────────────────
  //
  // Core DAG tools that the LLM calls during execution.

  registerExecutionTools(pi);
  registerExecuteTool(pi);

  // ── Register SSH remote execution tools ───────────────────────────────────
  registerSshTools(pi);

  // ── Register worktree isolation tools ─────────────────────────────────────
  registerWorktreeTools(pi);

  // ── Register utility tools ────────────────────────────────────────────────

  // auto_goo_ask_user — 结构化交互（替代 AskUserQuestion）
  pi.registerTool({
    name: "auto_goo_ask_user",
    label: "Ask User",
    description: "向用户提问并获取结构化选择。用选择/确认/输入三种模式替代普通文本提问。",
    promptSnippet: "向用户提问获取选择或输入",
    promptGuidelines: [
      "使用 auto_goo_ask_user 向用户提问，提供结构化选项让用户选择，而不是用普通文本要求用户回复编号。",
    ],
    parameters: {
      type: "object",
      properties: {
        header: { type: "string", description: "问题标题" },
        question: { type: "string", description: "问题内容" },
        type: { type: "string", enum: ["select", "confirm", "input"], description: "交互类型" },
        options: {
          type: "array",
          items: {
            type: "object",
            properties: {
              label: { type: "string" },
              description: { type: "string" },
              value: { type: "string" },
            },
          },
          description: "选择类型时的选项列表",
        },
        defaultValue: { type: "string", description: "输入类型时的默认值" },
      },
      required: ["header", "question", "type"],
    },
    async execute(_toolCallId: string, params: any, _signal: any, _onUpdate: any, ctx: any) {
      let result: any;
      switch (params.type) {
        case "select": {
          // Convert objects to string labels for Pi's select API
          const options = (params.options || []).map((o: any) =>
            typeof o === "string" ? o : (o.label || String(o))
          );
          const label = await ctx.ui.select(params.header, options);
          // Map back to value if input was objects with label/value
          if (label && params.options?.[0]?.value !== undefined) {
            const found = params.options.find((o: any) => o.label === label);
            result = found?.value ?? label;
          } else {
            result = label;
          }
          break;
        }
        case "confirm":
          result = await ctx.ui.confirm(params.header, params.question);
          break;
        case "input":
          result = await ctx.ui.input(params.question, params.defaultValue || "");
          break;
      }
      return {
        content: [{ type: "text", text: `用户回答: ${String(result ?? "(无回答)")}` }],
        details: { userResponse: result },
      };
    },
  });

  // auto_goo_shell — 安全执行 shell 命令
  pi.registerTool({
    name: "auto_goo_shell",
    label: "Shell",
    description: "在项目根目录执行 shell 命令，返回输出。用于执行 Python 脚本、Git 操作等。",
    promptSnippet: "在项目根执行 shell 命令",
    parameters: {
      type: "object",
      properties: {
        command: { type: "string", description: "要执行的 shell 命令" },
        timeout: { type: "integer", description: "超时秒数（默认 30）" },
        description: { type: "string", description: "命令用途说明（可选，用于日志）" },
      },
      required: ["command"],
    },
    async execute(_toolCallId: string, params: any, _signal: any, _onUpdate: any, ctx: any) {
      const { execShell } = await import("./utils/exec.js");
      const result = execShell(params.command, ctx.cwd, { timeout: params.timeout ?? 30000 });
      const output = (result.stdout || result.stderr || "(no output)").slice(0, 10000);
      return {
        content: [{ type: "text", text: output }],
        details: { exitCode: result.exitCode, truncated: (result.stdout?.length ?? 0) > 10000 },
      };
    },
  });

  // ── Session hooks ─────────────────────────────────────────────────────────

  pi.on("session_start", async (_event, ctx) => {
    // Detect uncompleted AutoGoo plan
    try {
      const { loadPlan } = await import("./utils/plan.js");
      const plan = await loadPlan(ctx.cwd);
      if (plan) {
        const pending = plan.steps?.filter(
          (s: any) => s.status === "pending" || s.status === "running",
        ).length || 0;
        const blocked = plan.steps?.filter((s: any) => s.status === "blocked").length || 0;
        if (pending > 0 || blocked > 0) {
          ctx.ui.notify(
            `[AutoGoo] 📋 检测到未完成计划 (${pending} 待执行, ${blocked} 阻塞)。` +
            `使用 /goo-status 查看详情，/goo-continue 恢复执行。`,
            "info",
          );
        }
        // Update status bar
        try {
          const { updateStatusBar } = await import("./utils/status.js");
          await updateStatusBar(ctx);
        } catch (e) {
          // ignore
        }
      }
    } catch (e) {
      // ignore
    }
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    // Clear status bar — it belongs to this session
    try {
      const { clearStatusBar } = await import("./utils/status.js");
      clearStatusBar(ctx);
    } catch {}

    // Cleanup stale worktrees on exit
    try {
      const { execShell } = await import("./utils/exec.js");
      execShell(
        "git worktree list 2>/dev/null | grep 'auto-goo/step-' | awk '{print $1}' | xargs -r git worktree remove -f 2>/dev/null; true",
        ctx.cwd,
        { timeout: 10000 },
      );
    } catch {}
  });

  // ── Inject AutoGoo system prompt ─────────────────────────────────────────
  pi.on("before_agent_start", async (event, ctx) => {
    return {
      systemPrompt: event.systemPrompt + AUTOGOO_SYSTEM_PROMPT,
    };
  });

  // ── Startup banner ────────────────────────────────────────────────────────
  const cmdList = Object.keys(COMMANDS).join(", ");
  const toolList = [
    "auto_goo_execute", "auto_goo_update_step",
    "auto_goo_dispatch", "auto_goo_prepare_dispatch",
    "auto_goo_dag_status", "auto_goo_pending_steps",
    "auto_goo_ask_user", "auto_goo_shell",
    "auto_goo_ssh_exec", "auto_goo_ssh_status",
    "auto_goo_worktree_create", "auto_goo_worktree_merge",
    "auto_goo_worktree_cleanup",
  ].join(", ");

  // Use stderr to avoid interfering with Pi's TUI rendering
  process.stderr.write(`[AutoGoo] ✅ 扩展已加载 (v0.4.0)\n`);
}
