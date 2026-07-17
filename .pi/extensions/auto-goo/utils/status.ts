/**
 * AutoGoo Status Bar — 持久化状态栏，替代频繁的 notify 通知。
 *
 * 使用 ctx.ui.setStatus() 在 Pi 底部状态栏显示：
 * - 当前 thread 名称 / ID
 * - 计划整体进度
 * - 运行中 / 已完成 / 总步骤数
 * - 心跳健康状态
 */

import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { loadPlan, getCurrentThreadId, loadThreadMeta, type Plan, type Step } from "./plan.js";

const STATUS_KEY = "auto-goo";

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
    // Format: thread-2026-07-17T07-18-52-abcd
    // Show: 07-17 07:18
    const m = snap.threadId.match(/thread-(\d{4})-(\d{2})-(\d{2})T(\d{2})-(\d{2})/);
    if (m) {
      parts.push(`${m[2]}-${m[3]} ${m[4]}:${m[5]}`);
    } else if (snap.threadId.length > 12) {
      parts.push(snap.threadId.slice(-8));
    } else {
      parts.push(snap.threadId);
    }
    // Append short task name if available
    if (snap.threadTask) {
      parts[parts.length - 1] += ` ${snap.threadTask}`;
    }
  }

  // Progress bar (compact)
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

  // 所有步骤已完成或没有待执行步骤 → 清除状态栏
  if (snap.total > 0 && snap.pending === 0 && snap.running === 0) {
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
