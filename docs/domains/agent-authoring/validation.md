# Agent & Skill Validation

Verification checklists and governance for agent configurations.

## Verification Checklist

1. **Clear Definition:** Agent specifies role, trigger conditions, required tools, and operational constraints.
2. **Thin Wrapper:** The wrapper does not duplicate domain rules; it references the appropriate Domain Pack in `docs/domains/`.
3. **Least Privilege:** Permissions restricted to the minimum required (read-only by default; write/bash only when essential).
4. **Syntax Validity:** Valid YAML frontmatter for Markdown and valid TOML syntax for Codex configurations.
5. **Discovery Alignment:** Files positioned strictly according to `platform-layouts.md`.
6. **Skill Parity:** Skills propagated via `node scripts/sync-skills.mjs` with zero drift.
