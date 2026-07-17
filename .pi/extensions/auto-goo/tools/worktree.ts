/**
 * AutoGoo Subagent Worktree Isolation — Git worktree 隔离
 *
 * 为每个 Subagent 创建独立的 Git worktree 分支，
 * 实现文件系统级别的执行隔离，互不干扰。
 *
 * Worktree 模式：
 * - mode="worktree"：每个 Subagent 获得独立 worktree，互不干扰
 * - mode="none"：所有 Subagent 在同一个工作目录执行
 *
 * 生命周期：
 * 1. goo-start 时创建 worktree（如果启用且项目已初始化 Git）
 * 2. Subagent 在 worktree 中执行
 * 3. 步骤完成后合并回主分支
 * 4. 所有步骤完成后清理 worktree
 */

import { Type } from "typebox";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { execShell } from "../utils/exec.js";
import { TEMPLATE_WORKTREE } from "../constants.js";
import { loadPlan, savePlan, type Plan } from "../utils/plan.js";
import { projectPlanPath } from "../utils/paths.js";
import { existsSync } from "node:fs";
import { join } from "node:path";

export function registerWorktreeTools(pi: ExtensionAPI): void {
  // Tool: auto_goo_worktree_create
  pi.registerTool({
    name: "auto_goo_worktree_create",
    label: "Create Worktree",
    description: `为 DAG 步骤创建一个 Git worktree 分支，实现文件级执行隔离。需要项目已初始化 Git 且 HEAD 可解析。`,
    promptSnippet: "为 Subagent 创建 Git worktree 分支执行隔离",
    promptGuidelines: [
      "使用 auto_goo_worktree_create 在 Subagent 派发前创建隔离的 worktree。",
      "worktree 从当前 HEAD 创建新分支，Subagent 在其中安全执行。",
    ],
    parameters: Type.Object({
      stepId: Type.Integer({ description: "步骤 ID" }),
      baseBranch: Type.Optional(Type.String({ description: "基础分支（默认当前分支）" })),
    }),
    async execute(_toolCallId: string, params: any, _signal: any, _onUpdate: any, ctx: any) {
      const cwd = ctx.cwd;
      const stepId = params.stepId;
      const branchName = `auto-goo/step-${stepId}-${Date.now()}`;
      const worktreeDir = join(cwd, `.goo/worktrees/step-${stepId}`);

      const lines: string[] = [];

      // Check git availability
      const gitCheck = execShell("git rev-parse --git-dir 2>&1", cwd, { timeout: 5000 });
      if (gitCheck.exitCode !== 0) {
        return {
          content: [{ type: "text", text: "项目不是 Git 仓库或 HEAD 不可解析。无法创建 worktree。请先初始化 Git 仓库。" }],
          details: { error: "not_a_git_repo" },
        };
      }

      // Get current branch
      let baseBranch = params.baseBranch;
      if (!baseBranch) {
        const branchResult = execShell("git rev-parse --abbrev-ref HEAD 2>&1", cwd, { timeout: 5000 });
        baseBranch = branchResult.stdout?.trim() || "main";
      }

      lines.push(`🌳 创建 Worktree 隔离`);
      lines.push(`─────────────────`);
      lines.push(`步骤: #${stepId}`);
      lines.push(`分支: ${branchName}`);
      lines.push(`目录: ${worktreeDir}`);

      // Cleanup existing worktree for this step
      if (existsSync(worktreeDir)) {
        execShell(`git worktree remove -f "${worktreeDir}" 2>/dev/null`, cwd);
        execShell(`git branch -D "${branchName}" 2>/dev/null`, cwd);
        lines.push(`  已清理旧的 worktree`);
      }

      // Create worktree
      const createResult = execShell(
        `git worktree add -b "${branchName}" "${worktreeDir}" "${baseBranch}" 2>&1`,
        cwd,
        { timeout: 15000 },
      );

      if (createResult.exitCode !== 0) {
        lines.push(`  ❌ 创建失败: ${createResult.stderr.slice(0, 200)}`);
        return {
          content: [{ type: "text", text: lines.join("\n") }],
          details: { error: "worktree_create_failed", branch: branchName },
        };
      }

      lines.push(`  ✅ Worktree 已创建: ${worktreeDir}`);
      lines.push(`  基础分支: ${baseBranch}`);

      return {
        content: [{ type: "text", text: lines.join("\n") }],
        details: {
          stepId,
          branch: branchName,
          worktreeDir,
          baseBranch,
          worktreeCreated: true,
        },
      };
    },
  });

  // Tool: auto_goo_worktree_merge
  pi.registerTool({
    name: "auto_goo_worktree_merge",
    label: "Merge Worktree",
    description: `将 Subagent worktree 的改动合并回主分支。完成步骤的产物从 worktree 合并到项目主分支。`,
    promptSnippet: "将 Subagent worktree 的改动合并回主分支",
    promptGuidelines: [
      "步骤完成后使用 auto_goo_worktree_merge 将 worktree 的改动合并回主分支。",
      "合并后清理 worktree 分支和目录。",
    ],
    parameters: Type.Object({
      stepId: Type.Integer({ description: "步骤 ID" }),
      keepWorktree: Type.Optional(Type.Boolean({ description: "是否保留 worktree（默认 false）" })),
    }),
    async execute(_toolCallId: string, params: any, _signal: any, _onUpdate: any, ctx: any) {
      const cwd = ctx.cwd;
      const stepId = params.stepId;
      const branchName = `auto-goo/step-${stepId}`; // prefix, actual name may have timestamp
      const worktreeDir = join(cwd, `.goo/worktrees/step-${stepId}`);

      const lines: string[] = [];
      lines.push(`🔄 合并 Worktree`);
      lines.push(`─────────────────`);
      lines.push(`步骤: #${stepId}`);

      if (!existsSync(worktreeDir)) {
        lines.push(`  ⚠️ Worktree 目录不存在: ${worktreeDir}`);
        lines.push(`  可能已完成清理，或未创建 worktree。`);

        // Try to merge branch anyway if it exists
        const branchResult = execShell(
          `git branch --list 'auto-goo/step-${stepId}-*' 2>&1`,
          cwd,
          { timeout: 5000 },
        );
        const branches = branchResult.stdout?.trim().split("\n").filter(Boolean);

        if (branches?.length) {
          for (const br of branches) {
            const mergeResult = execShell(
              `git merge --no-ff "${br.trim()}" -m "Merge step #${stepId} from worktree" 2>&1`,
              cwd,
              { timeout: 15000 },
            );
            lines.push(`  合并分支 ${br.trim()}: ${mergeResult.exitCode === 0 ? "✅" : "❌"}`);
            if (mergeResult.exitCode !== 0) {
              execShell(`git merge --abort 2>/dev/null`, cwd);
            }
            execShell(`git branch -D "${br.trim()}" 2>/dev/null`, cwd);
          }
        }

        return {
          content: [{ type: "text", text: lines.join("\n") }],
          details: {},
        };
      }

      // Get actual branch name from worktree
      const branchResult = execShell(
        `git worktree list --porcelain 2>&1 | grep -A1 "${worktreeDir}" | grep "branch" | sed 's/branch //'`,
        cwd,
        { timeout: 5000 },
      );
      const actualBranch = branchResult.stdout?.trim();

      if (!actualBranch) {
        lines.push(`  ⚠️ 无法获取 worktree 对应的分支名`);
        return {
          content: [{ type: "text", text: lines.join("\n") }],
          details: {},
        };
      }

      lines.push(`  Worktree 分支: ${actualBranch}`);

      // Check for changes
      const diffResult = execShell(
        `cd "${worktreeDir}" && git diff --stat HEAD 2>&1`,
        cwd,
        { timeout: 5000 },
      );
      const hasChanges = diffResult.stdout?.trim().length > 0;

      if (!hasChanges) {
        lines.push(`  没有检测到改动，跳过合并。`);
      } else {
        // Add, commit in worktree
        execShell(`cd "${worktreeDir}" && git add -A && git commit -m "Step #${stepId} work" 2>&1`, cwd, { timeout: 15000 });
        lines.push(`  已提交 worktree 改动`);

        // Merge back to main branch
        const currentBranch = execShell("git rev-parse --abbrev-ref HEAD", cwd, { timeout: 5000 }).stdout?.trim() || "main";

        // Fetch worktree branch
        execShell(`git fetch . "${actualBranch}":"${actualBranch}" 2>&1`, cwd, { timeout: 10000 });

        // Merge
        const mergeResult = execShell(
          `git merge --no-ff "${actualBranch}" -m "Merge step #${stepId} from worktree" 2>&1`,
          cwd,
          { timeout: 15000 },
        );

        if (mergeResult.exitCode !== 0) {
          lines.push(`  ❌ 合并冲突: ${mergeResult.stderr.slice(0, 200)}`);
          execShell(`git merge --abort 2>/dev/null`, cwd);
          return {
            content: [{ type: "text", text: lines.join("\n") }],
            details: { error: "merge_conflict" },
          };
        }

        lines.push(`  ✅ 已合并到 ${currentBranch}`);
      }

      // Cleanup
      if (!params.keepWorktree) {
        execShell(`git worktree remove -f "${worktreeDir}" 2>&1`, cwd, { timeout: 5000 });
        execShell(`git branch -D "${actualBranch}" 2>&1`, cwd, { timeout: 5000 });
        lines.push(`  🧹 已清理 worktree 目录和分支`);
      }

      return {
        content: [{ type: "text", text: lines.join("\n") }],
        details: {
          stepId,
          branch: actualBranch,
          merged: hasChanges,
          worktreeCleaned: !params.keepWorktree,
        },
      };
    },
  });

  // Tool: auto_goo_worktree_cleanup
  pi.registerTool({
    name: "auto_goo_worktree_cleanup",
    label: "Cleanup Worktrees",
    description: `清理所有 AutoGoo 创建的 worktree 分支和目录。在计划完成或中断后执行清理。`,
    promptSnippet: "清理所有 AutoGoo worktree 分支和目录",
    parameters: Type.Object({}),
    async execute(_toolCallId: string, _params: any, _signal: any, _onUpdate: any, ctx: any) {
      const cwd = ctx.cwd;
      const lines: string[] = [];
      lines.push(`🧹 Worktree 清理`);

      // Remove all auto-goo worktrees
      const listResult = execShell(
        `git worktree list 2>&1 | grep "auto-goo/step-" || true`,
        cwd,
        { timeout: 5000 },
      );

      const worktrees = listResult.stdout?.split("\n").filter(Boolean) || [];
      if (worktrees.length === 0) {
        lines.push(`  没有找到 AutoGoo worktree`);
      } else {
        for (const wt of worktrees) {
          const dir = wt.split(/\s+/)[0];
          if (dir) {
            execShell(`git worktree remove -f "${dir}" 2>&1`, cwd, { timeout: 5000 });
            lines.push(`  已移除: ${dir}`);
          }
        }
      }

      // Remove all auto-goo branches
      const branchResult = execShell(
        `git branch --list 'auto-goo/step-*' 2>&1`,
        cwd,
        { timeout: 5000 },
      );
      const branches = branchResult.stdout?.split("\n").filter(Boolean) || [];
      for (const br of branches) {
        execShell(`git branch -D "${br.trim()}" 2>&1`, cwd, { timeout: 5000 });
        lines.push(`  已删除分支: ${br.trim()}`);
      }

      // Clean worktree directory
      execShell(`rm -rf "${join(cwd, '.goo/worktrees')}" 2>&1`, cwd);

      return {
        content: [{ type: "text", text: lines.join("\n") }],
        details: { worktreesRemoved: worktrees.length, branchesRemoved: branches.length },
      };
    },
  });
}
