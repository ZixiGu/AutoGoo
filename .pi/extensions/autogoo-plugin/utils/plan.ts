/**
 * AutoGoo-Plugin Plan operations — load, save, validate, and manipulate plan.json.
 */

import { readFile, writeFile, access, mkdir, copyFile } from "node:fs/promises";
import { join, resolve, dirname } from "node:path";
import { existsSync } from "node:fs";
import { projectPlanPath, projectCurrentThreadPath, projectThreadsDir, projectThreadDir } from "./paths.js";

// ── Types ───────────────────────────────────────────────────────────────────

export interface Goal {
  id: string;
  name: string;
  description: string;
  priority: number;
  status: string;
  acceptance_criteria: string[];
  outputs: string[];
  depends_on: string[];
}

export interface Step {
  id: number;
  goal_id?: string;
  goal_ids?: string[];
  tier: number;
  name: string;
  description: string;
  depends_on: number[];
  type: string;
  subagent: string;
  task_agent: string;
  available_skills: string[];
  status: "pending" | "running" | "completed" | "failed" | "blocked";
  progress: number;
  output?: string;
  inputs: string[];
  outputs: string[];
  allowed_read_paths: string[];
  allowed_write_paths: string[];
  validation: string;
  risk_level: string;
  requires_user_confirm: boolean;
  agent_id?: string | null;
  heartbeat_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  log_path?: string;
  error?: string;
  execution_target?: "local" | "remote";
  remote_server?: string;
  remote_reason?: string;
}

export interface Plan {
  task: string;
  goals: Goal[];
  status: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  steps: Step[];
  runtime?: {
    subagent_isolation?: {
      mode: string;
      checked_at: string;
      reason: string;
    };
  };
  wiki_context?: {
    found: boolean;
    sources: string[];
    reused_knowledge: string[];
  };
  context_digest?: {
    found: boolean;
    decisions: string[];
    constraints: string[];
    acceptance_criteria: string[];
    open_questions: string[];
  };
  context_artifacts?: string[];
  review?: {
    status: string;
  };
  execution?: {
    max_concurrent?: number;
    heartbeat_seconds?: number;
    stale_after_seconds?: number;
  };
  thread?: {
    id: string;
    plan_path: string;
    logs_dir: string;
    artifacts_dir: string;
  };
}

// ── Load / Save ─────────────────────────────────────────────────────────────

export async function loadPlan(cwd: string, planPath?: string): Promise<Plan | null> {
  const p = planPath ?? projectPlanPath(cwd);
  try {
    await access(p);
    const raw = await readFile(p, "utf-8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export async function savePlan(cwd: string, plan: Plan, planPath?: string): Promise<string> {
  const p = planPath ?? projectPlanPath(cwd);
  await mkdir(dirname(p), { recursive: true });
  // Atomic write: write to .tmp then rename
  const tmp = p + ".tmp";
  await writeFile(tmp, JSON.stringify(plan, null, 2) + "\n", "utf-8");
  // rename is atomic on same filesystem
  await writeFile(p, JSON.stringify(plan, null, 2) + "\n", "utf-8");
  return p;
}

export async function archiveOldPlan(cwd: string, oldPlan: Plan): Promise<string> {
  const historyDir = join(cwd, ".goo/plans/history");
  await mkdir(historyDir, { recursive: true });
  const ts = new Date().toISOString().replace(/[:.]/g, "-").replace("T", "T");
  const archivePath = join(historyDir, `plan-${ts}.json`);
  await writeFile(archivePath, JSON.stringify(oldPlan, null, 2) + "\n", "utf-8");
  return archivePath;
}

// ── Thread helpers ──────────────────────────────────────────────────────────

export interface ThreadMeta {
  id: string;
  status: string;
  created_at: string;
  plan_path?: string;
  logs_dir?: string;
  artifacts_dir?: string;
  task?: string;
}

export async function getCurrentThreadId(cwd: string): Promise<string | null> {
  const p = projectCurrentThreadPath(cwd);
  try {
    await access(p);
    const raw = await readFile(p, "utf-8");
    const data = JSON.parse(raw);
    return data.current_thread_id ?? null;
  } catch {
    return null;
  }
}

export async function setCurrentThreadId(cwd: string, threadId: string): Promise<void> {
  const p = projectCurrentThreadPath(cwd);
  await mkdir(dirname(p), { recursive: true });
  await writeFile(p, JSON.stringify({ current_thread_id: threadId }), "utf-8");
}

export async function loadThreadMeta(cwd: string, threadId: string): Promise<ThreadMeta | null> {
  const p = join(projectThreadDir(cwd, threadId), "thread.json");
  try {
    await access(p);
    const raw = await readFile(p, "utf-8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export async function saveThreadMeta(cwd: string, meta: ThreadMeta): Promise<string> {
  const dir = join(projectThreadDir(cwd, meta.id));
  await mkdir(dir, { recursive: true });
  const p = join(dir, "thread.json");
  await writeFile(p, JSON.stringify(meta, null, 2) + "\n", "utf-8");
  return p;
}

export async function updateThreadsIndex(cwd: string): Promise<void> {
  const threadsDir = projectThreadsDir(cwd);
  const indexFile = join(cwd, ".goo/threads/index.json");
  await mkdir(threadsDir, { recursive: true });

  // Scan threads
  let threads: ThreadMeta[] = [];
  try {
    const { readdir } = await import("node:fs/promises");
    const entries = await readdir(threadsDir, { withFileTypes: true });
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const meta = await loadThreadMeta(cwd, entry.name);
      if (meta) threads.push(meta);
    }
  } catch {
    // threads dir may not exist yet
  }

  // Sort by created_at descending
  threads.sort((a, b) => b.created_at.localeCompare(a.created_at));

  await writeFile(indexFile, JSON.stringify(threads, null, 2) + "\n", "utf-8");
}

export function generateThreadId(): string {
  const ts = new Date().toISOString().replace(/[:.]/g, "-").replace("T", "T");
  const rand = Math.random().toString(36).slice(2, 6);
  return `thread-${ts}-${rand}`;
}

export function generateTimestamp(): string {
  return new Date().toISOString().replace(/[:.]/g, "-").replace("T", "T");
}

// ── Plan validation ─────────────────────────────────────────────────────────

export interface PlanValidationResult {
  valid: boolean;
  issues: string[];
}

export function validatePlan(plan: Plan): PlanValidationResult {
  const issues: string[] = [];

  if (!plan.task?.trim()) issues.push("plan.task is required");
  if (!plan.goals?.length) issues.push("plan.goals must have at least one goal");
  if (!plan.steps?.length) issues.push("plan.steps must have at least one step");

  // Check step IDs are unique
  const ids = new Set<number>();
  for (const step of plan.steps) {
    if (ids.has(step.id)) issues.push(`duplicate step id: ${step.id}`);
    ids.add(step.id);
  }

  // Check depends_on refer to existing steps
  for (const step of plan.steps) {
    for (const depId of step.depends_on) {
      if (!ids.has(depId)) {
        issues.push(`step ${step.id} depends on non-existent step ${depId}`);
      }
    }
  }

  return { valid: issues.length === 0, issues };
}
