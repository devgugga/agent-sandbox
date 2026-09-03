@AGENTS.md

@AGENTS.md

# Claude Code Configuration

Project-wide governance, engineering guidelines, and agent workflow standards are defined in `AGENTS.md` (imported above).

## Available Subagents (`.claude/agents/`)

* [`commit-curator`](.claude/agents/git/commit-curator.md): Normalizes and creates standardized local commits with Gitmoji and mandatory structured body.

## Skills (`.claude/skills/`)

The directory `.claude/skills/` is the **canonical source of truth** for all skills in this repository. After adding or modifying a skill, run:
```bash
node scripts/sync-skills.mjs
```

