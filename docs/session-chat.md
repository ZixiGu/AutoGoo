# 跨 Session 对话（session-chat）

> 2026-08-17 实现。不同 pi session（同一项目/跨项目）通过**文件信箱**异步对话，
> 无需共享会话上下文，消息持久化在项目 `.goo/chat/` 目录。

## 功能概述

跨 session 对话让多个 pi 会话（可以属于同一项目，也可以属于不同项目）通过
**文件信箱（mailbox）** 异步收发消息：

- **异步**：发送方写入信箱文件即完成，不要求接收方在线；接收方下次启动（或手动拉取）时取回。
- **跨项目**：消息数据按**接收方所在项目**的 `.goo/chat/` 目录落盘，发送方只需知道接收方别名。
- **轻量**：无中央服务，无网络 IPC，纯文件读写 + JSON 原子写，天然适合同一机器上的多个 pi 进程。

典型场景：

- 一个主会话在跑 DAG 调度，另一个会话负责人工确认/补充信息，两者异步沟通。
- 项目 A 的会话向项目 B 的会话汇报结果（跨项目消息）。

## 配对规则

发消息前必须**配对**（pair），两种配对方式：

| 方式 | 规则 | 适用 |
|------|------|------|
| ① 同 thread 自动配对 | 两个 session 的 `.goo/current_thread.json` 中 `thread_id` 相同（且均非 null）即自动配对 | 同一计划/同一 thread 内的多个会话 |
| ② `/goo-pair` 显式配对 | 写入 `pairs.json` 配对表，**任意方向**命中即配对 | 跨 thread、跨项目的会话 |

要点：

- 同 thread 自动配对无需任何配置；`session_start` 时从 `.goo/current_thread.json`
  读取 threadId 写入注册表（`utils/plan.ts getCurrentThreadId`，兼容新旧字段
  `current_thread_id` / `thread_id`）。
- 显式配对幂等（重复配对不重复写表）；`/goo-unpair` 只删除显式配对，
  **同 thread 自动配对仍有效**（命令会提示这一点）。
- 不能配对/发给同一个 session；给自己发消息会被拒绝。

## 命令

| 命令 | 说明 |
|------|------|
| `/goo-chat <target> <message>` | 发送消息（target 为别名或 sessionId 前缀） |
| `/goo-chat-read [target]` | 拉取未读消息并注入内容（带 target 只拉该来源，其余放回信箱） |
| `/goo-chat-list` | 列出注册表 + 配对 + 未读消息摘要 |
| `/goo-pair <aliasA> <aliasB>` | 显式配对两个 session |
| `/goo-unpair <aliasA> <aliasB>` | 解除显式配对（同 thread 自动配对仍有效） |
| `/goo-alias <alias>` | 自定义本会话别名（默认 `<项目名>@<序号>`） |

### 使用示例

```text
# 查看注册表/配对/未读
/goo-chat-list
# 发消息给同项目另一会话（自动配对 + 别名）
/goo-chat projX@2 第一版验证通过了，接下来提交
# 跨项目显式配对
/goo-pair projX@1 otherProj@1
# 配对后跨项目发消息
/goo-chat otherProj@1 上游报告请查收
# 拉取未读消息（全部）
/goo-chat-read
# 只拉取某来源的消息，其余保留
/goo-chat-read projX@2
# 解除显式配对
/goo-unpair projX@1 otherProj@1
# 自定义别名
/goo-alias 帮手机器人
```

target 解析规则（`resolveAlias`）：精确匹配 alias 优先；否则 sessionId
**前缀匹配**（至少 8 字符且唯一命中）；多会话共享前缀时不猜测，返回 null 并提示用精确别名。

### 回复指引

拉取到的消息按来源分组注入，格式：

```
📨 来自 <alias>@<project>：<消息内容>
（回复用 /goo-chat <alias> 你的回复）
```

回复时直接用 `/goo-chat <alias> 内容` 即可，无需再次配对（配对状态保留在配对表/threadId 中）。

## 上下文零负担设计

**session_start 只通知，不注入内容**——这是本功能的关键设计（step 4 投递策略调整）：

1. 每次 pi 会话启动，`session_start` hook（index.ts:344-357）执行
   `registerSession → countUnread → peekMailbox`（全部**只读**）。
