/**
 * AutoGoo-Plugin Remote Server SSH — 远程执行集成
 *
 * 封装 SSH 远程执行流程：
 * - 读取配置文件中的服务器信息
 * - 通过 goo-ssh.sh（sshpass -f 临时文件读 secrets.json 密码）执行远程命令
 * - 服务器信息缺失/冲突时主动询问用户：新增配置 or 更新原配置
 *
 * 安全约束：
 * - 密码绝不进入命令行 / 聊天 / 日志 / plan，只存 .goo/secrets.json（chmod 600）
 * - 新增服务器时不通过 ui.input 收集密码；若需密码认证，提示用户手动写入 secrets.json
 */

import { Type } from "typebox";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { execBash } from "../utils/exec.js";
import {
  REPO_ROOT,
  loadProjectConfig,
  getServers,
  projectConfigPath,
  type AutogooPluginConfig,
  type ServerEntry,
} from "../utils/paths.js";
import { existsSync } from "node:fs";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

/** 小范围 upsert 服务器配置（保持其余配置原样，避免 goo-init.sh 的连带副作用）。 */
async function upsertServerInConfig(cwd: string, server: ServerEntry): Promise<void> {
  const cfgPath = projectConfigPath(cwd);
  let config: any = {};
  try {
    config = JSON.parse(await readFile(cfgPath, "utf-8"));
  } catch {
    config = {};
  }
  const list = Array.isArray(config.servers) ? config.servers : [];
  const idx = list.findIndex((s: any) => s?.name === server.name);
  if (idx >= 0) {
    list[idx] = { ...list[idx], ...server };
  } else {
    list.push(server);
  }
  config.servers = list;
  await writeFile(cfgPath, JSON.stringify(config, null, 2) + "\n", "utf-8");
}

/** 判断 server 字符串是否像 goo-ssh.sh 的直接连接串（user@host / host:port / 索引），
 *  这类串不应触发“新增配置”流程。 */
function looksLikeDirectSelector(value: string): boolean {
  if (/^\d+$/.test(value)) return true; // 索引
  if (value.includes("@")) return true; // user@host
  if (/^[\w.\-]+:\d+$/.test(value)) return true; // host:port
  return false;
}

interface ResolvedServer {
  server: ServerEntry;
  lines: string[];
  cancelled?: string;
}

/**
 * 解析服务器配置：按 name/host/ip 查找；缺失 → 询问是否新增；
 * 用户额外提供的 host/port/user 与配置冲突/缺失 → 询问是否更新原配置。
 * 返回解析后的 server + 过程说明行；用户拒绝时返回 cancelled。
 */
