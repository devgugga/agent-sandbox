# Platform Layouts & Discovery

Discovery paths and configuration formats are defined by official platform contracts.

## 1. Google Antigravity

* **Versioned custom agents:** `.agents/agents/<name>/agent.md`
* **Versioned skills:** `.agents/skills/<name>/SKILL.md`
* **Format:** Markdown with YAML frontmatter (`flash_lite`, `flash`, `inherit`, `pro`), tools list, and execution policy (`commandExecutionPolicy: sandbox`).

## 2. Claude Code

* **Versioned subagents:** `.claude/agents/<domain>/<name>.md`
* **Versioned skills (Source of Truth):** `.claude/skills/<name>/SKILL.md`
* **Format:** Markdown with YAML frontmatter, tools (`Read`, `Grep`, `Glob`, `Bash`), and runtime model identifiers.

## 3. OpenAI Codex

* **Versioned subagents:** `.codex/agents/<domain>/<name>.toml`
* **Versioned skills (Generated mirrors):** `.codex/skills/<name>/SKILL.md`
* **Format:** TOML with `name`, `description`, `model`, `model_reasoning_effort`, and `developer_instructions`.
