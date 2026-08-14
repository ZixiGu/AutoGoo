/**
 * plan.ts 环检测与校验 — 单元测试
 *
 * 修复 2026-08-14：由 bun:test 改写为 node:test + node:assert/strict，
 * 与 subagent.test.ts / utils/status.test.ts 统一，node --test 可直接发现运行。
 *
 * 运行方式(任选其一):
 *   cd /home/zixigu/workspace/AutoGoo-Plugin/.pi/extensions/autogoo-plugin
 *   npx tsx __tests__/plan-cycle.test.ts
 *   或: node --import tsx --test __tests__/plan-cycle.test.ts
 *
 * 覆盖：findCycleNodes（无环/2节点环/3节点环/自环）+ validatePlan（坏依赖/重复id/环）。
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { findCycleNodes, validatePlan } from "../utils/plan.ts";

const noCycle = { task: "t", goals: [], steps: [{ id: "s1", depends_on: [] }, { id: "s2", depends_on: ["s1"] }] } as any;
const cyc2 = { task: "t", goals: [], steps: [{ id: "s1", depends_on: ["s2"] }, { id: "s2", depends_on: ["s1"] }] } as any;
const cyc3 = { task: "t", goals: [], steps: [{ id: "a", depends_on: ["c"] }, { id: "b", depends_on: ["a"] }, { id: "c", depends_on: ["b"] }] } as any;
const badDep = { task: "t", goals: [], steps: [{ id: "s1", depends_on: ["s9"] }] } as any;
const dup = { task: "t", goals: [], steps: [{ id: "s1", depends_on: [] }, { id: "s1", depends_on: [] }] } as any;
const selfLoop = { task: "t", goals: [], steps: [{ id: "s1", depends_on: ["s1"] }] } as any;

// ── findCycleNodes ──────────────────────────────────────────────────────────

test("无环返回空", () => {
  assert.deepEqual(findCycleNodes(noCycle), []);
});

test("2 节点环", () => {
  assert.deepEqual(findCycleNodes(cyc2).sort(), ["s1", "s2"]);
});

test("3 节点环", () => {
  assert.deepEqual(findCycleNodes(cyc3).sort(), ["a", "b", "c"]);
});

test("自环", () => {
  assert.deepEqual(findCycleNodes(selfLoop), ["s1"]);
});

// ── validatePlan ────────────────────────────────────────────────────────────

test("坏依赖", () => {
  assert.ok(validatePlan(badDep).issues.join().includes("s9"));
});

test("重复 id", () => {
  assert.ok(validatePlan(dup).issues.join().includes("duplicate"));
});

test("环报错", () => {
  assert.ok(validatePlan(cyc2).issues.join().includes("circular"));
});