async function resolveServer(
  cwd: string,
  selector: string,
  provided: { host?: string; port?: number; user?: string },
  ctx: any,
): Promise<ResolvedServer> {
  const lines: string[] = [];
  const config = await loadProjectConfig(cwd);
  const servers = getServers(config);
  const existing = servers.find(
    (s) => s.name === selector || s.host === selector || s.ip === selector,
  );

  // 未找到
  if (!existing) {
    if (looksLikeDirectSelector(selector)) {
      return {
        server: null as any,
        lines,
        cancelled: `"${selector}" 是直接连接串（索引/user@host/host:port），请用配置中的服务器名称。可用服务器: ${servers.map((s) => s.name).join(", ") || "无"}`,
      };
    }
    if (!ctx?.ui) {
      return {
        server: null as any,
        lines,
        cancelled: `服务器 "${selector}" 未在配置中找到，且当前无可交互 UI 无法询问是否新增。可用服务器: ${servers.map((s) => s.name).join(", ") || "无"}`,
      };
    }

    // 收集缺失字段（host / port / user 必填；type 可选）
    let host = provided.host || (await ctx.ui.input(`未找到服务器 "${selector}"。请输入其主机/IP 以新增配置：`, ""));
    let port = provided.port || Number(await ctx.ui.input(`请输入 ${selector} 的 SSH 端口：`, "22"));
    let user = provided.user || (await ctx.ui.input(`请输入 ${selector} 的 SSH 用户名：`, ""));
    host = (host || "").trim();
    user = (user || "").trim();
    if (!host || !port || !user) {
      return {
        server: null as any,
        lines,
        cancelled: `服务器 "${selector}" 信息不完整（host/port/user 必填），未新增。可用服务器: ${servers.map((s) => s.name).join(", ") || "无"}`,
      };
    }
    let type: "cpu" | "gpu" = "cpu";
    try {
      const t = await ctx.ui.select(`服务器 ${selector} 类型`, ["cpu", "gpu"]);
      if (t === "gpu" || t === "cpu") type = t;
    } catch {
      /* 默认 cpu */
    }

    const addAnswer = await ctx.ui.confirm(
      `新增服务器 ${selector}？`,
      `未在配置中找到 "${selector}"。将新增到 ${projectConfigPath(cwd)}：\n` +
        `  name=${selector}\n  host=${host}\n  port=${port}\n  user=${user}\n  type=${type}\n` +
        `\n是否添加？添加后立即用该配置执行；拒绝则中止。`,
    );
    if (!addAnswer) {
      return {
        server: null as any,
        lines,
        cancelled: `用户拒绝新增服务器 "${selector}"，命令未执行。可用服务器: ${servers.map((s) => s.name).join(", ") || "无"}`,
      };
    }

    const newServer: ServerEntry = {
      name: selector,
      host,
      port,
      user,
      type,
      purpose: selector,
    };
    await upsertServerInConfig(cwd, newServer);
    lines.push(`✅ 已新增服务器 "${selector}"（host=${host}:${port}, user=${user}, type=${type}）`);
    lines.push(`🔑 若该服务器需要密码认证：请将密码加入 ${projectConfigPath(cwd).replace(/config\.json$/, "secrets.json")}（chmod 600，格式与现有条目一致），密码不会在本对话中收集。`);
    return { server: newServer, lines };
  }

  // 已找到 → 检测冲突/缺失
  const conflicts: string[] = [];
  if (provided.host) {
    const cfgHost = existing.host || existing.ip || "";
    if (cfgHost && provided.host !== cfgHost) {
      conflicts.push(`host: 配置=${cfgHost}，提供=${provided.host}`);
    } else if (!cfgHost) {
      conflicts.push(`host: 配置缺失，提供=${provided.host}`);
    }
  }
  if (provided.port) {
    if (existing.port && Number(provided.port) !== Number(existing.port)) {
      conflicts.push(`port: 配置=${existing.port}，提供=${provided.port}`);
    } else if (!existing.port) {
      conflicts.push(`port: 配置缺失，提供=${provided.port}`);
    }
  }
  if (provided.user) {
    if (existing.user && provided.user !== existing.user) {
      conflicts.push(`user: 配置=${existing.user}，提供=${provided.user}`);
    } else if (!existing.user) {
      conflicts.push(`user: 配置缺失，提供=${provided.user}`);
    }
  }

  if (conflicts.length > 0 && ctx?.ui) {
    const updateAnswer = await ctx.ui.confirm(
      `服务器 ${existing.name} 配置冲突/缺失`,
      `检测到提供的信息与 .goo/config.json 不一致：\n${conflicts.join("\n")}\n\n` +
        `是否更新配置？\n选择"是" → 更新后用新值执行；选择"否" → 忽略提供值，用现有配置执行。`,
    );
    if (updateAnswer) {
      if (provided.host) existing.host = provided.host;
      if (provided.port) existing.port = Number(provided.port);
      if (provided.user) existing.user = provided.user;
      await upsertServerInConfig(cwd, existing);
      lines.push(`✅ 已更新服务器 ${existing.name} 配置（${conflicts.map((c) => c.split(":")[0]).join(", ")}）`);
    } else {
      lines.push(`ℹ️ 忽略提供值，使用现有配置执行`);
    }
  } else if (conflicts.length > 0) {
    lines.push(`ℹ️ 检测到配置不一致但无可交互 UI，使用现有配置执行：${conflicts.join("；")}`);
  }

  return { server: existing, lines };
}

