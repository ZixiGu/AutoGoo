/**
 * AutoGoo Remote Server SSH — 远程执行集成
 *
 * 封装 SSH 远程执行流程：
 * - 读取配置文件中的服务器信息
 * - 从 secrets.json 读取密码（如果配置了 sshpass）
 * - 通过 goo-ssh.sh 执行远程命令
 * - 支持多服务器选择
 */

import { Type } from "typebox";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { execBash, execShell } from "../utils/exec.js";
import {
  REPO_ROOT,
  loadProjectConfig,
  projectSecretsPath,
  type AutoGooConfig,
} from "../utils/paths.js";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

export function registerSshTools(pi: ExtensionAPI): void {
  // Tool: auto_goo_ssh_exec
  pi.registerTool({
    name: "auto_goo_ssh_exec",
    label: "SSH Execute",
    description: `在远程服务器上执行命令。需要先在 .goo/config.json 中配置服务器信息，密码存储在 .goo/secrets.json（chmod 600）。`,
    promptSnippet: "在远程服务器上执行命令",
    promptGuidelines: [
      "使用 auto_goo_ssh_exec 在远程服务器上执行命令。需要先通过 goo-init 配置服务器。",
      "密码不得暴露在聊天、日志或 plan 中，只能存储在 secrets.json。",
    ],
    parameters: Type.Object({
      server: Type.String({ description: "服务器名称/别名（来自 config.json servers[].name）" }),
      command: Type.String({ description: "在远程服务器上执行的命令" }),
      workdir: Type.Optional(Type.String({ description: "远程工作目录（可选，默认使用服务器配置的 workdir）" })),
      timeout: Type.Optional(Type.Integer({ description: "超时秒数（默认 300）" })),
    }),
    async execute(_toolCallId: string, params: any, _signal: any, _onUpdate: any, ctx: any) {
      const cwd = ctx.cwd;
      const sshScript = join(REPO_ROOT, "skills/auto-goo/scripts/goo-ssh.sh");

      if (!existsSync(sshScript)) {
        return {
          content: [{ type: "text", text: `goo-ssh.sh 未找到: ${sshScript}` }],
          details: { error: "script_not_found" },
        };
      }

      // Find server config
      const config = await loadProjectConfig(cwd);
      const server = config?.servers?.find(
        (s) => s.name === params.server || s.host === params.server,
      );
      if (!server) {
        return {
          content: [{ type: "text", text: `服务器 "${params.server}" 未在配置中找到。可用服务器: ${(config?.servers ?? []).map((s: any) => s.name).join(", ") || "无"}` }],
          details: { error: "server_not_found" },
        };
      }

      // Check secrets
      let passwordCmd = "";
      const secretsPath = server.secrets_file
        ? join(cwd, server.secrets_file)
        : projectSecretsPath(cwd);
      if (existsSync(secretsPath)) {
        try {
          const secrets = JSON.parse(readFileSync(secretsPath, "utf-8"));
          const serverSecret = secrets.servers?.find(
            (s: any) => s.name === server.name || s.host === server.host,
          );
          if (serverSecret?.password) {
            // Use sshpass with password from secrets
            passwordCmd = `sshpass -p "${serverSecret.password}"`;
          }
        } catch {}
      }

      // Build SSH command
      const workdir = params.workdir || server.defaults?.workdir || "~";
      const sshCmd = [
        passwordCmd,
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        "-p", String(server.port),
        `${server.user}@${server.host}`,
        `"cd ${workdir} && ${params.command}"`,
      ]
        .filter(Boolean)
        .join(" ");

      // Execute via goo-ssh.sh or directly
      let result;
      if (existsSync(sshScript)) {
        result = execBash(sshScript, [
          "--config", join(cwd, ".goo/config.json"),
          "--server", server.name,
          "--", params.command,
        ], cwd, { timeout: params.timeout ?? 300000 });
      } else {
        result = execShell(sshCmd, cwd, { timeout: params.timeout ?? 300000 });
      }

      const output = result.stdout || result.stderr || "(no output)";
      const truncated = output.length > 5000 ? output.slice(0, 5000) + `\n\n... (${output.length - 5000} more bytes)` : output;

      return {
        content: [{ type: "text", text: truncated }],
        details: {
          server: server.name,
          host: server.host,
          exitCode: result.exitCode,
          outputLength: output.length,
        },
      };
    },
  });

  // Tool: auto_goo_ssh_status
  pi.registerTool({
    name: "auto_goo_ssh_status",
    label: "SSH Server Status",
    description: "检查远程服务器的连通性和基本状态（CPU、内存、磁盘、GPU）。",
    promptSnippet: "检查远程服务器连通性和资源状态",
    parameters: Type.Object({
      server: Type.Optional(Type.String({ description: "服务器名称（可选，默认所有服务器）" })),
    }),
    async execute(_toolCallId: string, params: any, _signal: any, _onUpdate: any, ctx: any) {
      const cwd = ctx.cwd;
      const config = await loadProjectConfig(cwd);

      if (!config?.servers?.length) {
        return {
          content: [{ type: "text", text: "没有配置远程服务器。使用 /goo-init 添加服务器。" }],
          details: {},
        };
      }

      let servers = config.servers;
      if (params.server) {
        servers = servers.filter((s: any) => s.name === params.server);
      }

      const lines: string[] = ["🖥️ 远程服务器状态", "─────────────────"];

      for (const server of servers) {
        lines.push(`\n服务器: ${server.name} (${server.host}:${server.port})`);
        lines.push(`  类型: ${server.type}`);
        lines.push(`  用途: ${server.purpose}`);

        // Quick connectivity check
        const pingResult = execShell(
          `ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes -p ${server.port} ${server.user}@${server.host} "echo OK" 2>&1`,
          cwd,
          { timeout: 10000 },
        );

        if (pingResult.exitCode !== 0) {
          lines.push(`  状态: ❌ 无法连接`);
          if (pingResult.stderr) {
            lines.push(`  原因: ${pingResult.stderr.slice(0, 100)}`);
          }
          continue;
        }

        lines.push(`  状态: ✅ 在线`);

        // Get system info
        const infoResult = execShell(
          `ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -p ${server.port} ${server.user}@${server.host} "echo '---CPU---'; nproc; echo '---MEM---'; free -h | grep Mem; echo '---DISK---'; df -h / | tail -1; echo '---UPTIME---'; uptime -p; ${server.type === 'gpu' ? "echo '---GPU---'; nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null || echo 'nvidia-smi not found'" : ""}" 2>&1`,
          cwd,
          { timeout: 15000 },
        );

        if (infoResult.exitCode === 0) {
          const info = infoResult.stdout;
          const cpuMatch = info.match(/---CPU---\n(.+)/);
          const memMatch = info.match(/---MEM---\n(.+)/);
          const diskMatch = info.match(/---DISK---\n(.+)/);
          const uptimeMatch = info.match(/---UPTIME---\n(.+)/);
          const gpuMatch = info.match(/---GPU---\n(.+?)(?:\n---|$)/s);

          if (cpuMatch) lines.push(`  CPU 核心: ${cpuMatch[1].trim()}`);
          if (memMatch) lines.push(`  内存: ${memMatch[1].trim()}`);
          if (diskMatch) lines.push(`  磁盘: ${diskMatch[1].trim()}`);
          if (uptimeMatch) lines.push(`  运行时间: ${uptimeMatch[1].trim()}`);
          if (gpuMatch) {
            const gpuLines = gpuMatch[1].trim().split("\n");
            for (const gl of gpuLines) {
              if (gl.trim()) lines.push(`  GPU: ${gl.trim()}`);
            }
          }
        }
      }

      return {
        content: [{ type: "text", text: lines.join("\n") }],
        details: { serverCount: servers.length },
      };
    },
  });
}
