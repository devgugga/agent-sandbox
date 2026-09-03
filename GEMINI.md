# Google Antigravity & Gemini CLI Configuration

This project adheres to the conventions and guidelines established in the canonical [`AGENTS.md`](./AGENTS.md).

## Available Subagents (`.agents/agents/`)

* [`commit-curator`](.agents/agents/commit-curator/agent.md): Subagent for local commit normalization and branch governance.

## Skills (`.agents/skills/`)

Skills for Google Antigravity in `.agents/skills/` are mirrors synchronized from `.claude/skills/` via:
```bash
node scripts/sync-skills.mjs
```
Refer to `AGENTS.md` and `docs/domains/agent-authoring/` before creating or updating agents and skills.
