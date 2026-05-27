# AutoGoo Skill Design

AutoGoo is a workflow skill, not a monolithic prompt. Keep the entrypoint small, push detail into references, and turn repeatable mechanics into scripts so the agent spends tokens on judgment instead of bookkeeping.

## Context Budget

- Keep `SKILL.md` as the routing and lifecycle entrypoint.
- Put long rules, schemas, examples, prompt variants, and checklists in `references/`.
- Link each support file directly from `SKILL.md`; avoid reference chains that require opening several files to find the actual rule.
- Prefer a script that emits a compact packet over asking the agent to read many Markdown files.
- Script stdout should be concise and machine-readable when possible; verbose status belongs on stderr.

## Skill Anatomy

AutoGoo's entrypoint should always make these parts easy to find:

- Trigger conditions: when AutoGoo should and should not run.
- Phase workflow: init, recall, plan, execute, optimize, archive, improve.
- Verification gates: what evidence proves each phase completed.
- Failure modes: common shortcuts the agent must not rationalize.
- References and scripts: direct paths to deeper material and reusable helpers.

## Anti-Rationalizations

| Shortcut | Why It Fails | Required Behavior |
| --- | --- | --- |
| "This task is small enough to skip planning." | Multi-step work drifts without a state file. | If the task has multiple dependent actions, write or update `.goo/plan.json`. |
| "The wiki can be updated at the end from memory." | Conversation context is lossy and expensive. | Capture `context_digest` / `context_artifacts` while decisions are made. |
| "I'll read the whole wiki to find links." | Large Markdown reads waste tokens and reduce focus. | Run `scripts/wiki-graph-assist.py` first and read full pages only when the compact packet is insufficient. |
| "The final output looks right." | AutoGoo is meant to be recoverable and auditable. | Record evidence: commands, outputs, artifact paths, verification results, and archive links. |
| "A subagent can figure out the missing context." | Subagents do not share the main conversation by default. | Put required context in plan fields, artifacts, or explicit prompt inputs before dispatch. |

## Verification Gates

Before considering AutoGoo changes ready:

- `bash "$auto_goo_root/skills/auto-goo/scripts/check-plugin.sh"` passes after `auto_goo_root` is resolved from `~/.claude/plugins/installed_plugins.json` and `skills/auto-goo/scripts/check-plugin.sh` is verified to exist.
- New or changed scripts have valid syntax checks.
- Docs, command files, templates, and generated init blocks agree on any changed behavior.
- Any token-saving rule has a concrete script, config field, or checklist behind it.
