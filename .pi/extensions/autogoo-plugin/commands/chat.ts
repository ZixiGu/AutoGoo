/**
 * AutoGoo-Plugin 跨 session 对话命令
 *
 * 5 个命令（参考 commands/other.ts 的 handler 模式）：
 *   /goo-chat <target> <message>   发送消息（resolveAlias → isPaired → 信箱投递）
 *   /goo-chat-read [target]        拉取未读消息并注入内容（带 target 只拉该 session，其余放回）
 *   /goo-pair <aliasA> <aliasB>    显式配对
 *   /goo-unpair <aliasA> <aliasB>  解除配对
 *   /goo-chat-list                 列出注册表 + 配对 + 未读消息摘要
 *   /goo-alias <alias>             自定义本会话别名
 */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  registerSession,
  resolveAlias,
  isPaired,
  sendMessage,
  addPair,
  removePair,
  listSessions,
  listPairs,
  getUnreadCount,
  setAlias,
  getSession,
  peekMailbox,
  drainMailbox,
  putBackMessages,
  type ChatPair,
  type ChatMessage,
  type ChatSessionEntry,
} from "../utils/chat.js";

// ── Global pi reference（供 sendUserMessage 注入内容；与 commands/other.ts 同模式） ──
let _pi: ExtensionAPI | null = null;

export function setPi(pi: ExtensionAPI): void {
  _pi = pi;
}

// ── 参数解析 ────────────────────────────────────────────────────────────────

function splitArgs(args: string): string[] {
  return args.trim().split(/\s+/).filter(Boolean);
}

// ── /goo-chat ───────────────────────────────────────────────────────────────

export async function handleGooChat(args: string, ctx: ExtensionContext): Promise<void> {
  const parts = splitArgs(args);
  if (parts.length < 2) {
    ctx.ui.notify("用法: /goo-chat <target> <message>", "warning");
    return;
  }

  const target = parts[0];
  const content = args.trim().slice(target.length).trim();
  if (!content) {
    ctx.ui.notify("消息内容不能为空", "warning");
    return;
  }

  const cwd = ctx.cwd;
  const sessionId = ctx.sessionManager.getSessionId();

  const targetEntry = await resolveAlias(cwd, target);
  if (!targetEntry) {
    ctx.ui.notify(`session 不存在: ${target}`, "error");
    return;
  }
  if (targetEntry.sessionId === sessionId) {
    ctx.ui.notify("不能给自己发消息", "warning");
    return;
  }

  const paired = await isPaired(cwd, sessionId, targetEntry.sessionId);
  if (!paired) {
    ctx.ui.notify(
      `未配对: 与 ${target} 未配对，用 /goo-pair 配对 或 同 thread 自动配对`,
      "warning",
    );
    return;
  }

  try {
    await sendMessage(cwd, sessionId, targetEntry.sessionId, content);
  } catch (err: any) {
    ctx.ui.notify(`发送失败: ${err.message}`, "error");
    return;
  }
  ctx.ui.notify(`📨 已投递到 ${targetEntry.alias}@${targetEntry.project}`, "success");
}

// ── /goo-pair ───────────────────────────────────────────────────────────────

export async function handleGooPair(args: string, ctx: ExtensionContext): Promise<void> {
  const [a, b] = splitArgs(args);
  if (!a || !b) {
    ctx.ui.notify("用法: /goo-pair <aliasA> <aliasB>", "warning");
    return;
  }

  const cwd = ctx.cwd;
  const ea = await resolveAlias(cwd, a);
  const eb = await resolveAlias(cwd, b);
  if (!ea) {
    ctx.ui.notify(`session 不存在: ${a}`, "error");
    return;
  }
  if (!eb) {
    ctx.ui.notify(`session 不存在: ${b}`, "error");
    return;
  }
  if (ea.sessionId === eb.sessionId) {
    ctx.ui.notify("不能配对同一个 session", "warning");
    return;
  }

  try {
    await addPair(cwd, ea.sessionId, eb.sessionId);
  } catch (err: any) {
    ctx.ui.notify(`配对失败: ${err.message}`, "error");
    return;
  }
  ctx.ui.notify(`✅ 已配对: ${ea.alias} ↔ ${eb.alias}`, "success");
}

// ── /goo-unpair ─────────────────────────────────────────────────────────────

export async function handleGooUnpair(args: string, ctx: ExtensionContext): Promise<void> {
  const [a, b] = splitArgs(args);
  if (!a || !b) {
    ctx.ui.notify("用法: /goo-unpair <aliasA> <aliasB>", "warning");
    return;
  }

  const cwd = ctx.cwd;
  const ea = await resolveAlias(cwd, a);
  const eb = await resolveAlias(cwd, b);
  if (!ea || !eb) {
    ctx.ui.notify("session 不存在（用 /goo-chat-list 查看可用别名）", "error");
    return;
  }

  const removed = await removePair(cwd, ea.sessionId, eb.sessionId);
  ctx.ui.notify(
    removed ? `已解除配对: ${ea.alias} ↔ ${eb.alias}` : `这两个 session 没有显式配对（同 thread 自动配对仍有效）`,
    removed ? "success" : "info",
  );
}

// ── /goo-chat-read ──────────────────────────────────────────────────────────

/**
 * 拉取未读消息并注入内容：drainMailbox 取全部 → 按 from 分组 → 逐组 sendUserMessage。
 * 带 [target] 时只注入来自该 target 的，其余消息放回信箱（未注入的保留）。
 */
