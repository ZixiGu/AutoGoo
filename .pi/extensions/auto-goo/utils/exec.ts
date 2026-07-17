/**
 * Shared shell execution utility — eliminates duplication of execAsync.
 */

import { execSync, type ExecSyncOptions } from "node:child_process";

export interface ExecResult {
  stdout: string;
  stderr: string;
  exitCode: number;
}

/**
 * Execute a command synchronously with proper error handling.
 * All AutoGoo command handlers use this instead of duplicating execAsync.
 */
export function exec(
  command: string,
  args: string[],
  cwd: string,
  options?: { timeout?: number; maxBuffer?: number },
): ExecResult {
  const escaped = args.map((a) => `"${a.replace(/"/g, '\\"')}"`).join(" ");
  const fullCmd = `${command} ${escaped}`;

  const opts: ExecSyncOptions = {
    cwd,
    encoding: "utf-8" as const,
    maxBuffer: options?.maxBuffer ?? 10 * 1024 * 1024,
    timeout: options?.timeout ?? 60000,
  };

  try {
    const stdout = execSync(fullCmd, opts) as string;
    return { stdout, stderr: "", exitCode: 0 };
  } catch (err: any) {
    return {
      stdout: err.stdout ?? "",
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
 * Execute an arbitrary shell command string.
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
