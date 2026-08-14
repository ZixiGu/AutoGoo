/**
 * Pi 子进程 Subagent 执行器 — 迁移自「会话内 followUp 注入」。
 *
 * 动机（2026-08-10 迁移）：
 * - 旧方案用 pi.sendUserMessage(prompt, { deliverAs: "followUp" }) 注入任务，
 *   依赖主 Agent turn 结束消费 followUp 队列；调度循环持续调用工具时
 *   followUp 永不投递（饥饿），实测 auto_goo_execute 自动派发多次失败。
 * - 新方案 spawn 独立 pi 子进程（--mode json -p --no-session）执行 Subagent：
 *   - 上下文隔离（--no-session 新会话）
 *   - 投递可靠（不依赖 followUp 机制）
 *   - 天然并行（多 step 并发 spawn）
 *   - usage 统计（解析 message_end 事件）
 *   - 心跳保活：onTick 回调由调用方每 ~20s 更新 step 心跳，防止 STALE 误杀
 *
 * 参考 pi 官方示例 examples/extensions/subagent/index.ts（子进程 JSON 模式）。
 */

import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";

// ── Types ───────────────────────────────────────────────────────────────────

export interface SubagentUsage {
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
  cost: number;
  contextTokens: number;
  turns: number;
}

export interface SubagentRunOptions {
  /** Role 系统提示（写入临时文件 via --append-system-prompt） */
  systemPrompt?: string;
  /** 任务 prompt（含 step 契约 / wiki packet / 执行要求） */
  task: string;
  /** 子进程工作目录（= 项目根） */
  cwd: string;
  /** 覆盖 provider（默认继承 pi 全局配置） */
  provider?: string;
  /** 覆盖 model（默认继承 pi 全局配置） */
  model?: string;
  /** 限制工具集（--tools a,b） */
  tools?: string[];
  /** 超时（默认 30min），超时 kill SIGTERM → 5s 后 SIGKILL */
  timeoutMs?: number;
  /** 心跳保活回调（每 ~20s），由调用方写 step heartbeat */
  onTick?: () => void;
  /** 流式消息回调（message_end / tool_result_end），可选 */
  onMessage?: (message: unknown) => void;
  /** 取消信号 */
  signal?: AbortSignal;
}

export interface SubagentRunResult {
  exitCode: number;
  /** 最终 assistant 文本输出 */
  output: string;
  stderr: string;
  messages: unknown[];
  usage: SubagentUsage;
  model?: string;
  stopReason?: string;
  errorMessage?: string;
  timedOut?: boolean;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

const HEARTBEAT_INTERVAL_MS = 20_000;
const DEFAULT_TIMEOUT_MS = 30 * 60 * 1000;

/** 解析当前 pi 可执行文件（复用官方 subagent 扩展逻辑）。
 *  支持 AUTOGOO_SUBAGENT_CMD 环境变量覆盖（测试/调试用）。 */
export function getPiInvocation(args: string[]): { command: string; args: string[] } {
  const override = process.env.AUTOGOO_SUBAGENT_CMD;
  if (override) {
    const parts = override.split(" ").filter(Boolean);
    return { command: parts[0], args: [...parts.slice(1), ...args] };
  }
  const currentScript = process.argv[1];
  const isBunVirtualScript = currentScript?.startsWith("/$bunfs/root/");
  if (currentScript && !isBunVirtualScript && existsSafe(currentScript)) {
    return { command: process.execPath, args: [currentScript, ...args] };
  }
  const execName = basename(process.execPath).toLowerCase();
  const isGenericRuntime = /^(node|bun)(\.exe)?$/.test(execName);
  if (!isGenericRuntime) {
    return { command: process.execPath, args };
  }
  return { command: "pi", args };
}

function existsSafe(p: string): boolean {
  return existsSync(p);
}

/** 从 assistant 消息中提取最终文本输出。 */
export function getFinalOutput(messages: unknown[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i] as { role?: string; content?: Array<{ type: string; text?: string }> };
    if (msg?.role === "assistant" && Array.isArray(msg.content)) {
      for (const part of msg.content) {
        if (part?.type === "text" && part.text) return part.text;
      }
    }
  }
  return "";
}

// ── Core ────────────────────────────────────────────────────────────────────

export function emptyUsage(): SubagentUsage {
  return { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: 0, contextTokens: 0, turns: 0 };
}

/**
 * Spawn 一个独立 pi 子进程执行 Subagent 任务，解析 JSON 流输出。
 * 阻塞直到子进程退出；期间每 ~20s 调用 onTick 供调用方保活心跳。
 */
