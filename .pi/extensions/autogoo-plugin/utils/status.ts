/**
 * AutoGoo-Plugin Status Bar — 持久化状态栏，关联当前 session 的 thread。
 *
 * 使用 ctx.ui.setStatus() 在 Pi 底部状态栏显示：
 * - thread 创建时间 + 任务名
 * - 执行用时
 * - 计划进度（进度条 + 完成百分比 + 步骤计数）
 * - 心跳健康状态
 *
 * 生命周期：session 启动时显示，session 结束时清除。
 */

import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { loadPlan, getCurrentThreadId, loadThreadMeta, type Plan, type Step } from "./plan.js";

const STATUS_KEY = "autogoo-plugin";

export interface PlanSnapshot {
  total: number;
  completed: number;
  running: number;
  pending: number;
  blocked: number;
  failed: number;
  staleHeartbeats: number;
  threadId?: string;
  threadTask?: string;
  elapsed?: string;    // human-readable duration, e.g. "5m", "1h23m"
}

/** Format milliseconds into human-readable duration. */
function formatDuration(ms: number): string {
  if (ms < 1000) return "0s";
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m${sec % 60 > 0 ? `${sec % 60}s` : ""}`;
  const hr = Math.floor(min / 60);
  return `${hr}h${min % 60 > 0 ? `${min % 60}m` : ""}`;
}

async function getThreadInfo(cwd: string): Promise<{ id: string; task: string } | null> {
  try {
    const plan = await loadPlan(cwd);
    if (plan?.thread?.id) {
      return { id: plan.thread.id, task: plan.task?.slice(0, 20) || "" };
    }
    const tid = await getCurrentThreadId(cwd);
    if (tid) {
      const meta = await loadThreadMeta(cwd, tid);
      return { id: tid, task: meta?.task?.slice(0, 20) || "" };
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Collect a snapshot of current plan state.
 */
export async function snapshotPlan(cwd: string): Promise<PlanSnapshot | null> {
  const plan = await loadPlan(cwd);
  if (!plan?.steps) return null;

  const steps = plan.steps;
  const now = Date.now();
  const staleSeconds = plan.execution?.stale_after_seconds ?? 120;

  let staleCount = 0;
  for (const s of steps) {
    if (s.status === "running" && s.heartbeat_at) {
      const age = (now - new Date(s.heartbeat_at).getTime()) / 1000;
      if (age > staleSeconds) staleCount++;
    }
  }

  // Calculate elapsed time
  let elapsed: string | undefined;
  if (plan.started_at) {
    const start = new Date(plan.started_at).getTime();
    const end = plan.completed_at ? new Date(plan.completed_at).getTime() : now;
    elapsed = formatDuration(end - start);
  }

  const threadInfo = await getThreadInfo(cwd);

  return {
    total: steps.length,
    completed: steps.filter(s => s.status === "completed").length,
    running: steps.filter(s => s.status === "running").length,
    pending: steps.filter(s => s.status === "pending").length,
    blocked: steps.filter(s => s.status === "blocked").length,
    failed: steps.filter(s => s.status === "failed").length,
    staleHeartbeats: staleCount,
    threadId: threadInfo?.id,
    threadTask: threadInfo?.task,
    elapsed,
  };
}

/**
 * Render a status bar line from a plan snapshot.
 */
export function formatStatusLine(snap: PlanSnapshot): string {
  const pct = snap.total > 0 ? Math.round((snap.completed / snap.total) * 100) : 0;
  const parts: string[] = [];

  // Thread timestamp (human-readable)
  if (snap.threadId) {
    const m = snap.threadId.match(/thread-(\d{4})-(\d{2})-(\d{2})T(\d{2})-(\d{2})/);
    if (m) {
      parts.push(`${m[2]}-${m[3]} ${m[4]}:${m[5]}`);
    } else if (snap.threadId.length > 12) {
      parts.push(snap.threadId.slice(-8));
    } else {
      parts.push(snap.threadId);
    }
    if (snap.threadTask) {
      parts[parts.length - 1] += ` ${snap.threadTask}`;
    }
  }

  // Elapsed time
  if (snap.elapsed) {
    parts.push(`⌛${snap.elapsed}`);
  }

  // Progress bar
  const barLen = 10;
  const filled = Math.round(barLen * snap.completed / Math.max(1, snap.total));
  parts.push(`[${"█".repeat(filled)}${"░".repeat(barLen - filled)}]`);
  parts.push(`${pct}%`);

  // Counts
  const counts: string[] = [];
  if (snap.running > 0) counts.push(`▶${snap.running}`);
  if (snap.pending > 0) counts.push(`○${snap.pending}`);
  if (snap.blocked > 0) counts.push(`⊘${snap.blocked}`);
  if (snap.failed > 0) counts.push(`✕${snap.failed}`);
  parts.push(`${snap.completed}/${snap.total}`);
  if (counts.length > 0) parts.push(counts.join(" "));

  // Heartbeat warning
  if (snap.staleHeartbeats > 0) {
    parts.push(`⚠HB${snap.staleHeartbeats}`);
  }

  return parts.join(" ");
}

/**
 * Update the Pi status bar with current plan state.
 * Call this after any state-changing operation.
 */
export async function updateStatusBar(ctx: ExtensionContext): Promise<void> {
  const snap = await snapshotPlan(ctx.cwd);
  if (!snap) {
    ctx.ui.setStatus(STATUS_KEY, undefined);
    return;
  }

  const line = formatStatusLine(snap);
  ctx.ui.setStatus(STATUS_KEY, line);
}

/**
 * Clear the status bar.
 */
export function clearStatusBar(ctx: ExtensionContext): void {
  ctx.ui.setStatus(STATUS_KEY, undefined);
}