export async function handleGooChatRead(args: string, ctx: ExtensionContext): Promise<void> {
  const cwd = ctx.cwd;
  const sessionId = ctx.sessionManager.getSessionId();

  const target = splitArgs(args)[0] ?? null;
  let targetEntry: ChatSessionEntry | null = null;
  if (target) {
    targetEntry = await resolveAlias(cwd, target);
    if (!targetEntry) {
      ctx.ui.notify(`session 不存在: ${target}`, "error");
      return;
    }
  }

  const all = await drainMailbox(cwd, sessionId);
  if (all.length === 0) {
    ctx.ui.notify("📭 没有未读消息", "info");
    return;
  }

  // 带 target：只注入来自该 target 的，其余放回信箱
  let toInject = all;
  if (targetEntry) {
    toInject = all.filter((m) => m.from === targetEntry!.sessionId);
    if (toInject.length === 0) {
      await putBackMessages(cwd, sessionId, all);
      ctx.ui.notify(`来自 ${targetEntry.alias} 的消息：无（其他未读已保留在信箱）`, "info");
      return;
    }
    const rest = all.filter((m) => m.from !== targetEntry!.sessionId);
    await putBackMessages(cwd, sessionId, rest);
  }

  if (!_pi) {
    await putBackMessages(cwd, sessionId, toInject);
    ctx.ui.notify("chat-read 需要 pi 运行时引用，消息已保留在信箱", "error");
    return;
  }

  // 按 from 分组注入
  const groups = new Map<string, ChatMessage[]>();
  for (const m of toInject) {
    const list = groups.get(m.from) ?? [];
    list.push(m);
    groups.set(m.from, list);
  }

  for (const [fromId, msgs] of groups) {
    const alias = msgs[0].fromAlias || fromId.slice(0, 8);
    const project = msgs[0].fromProject || "";
    const content = msgs.map((m) => m.content).join("\n");
    _pi?.sendUserMessage(
      `📨 来自 ${alias}@${project}：${content}\n（回复用 /goo-chat ${alias} 你的回复）`,
      { deliverAs: "followUp" },
    );
  }

  const injected = toInject.length;
  ctx.ui.notify(
    `📨 已拉取 ${injected} 条未读消息${targetEntry ? `（来自 ${targetEntry.alias}）` : ""}`,
    "success",
  );
}

// ── /goo-chat-list ──────────────────────────────────────────────────────────

function pairLabel(p: ChatPair, sessions: { sessionId: string; alias: string }[]): string {
  const name = (id: string) => {
    const s = sessions.find((x) => x.sessionId === id);
    return s ? `${s.alias}` : id.slice(0, 12);
  };
  return `${name(p.from)} ↔ ${name(p.to)}`;
}

export async function handleGooChatList(args: string, ctx: ExtensionContext): Promise<void> {
  const cwd = ctx.cwd;
  const sessionId = ctx.sessionManager.getSessionId();

  const sessions = await listSessions(cwd);
  const pairs = await listPairs(cwd);
  const unread = await getUnreadCount(cwd, sessionId);
  const unreadMsgs = await peekMailbox(cwd, sessionId);

  const lines: string[] = [];
  lines.push(`📋 会话注册表 (${sessions.length}):`);
  if (sessions.length === 0) {
    lines.push("  （空 — 当前 session 将随启动自动注册）");
  }
  for (const s of sessions) {
    const me = s.sessionId === sessionId ? " ⭐本会话" : "";
    const last = s.lastSeen ? new Date(s.lastSeen).toISOString().slice(0, 19) : "—";
    lines.push(
      `  - ${s.alias}${me} | ${s.project} | thread=${s.threadId ?? "—"} | ${s.sessionId.slice(0, 12)}… | 活跃 ${last}`,
    );
  }

  if (pairs.length > 0) {
    lines.push(`🔗 显式配对 (${pairs.length}):`);
    for (const p of pairs) {
      lines.push(`  - ${pairLabel(p, sessions)}`);
    }
  } else {
    lines.push("🔗 显式配对: 无");
  }

  lines.push(unread > 0 ? `📨 本会话未读消息: ${unread}（用 /goo-chat-read 拉取）` : "📭 本会话未读消息: 0");
  for (const m of unreadMsgs) {
    const alias = m.fromAlias || m.from.slice(0, 8);
    const project = m.fromProject || "";
    const preview = m.content.replace(/\s+/g, " ").slice(0, 80);
    lines.push(`  - ${alias}@${project}: ${preview}`);
  }

  ctx.ui.notify(lines.join("\n").slice(0, 2000), "info");
}

// ── /goo-alias ──────────────────────────────────────────────────────────────

export async function handleGooAlias(args: string, ctx: ExtensionContext): Promise<void> {
  const [alias] = splitArgs(args);
  if (!alias) {
    ctx.ui.notify("用法: /goo-alias <alias>", "warning");
    return;
  }

  const cwd = ctx.cwd;
  const sessionId = ctx.sessionManager.getSessionId();

  // 未注册则先注册（防御：hook 未执行到的场景）
  const existing = await getSession(cwd, sessionId);
  if (!existing) {
    await registerSession(cwd, sessionId, ctx.sessionManager.getSessionFile() ?? null);
  }

  const result = await setAlias(cwd, sessionId, alias);
  if (!result.ok) {
    if (result.reason === "alias_conflict") {
      ctx.ui.notify(`别名冲突: ${alias} 已被其他 session 使用，换一个`, "warning");
    } else {
      ctx.ui.notify(`session 未注册，无法设置别名`, "error");
    }
    return;
  }
  ctx.ui.notify(`✅ 本会话别名已设为: ${alias}`, "success");
}