export async function runSubagent(opts: SubagentRunOptions): Promise<SubagentRunResult> {
  const args: string[] = ["--mode", "json", "-p", "--no-session"];
  if (opts.provider) args.push("--provider", opts.provider);
  if (opts.model) args.push("--model", opts.model);
  if (opts.tools && opts.tools.length > 0) args.push("--tools", opts.tools.join(","));

  let tmpDir: string | null = null;
  if (opts.systemPrompt?.trim()) {
    tmpDir = mkdtempSync(join(tmpdir(), "autogoo-subagent-"));
    const spPath = join(tmpDir, "system-prompt.md");
    writeFileSync(spPath, opts.systemPrompt, { mode: 0o600 });
    args.push("--append-system-prompt", spPath);
  }
  args.push(`Task: ${opts.task}`);

  const invocation = getPiInvocation(args);
  const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const usage = emptyUsage();
  const messages: unknown[] = [];

  const result: SubagentRunResult = {
    exitCode: 0,
    output: "",
    stderr: "",
    messages,
    usage,
    timedOut: false,
  };

  const cleanup = () => {
    if (tmpDir) {
      try {
        rmSync(tmpDir, { recursive: true, force: true });
      } catch {
        /* ignore */
      }
      tmpDir = null;
    }
  };

  return await new Promise<SubagentRunResult>((resolve) => {
    let proc: ReturnType<typeof spawn>;
    try {
      proc = spawn(invocation.command, invocation.args, {
        cwd: opts.cwd,
        shell: false,
        stdio: ["ignore", "pipe", "pipe"],
        // 标记子进程模式：插件在子进程内跳过主 Agent 唤醒、不注册调度工具，
        // 防止 Subagent 递归调度 DAG。
        env: { ...process.env, AUTOGOO_SUBAGENT: "1" },
      });
    } catch (e) {
      cleanup();
      resolve({ ...result, exitCode: 1, errorMessage: e instanceof Error ? e.message : String(e) });
      return;
    }

    const heartbeatTimer = setInterval(() => {
      try {
        opts.onTick?.();
      } catch {
        /* 心跳失败不阻塞子进程 */
      }
    }, HEARTBEAT_INTERVAL_MS);

    let timeoutTimer: ReturnType<typeof setTimeout> | null = null;
    let killTimer: ReturnType<typeof setTimeout> | null = null;
    let settled = false;

    /** 终止子进程：先 SIGTERM，5s 后仍未退出则 SIGKILL（P11：timer 可清理）。 */
    const killProc = (signal: NodeJS.Signals = "SIGTERM") => {
      try {
        proc.kill(signal);
      } catch {
        /* ignore */
      }
      if (killTimer) clearTimeout(killTimer);
      killTimer = setTimeout(() => {
        try {
          if (proc.exitCode === null) proc.kill("SIGKILL");
        } catch {
          /* ignore */
        }
      }, 5000);
    };

    const clearKillTimer = () => {
      if (killTimer) {
        clearTimeout(killTimer);
        killTimer = null;
      }
    };

    if (timeoutMs > 0) {
      timeoutTimer = setTimeout(() => {
        result.timedOut = true;
        killProc("SIGTERM");
      }, timeoutMs);
    }

    // P11：abort listener 在 close/error 时移除，避免泄漏
    const onAbort = () => killProc("SIGTERM");
    if (opts.signal) {
      if (opts.signal.aborted) onAbort();
      else opts.signal.addEventListener("abort", onAbort, { once: true });
    }

    const stopTimers = () => {
      clearInterval(heartbeatTimer);
      if (timeoutTimer) {
        clearTimeout(timeoutTimer);
        timeoutTimer = null;
      }
      clearKillTimer();
      if (opts.signal) opts.signal.removeEventListener("abort", onAbort);
    };

    const finish = (code: number) => {
      if (settled) return;
      settled = true;
      stopTimers();
      result.exitCode = code;
      result.output = getFinalOutput(messages);
      cleanup();
      resolve(result);
    };

    const processLine = (line: string) => {
      if (!line.trim()) return;
      let event: any;
      try {
        event = JSON.parse(line);
      } catch {
        return; // 非 JSON 行（如日志）忽略
      }
      if (event.type === "message_end" && event.message) {
        const msg = event.message as {
          role?: string;
          content?: Array<{ type: string; text?: string }>;
          usage?: {
            input?: number;
            output?: number;
            cacheRead?: number;
            cacheWrite?: number;
            totalTokens?: number;
            cost?: { total?: number };
          };
          model?: string;
          stopReason?: string;
          errorMessage?: string;
        };
        messages.push(msg);
        if (msg.role === "assistant") {
          usage.turns++;
          if (msg.usage) {
            usage.input += msg.usage.input || 0;
            usage.output += msg.usage.output || 0;
            usage.cacheRead += msg.usage.cacheRead || 0;
            usage.cacheWrite += msg.usage.cacheWrite || 0;
            usage.cost += msg.usage.cost?.total || 0;
            usage.contextTokens = msg.usage.totalTokens || usage.contextTokens;
          }
          if (msg.model) result.model = msg.model;
          if (msg.stopReason) result.stopReason = msg.stopReason;
          if (msg.errorMessage) result.errorMessage = msg.errorMessage;
        }
        try {
          opts.onMessage?.(msg);
        } catch {
          /* ignore */
        }
      } else if (event.type === "tool_result_end" && event.message) {
        messages.push(event.message);
        try {
          opts.onMessage?.(event.message);
        } catch {
          /* ignore */
        }
      }
    };

    let buffer = "";
    proc.stdout!.on("data", (data: Buffer) => {
      buffer += data.toString();
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) processLine(line);
    });

    proc.stderr!.on("data", (data: Buffer) => {
      result.stderr += data.toString();
    });

    proc.on("close", (code) => {
      if (buffer.trim()) processLine(buffer);
      finish(code ?? 0);
    });

    proc.on("error", (e) => {
      result.errorMessage = e.message;
      finish(1);
    });
  });
}