2. 有未读时仅 `ctx.ui.notify` **数量 + 来源列表**，通知文本**不含消息内容**。
3. 消息内容只有用户**主动** `/goo-chat-read` 拉取时，才经
   `pi.sendUserMessage(deliverAs: "followUp")` 注入到会话（index.ts 全文无
   sendUserMessage 调用，注入仅存在于 `commands/chat.ts` 的 handleGooChatRead）。

好处：多 session 长期异步沟通不会让任何会话的上下文被无关消息膨胀；
「有信」通知零成本，内容按需消费。

## 数据位置

所有数据在**接收方/当前项目**的 `.goo/chat/` 目录（按项目隔离）：

```
.goo/chat/
  sessions.json                     # 注册表 [{sessionId, sessionFile, project, threadId, alias, lastSeen}]
  pairs.json                        # 显式配对表 [{from, to, pairedAt}]
  mailbox/<toSessionId>/            # 待投递消息信箱（按收件方 sessionId）
    <ts>_<fromSessionId>.json       # 消息文件（文件名 = 时间戳_发送方id，同毫秒追加序号 _1/_2 防覆盖）
```

消息文件内容（JSON）：

```json
{
  "from": "<发送方 sessionId>",
  "fromAlias": "<发送方别名>",
  "fromProject": "<发送方项目名>",
  "to": "<接收方 sessionId>",
  "content": "消息内容",
  "ts": "2026-08-17T03:00:00.000Z",
  "threadId": "<发送方 threadId>"
}
```

读写语义：

- 所有 JSON 写入为**原子写**（tmp + rename，与 utils/plan.ts savePlan 一致）。
- `peekMailbox` / `countUnread` **只读不删**（供通知与列表，可重复）。
- `drainMailbox` **读后删**（`/goo-chat-read` 拉取消费）。
- `putBackMessages` 把未注入的消息**放回信箱**（带 target 拉取时保留其余）。
- 损坏 JSON / 非 `.json` 文件**容错跳过**（不阻塞后续投递）。

## 技术要点

- **身份**：`ctx.sessionManager.getSessionId()` 获取当前 sessionId；
  `ctx.sessionManager.getSessionFile()` 获取会话文件路径。
- **注入**：`pi.sendUserMessage(content, { deliverAs: "followUp" })` 把拉取的消息
  注入当前会话（与 commands/other.ts 同模式，需 `setPi(pi)` 注册全局 pi 引用）。
- **自动配对依据**：`.goo/current_thread.json` 的 threadId（`getCurrentThreadId`，
  兼容 `current_thread_id` / `thread_id` 两代字段）。
- **容错**：session_start hook 的 chat 部分整体 `try/catch` + 动态 `import`，
  chat 功能异常不阻断 session 启动。

## 实现文件

| 文件 | 内容 |
|------|------|
| `.pi/extensions/autogoo-plugin/utils/chat.ts` | 注册表 / 配对 / 信箱全部数据逻辑（原子写、容错） |
| `.pi/extensions/autogoo-plugin/commands/chat.ts` | 6 个命令 handler + sendUserMessage 注入 |
| `.pi/extensions/autogoo-plugin/index.ts` | COMMANDS 表注册 + session_start hook（注册 + 通知不注入） |
| `.pi/extensions/autogoo-plugin/__tests__/chat.test.ts` | 19 个单测（step 1 15 + step 4 4） |

## 验证

- 全量单测：`node --import tsx --test` 4 文件 **43/43 通过**（chat 19 + subagent 7 + plan-cycle 7 + status 10）。
- 场景模拟：/tmp/chat-sim/sim.mts **47/47 通过**（配对/投递/peek-drain-putBack 闭环/别名/报错/容错/通知不注入）。
- 语法检查：utils/chat.ts、commands/chat.ts、index.ts `--check` 3/3 OK。
- 代码审读：session_start 只 notify 不注入内容；index.ts 无 sendUserMessage 残留。

详见 Goo-wiki：
[[projects/autogoo-plugin/tasks/task-2026-08-17-session-chat|任务页]] /
[[projects/autogoo-plugin/lessons/2026-08-17-session-chat|可复用经验]]。