export function registerSshTools(pi: ExtensionAPI): void {
  // Tool: auto_goo_ssh_exec
  pi.registerTool({
    name: "auto_goo_ssh_exec",
    label: "SSH Execute",
    description: `在远程服务器上执行命令。需要先在 .goo/config.json 中配置服务器信息，密码存储在 .goo/secrets.json（chmod 600）。`,
    promptSnippet: "在远程服务器上执行命令",
    promptGuidelines: [
      "使用 auto_goo_ssh_exec 在远程服务器上执行命令。需要先通过 goo-init 配置服务器。",
      "服务器不在配置中时会主动询问是否新增；提供 host/port/user 与配置冲突时会询问是否更新配置。",
      "密码不得暴露在聊天、日志或 plan 中，只能存储在 secrets.json。",
    ],
    parameters: Type.Object({
      server: Type.String({ description: "服务器名称/别名（来自 config.json servers[].name）" }),
      command: Type.String({ description: "在远程服务器上执行的命令" }),
      workdir: Type.Optional(Type.String({ description: "远程工作目录（可选，默认使用服务器配置的 workdir）" })),
      timeout: Type.Optional(Type.Integer({ description: "超时秒数（默认 300）" })),
      host: Type.Optional(Type.String({ description: "服务器主机/IP（与配置不一致或缺省时询问是否更新配置）" })),
      port: Type.Optional(Type.Integer({ description: "SSH 端口（与配置不一致或缺省时询问是否更新配置）" })),
      user: Type.Optional(Type.String({ description: "SSH 用户名（与配置不一致或缺省时询问是否更新配置）" })),
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

      // 解析服务器（缺失→询问新增；冲突/缺省→询问更新）
      const resolved = await resolveServer(
        cwd,
        params.server,
        { host: params.host, port: params.port, user: params.user },
        ctx,
      );
      if (resolved.cancelled || !resolved.server) {
        return {
          content: [{ type: "text", text: [resolved.cancelled, ...resolved.lines].filter(Boolean).join("\n") }],
          details: { error: "server_not_resolved" },
        };
      }
      const server = resolved.server;
      const prefixLines = resolved.lines;

      // Build SSH command — 密码只经 goo-ssh.sh 的 sshpass -f 临时文件传递，
      // 绝不拼进命令行（ps / shell history 可见）。
      const workdir = params.workdir || server.defaults?.workdir || "~";

      // Execute via goo-ssh.sh
      const result = execBash(sshScript, [
        "--config", join(cwd, ".goo/config.json"),
        "--server", server.name,
        "--", params.command,
      ], cwd, { timeout: params.timeout ?? 300000 });

      const output = result.stdout || result.stderr || "(no output)";
      const truncated = output.length > 5000 ? output.slice(0, 5000) + `\n\n... (${output.length - 5000} more bytes)` : output;

      return {
        content: [{ type: "text", text: [prefixLines.join("\n"), truncated].filter(Boolean).join("\n") }],
        details: {
          server: server.name,
          host: server.host || server.ip,
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
      host: Type.Optional(Type.String({ description: "服务器主机/IP（缺失时询问是否新增配置）" })),
      port: Type.Optional(Type.Integer({ description: "SSH 端口（缺失时询问是否新增配置）" })),
      user: Type.Optional(Type.String({ description: "SSH 用户名（缺失时询问是否新增配置）" })),
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

      // 指定了 server：先解析（缺失→询问新增），再只查该台
      let serversFiltered: ServerEntry[] = [];
      let resolveLines: string[] = [];
      if (params.server) {
        const resolved = await resolveServer(
          cwd,
          params.server,
          { host: params.host, port: params.port, user: params.user },
          ctx,
        );
        resolveLines = resolved.lines;
        if (resolved.cancelled || !resolved.server) {
          return {
            content: [{ type: "text", text: [resolved.cancelled, ...resolveLines].filter(Boolean).join("\n") }],
            details: { error: "server_not_resolved" },
          };
        }
        serversFiltered = [resolved.server];
      } else {
        const config = await loadProjectConfig(cwd);
        serversFiltered = getServers(config);
        if (!serversFiltered.length) {
          return {
            content: [{ type: "text", text: "没有配置远程服务器。使用 /auto-goo:goo-init 添加服务器，或调用 auto_goo_ssh_exec（提供 host/port/user）让系统询问新增。" }],
            details: {},
          };
        }
      }

      const lines: string[] = ["🖥️ 远程服务器状态", "─────────────────", ...resolveLines];
      // 连通性与信息采集统一走 goo-ssh.sh（sshpass -f 临时文件读 secrets 密码）；
      // 旧实现用裸 ssh -o BatchMode=yes 且不带密码：密码认证的服务器必然
      // Permission denied，永远显示“无法连接”。

      for (const server of serversFiltered) {
        const host = server.host || server.ip || "?";
        lines.push(`\n服务器: ${server.name} (${host}:${server.port})`);
        lines.push(`  类型: ${server.type}`);
        lines.push(`  用途: ${server.purpose}`);

        // Quick connectivity check（用 goo-ssh.sh，密码走 secrets 临时文件）
        const pingResult = execBash(
          sshScript,
          ["--config", join(cwd, ".goo/config.json"), "--server", server.name, "--", "echo OK"],
          cwd,
          { timeout: 15000 },
        );

        if (pingResult.exitCode !== 0) {
          lines.push(`  状态: ❌ 无法连接`);
          const err = (pingResult.stderr || pingResult.stdout || "").trim();
          if (err) {
            lines.push(`  原因: ${err.slice(0, 120)}`);
          }
          continue;
        }

        lines.push(`  状态: ✅ 在线`);

        // Get system info
        const infoCmd =
          `echo '---CPU---'; nproc; echo '---MEM---'; free -h | grep Mem; ` +
          `echo '---DISK---'; df -h / | tail -1; echo '---UPTIME---'; uptime -p; ` +
          (server.type === "gpu"
            ? `echo '---GPU---'; nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null || echo 'nvidia-smi not found'`
            : "");
        const infoResult = execBash(
          sshScript,
          ["--config", join(cwd, ".goo/config.json"), "--server", server.name, "--", infoCmd],
          cwd,
          { timeout: 20000 },
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
        details: { serverCount: serversFiltered.length },
      };
    },
  });
}
