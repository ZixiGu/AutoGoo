/**
 * Pi 状态栏 5 维度优化 — 单元测试
 *
 * 运行方式(任选其一):
 *   cd /home/zixigu/workspace/AutoGoo-Plugin/.pi/extensions/autogoo-plugin
 *   npx tsx utils/status.test.ts
 *   或: node --import tsx utils/status.test.ts
 *
 * 用 node:test + assert/strict,不依赖外部测试框架。
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  parseThreadTime, truncateTask, buildProgress, buildCounts, buildHealth, composeLine, formatDuration,
  type PlanSnapshot,
} from "./status.ts";

// Test 1: formatDuration 边界
test("formatDuration handles edge cases", () => {
  assert.equal(formatDuration(0), "0s");
  assert.equal(formatDuration(500), "0s");
  assert.equal(formatDuration(1500), "1s");
  assert.equal(formatDuration(60_000), "1m");
  assert.equal(formatDuration(65_000), "1m5s");
  assert.equal(formatDuration(3_600_000), "1h");
  assert.equal(formatDuration(3_900_000), "1h5m");
});

// Test 2: parseThreadTime
test("parseThreadTime extracts MM-DD HH:mm", () => {
  assert.equal(parseThreadTime("2026-08-05T07-44-status-bar"), "08-05 07:44");
  assert.equal(parseThreadTime("2026-08-05-status-bar-optimize"), "08-05");
  assert.equal(parseThreadTime("short-id"), "short-id");
  assert.equal(parseThreadTime(undefined), "");
  assert.equal(parseThreadTime(""), "");
});

// Test 3: truncateTask
test("truncateTask limits length", () => {
  assert.equal(truncateTask(""), "");
  assert.equal(truncateTask("short"), "short");
  assert.equal(truncateTask("memory-system-design"), "memory-s...ign");
  assert.equal(truncateTask("status-bar-optimize-thread"), "status-b...ead");
  assert.equal(truncateTask(undefined), "");
});

// Test 4: buildProgress 含 ANSI 颜色
test("buildProgress uses Unicode chars and ANSI", () => {
  const snap: PlanSnapshot = { total: 10, completed: 4, running: 0, pending: 0, blocked: 0, failed: 0, staleHeartbeats: 0 };
  const bar = buildProgress(snap);
  assert.match(bar, /▰/);
  assert.match(bar, /▱/);
  const fullSnap: PlanSnapshot = { ...snap, completed: 10 };
  const fullBar = buildProgress(fullSnap);
  assert.match(fullBar, /\x1b\[32m/);
});

// Test 5: buildCounts 颜色编码
test("buildCounts uses colors per status", () => {
  const snap: PlanSnapshot = {
    total: 5, completed: 1, running: 1, pending: 2, blocked: 1, failed: 0, staleHeartbeats: 0,
  };
  const counts = buildCounts(snap);
  assert.match(counts, /\x1b\[36m.*▶/);
  assert.match(counts, /\x1b\[33m.*⊘/);
  assert.match(counts, /\x1b\[2m.*○/);
});

// Test 6: buildHealth
test("buildHealth returns empty for 0", () => {
  const snap: PlanSnapshot = { total: 1, completed: 0, running: 1, pending: 0, blocked: 0, failed: 0, staleHeartbeats: 0 };
  assert.equal(buildHealth(snap), "");
  const snapStale: PlanSnapshot = { ...snap, staleHeartbeats: 2 };
  assert.match(buildHealth(snapStale), /\x1b\[33m.*⚠HB/);
});

// Test 7: composeLine 完整组合
test("composeLine assembles all parts", () => {
  const snap: PlanSnapshot = {
    total: 4, completed: 1, running: 1, pending: 2, blocked: 0, failed: 0, staleHeartbeats: 0,
    threadId: "2026-08-05T07-44-status-bar-optimize",
    threadTask: "status-bar-optimize-thread",
    elapsed: "5m",
    currentStepName: "step1-refactor",
    currentStepElapsed: "30s",
    memoryLayer: "L2",
    wikiPacketGenerated: true,
    etaSeconds: 600,
    recentCompletedStep: "step0-init",
  };
  const line = composeLine(snap);
  assert.match(line, /status-b\.\.\.ead/);
  assert.match(line, /08-05 07:44/);
  assert.match(line, /▰|▱/);
  assert.match(line, /▶.*step1-refactor/);
  assert.match(line, /ETA/);
  assert.match(line, /✓.*step0-init/);
});

// Test 8: ANSI reset 必须关闭颜色
test("ANSI codes close properly", () => {
  const snap: PlanSnapshot = { total: 1, completed: 1, running: 0, pending: 0, blocked: 0, failed: 0, staleHeartbeats: 0 };
  const bar = buildProgress(snap);
  const opens = (bar.match(/\x1b\[32m/g) || []).length;
  const closes = (bar.match(/\x1b\[0m/g) || []).length;
  assert.equal(opens, closes);
});

// Test 9: composeLine 在无 thread 时不报错
test("composeLine handles minimal snapshot", () => {
  const snap: PlanSnapshot = { total: 0, completed: 0, running: 0, pending: 0, blocked: 0, failed: 0, staleHeartbeats: 0 };
  const line = composeLine(snap);
  assert.match(line, /0%/);
  assert.match(line, /0\/0/);
});

// Test 10: long task name 在 composeLine 中正确截断,前面的时间戳不被遮
test("composeLine keeps timestamp visible despite long task name", () => {
  const snap: PlanSnapshot = {
    total: 5, completed: 2, running: 1, pending: 1, blocked: 0, failed: 0, staleHeartbeats: 0,
    threadId: "2026-08-05T07-44-status-bar-optimize",
    threadTask: "this-is-a-very-long-task-name-that-should-be-truncated",
  };
  const line = composeLine(snap);
  // 时间戳必须在前 16 个字符内(ANSI bold 标记外)
  const idx = line.indexOf("08-05");
  assert.ok(idx >= 0 && idx < 20, `timestamp should appear in first 20 chars, got idx=${idx}, line=${line}`);
  // 截断后的任务名包含 ... 标记
  assert.match(line, /\.\.\./);
});
