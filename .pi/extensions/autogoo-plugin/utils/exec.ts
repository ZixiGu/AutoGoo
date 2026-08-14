/**
 * Shared shell execution utility — eliminates duplication of execAsync.
 *
 * exec / execPython / execBash：用 spawnSync 传参数数组，**不走 shell**，
 * 参数中的 $()、反引号、引号、括号等特殊字符不会被执行或破坏命令
 * （修复 2026-08-10：原实现 execSync 拼接字符串 + 仅转义 "，导致
 *   $(cmd)、`cmd` 命令注入、引号配对破坏 → /bin/sh Syntax error）。
 *
 * execShell：保留 shell（本就接收 shell 命令字符串），用 /bin/bash。
 */

import { execSync, spawnSync, type ExecSyncOptions, type SpawnSyncOptions } from "node:child_process";

export interface ExecResult {
  stdout: string;
  stderr: string;
  exitCode: number;
}

/**
 * Execute a command with an argument array via spawnSync (no shell).
 * All AutoGoo-Plugin command handlers use this instead of duplicating execAsync.
 */
export function exec(
  command: string,
  args: string[],
  cwd: string,
  options?: { timeout?: number; maxBuffer?: number },
): ExecResult {
  const opts: SpawnSyncOptions = {
    cwd,
    encoding: "utf-8" as const,
    maxBuffer: options?.maxBuffer ?? 10 * 1024 * 1024,
    timeout: options?.timeout ?? 60000,
    // 不走 shell：参数数组原样传给子进程，杜绝引号/特殊字符注入
    shell: false,
  };

  try {
    const r = spawnSync(command, args, opts);
    return {
      stdout: r.stdout ?? "",
      stderr: r.stderr ?? "",
      exitCode: r.status ?? (r.error ? 1 : 0),
    };
  } catch (err: any) {
    return {
      stdout: "",
      stderr: err.stderr ?? err.message,
      exitCode: err.status ?? 1,
    };
  }
}

/**
 * Execute a Python script with arguments.
 */
export function execPython(
  scriptPath: string,
  scriptArgs: string[],
  cwd: string,
  options?: { timeout?: number },
): ExecResult {
  return exec("python3", [scriptPath, ...scriptArgs], cwd, options);
}

/**
 * Execute a bash script with arguments.
 */
export function execBash(
  scriptPath: string,
  scriptArgs: string[],
  cwd: string,
  options?: { timeout?: number },
): ExecResult {
  return exec("bash", [scriptPath, ...scriptArgs], cwd, options);
}

/**
 * Execute an arbitrary shell command string (intentionally uses shell).
 */
export function execShell(
  cmd: string,
  cwd: string,
  options?: { timeout?: number },
): ExecResult {
  const opts: ExecSyncOptions = {
    cwd,
    encoding: "utf-8" as const,
    maxBuffer: 10 * 1024 * 1024,
    timeout: options?.timeout ?? 60000,
    shell: "/bin/bash",
  };

  try {
    const stdout = execSync(cmd, opts) as string;
    return { stdout, stderr: "", exitCode: 0 };
  } catch (err: any) {
    return {
      stdout: err.stdout ?? "",
      stderr: err.stderr ?? err.message,
      exitCode: err.status ?? 1,
    };
  }
}
