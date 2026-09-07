# AGENTS.md

> **Canonical, tool-agnostic source of truth** for all AI agents working in this repository (Google Antigravity, Claude Code, OpenAI Codex, Gemini CLI, …). Tool-specific entry points (`CLAUDE.md`, `GEMINI.md`) reference this file. Keep core behavioral rules here; domain knowledge lives in `docs/domains/`.

---

## 1. Agent Architecture: "Domain Packs"

Domain knowledge lives **once**, in neutral Markdown under [`docs/domains/`](./docs/domains/README.md), and is consumed by all AI tools:

```text
docs/domains/<domain>/    ← Portable knowledge base (Single Source of Truth - SSoT)
.agents/agents/<name>/    ← Google Antigravity subagents (thin wrappers)
.claude/agents/<domain>/  ← Claude Code subagents (thin wrappers)
.codex/agents/<domain>/   ← OpenAI Codex subagents (thin wrappers)
.claude/skills/           ← Modular skills (repeatable workflows) — SOURCE OF TRUTH
.agents/skills/           ← Generated mirror for Antigravity  (node scripts/sync-skills.mjs)
.codex/skills/            ← Generated mirror for OpenAI Codex (node scripts/sync-skills.mjs)
```

**Golden Rule:** An agent or skill never duplicates domain rules in its prompt. It instructs the model to read `docs/domains/<domain>/*.md`. When a convention changes, edit the document in the domain pack once — all agents inherit the update immediately.

---

## 2. Available Subagents

| Subagent | Supported Platforms | Mode | Role & Responsibility |
| :--- | :--- | :--- | :--- |
| `commit-curator` | Antigravity, Claude Code, Codex | Read-Write | Normalizes and authors local Git commits adhering to Gitmoji, safe scope, structured body, and branch governance. |

---

## 3. Fundamental Engineering Guidelines

### 1. Think Before Coding
- Do not assume undeclared intent. If requirements are ambiguous, ask and clarify before acting.
- Explicitly present technical tradeoffs and simpler alternatives before implementing.

### 2. Simplicity First
- Write minimal, surgical code that strictly solves the presented problem.
- Avoid premature abstractions, unnecessary layers, or speculative features (ruthless YAGNI).

### 3. Surgical Changes
- Touch only what is strictly necessary to satisfy the request.
- Do not "improve" unrelated code, nor reformat files outside the active task scope.
- Every line modified in the diff must directly serve the current goal.

### 4. Goal-Driven Execution
- Establish objective success criteria and tests before making changes.
- Validate modifications with real compilation, linting, or test execution before claiming completion. Empirical evidence always precedes assertions of success.

---

## 4. Agent Workflow & Operational Rules

### 1. Specification Before Implementation (Spec-Driven)
- Complex or architectural tasks require an agreed specification and plan before modifying code.
- Deterministic workflow: Spec → Plan → Subagent Execution → Automated Verification → Human Gate.

### 2. Context Hygiene & Progressive Disclosure
- Maintain minimal context. Load Domain Packs from `docs/domains/` strictly on demand (*Just-in-Time*).
- Agent and skill wrappers must remain thin and declarative.

### 3. Least Privilege & Role Separation
- Reviewer agents must be Read-Only. Implementation agents must have minimal tool access.
- Subagents operate with narrow, well-bounded scopes (Single Responsibility Principle).

### 4. Verification Before Assertions
- Treat all AI-generated code as untrusted input.
- Run tests, linters, and inspect `git diff` before claiming completion. Never claim success without empirical evidence.

### 5. Human Gatekeeper
- The human engineer is the ultimate decision maker and domain authority.
- Never commit directly to `main`/`master`, apply destructive migrations, or run `git push` without explicit human authorization.

---

## 5. Skills: Single Source of Truth & Synchronization

- **Source of truth:** `.claude/skills/<name>/SKILL.md`.
- **Generated mirrors (NEVER edit directly):** `.agents/skills/` (Antigravity) and `.codex/skills/` (Codex).
- Every mirror file contains a generated banner and is overwritten on sync.
- Workflow:
  ```bash
  # 1. Edit or create in .claude/skills/<name>/SKILL.md
  # 2. Propagate to mirrors
  node scripts/sync-skills.mjs
  # 3. Verify parity (CI check)
  node scripts/sync-skills.mjs --check
  ```

---

## 6. Git & Commit Governance

All commits must follow [`docs/domains/git/commit-conventions.md`](./docs/domains/git/commit-conventions.md):
- **Literal Gitmoji** character in the title.
- **Mandatory structured body** wrapped at 76 columns (`### ✅ New features`, `### 💡 Architecture improvements`, `### 🧼 Best practices & validations`, `### 🔐 Security & Access Control`, `### 🚀 Outcome`).
- AI attribution trailers (`Co-authored-by`) are strictly prohibited.
- Use the `commit-curator` subagent to curate and format commits.

---

## 7. Graphify

The repository maintains an automated, persistent knowledge graph in `graphify-out/` (`graph.json`, `GRAPH_REPORT.md`) documenting code architecture, dependencies, and operational assets. The interactive web visualizer (`graph.html`) is ignored and generated strictly on demand via `graphify export html`.

### 1. Fast Path Querying
When `graphify-out/graph.json` exists, agents must treat codebase architecture and relationship questions as Graphify queries first rather than brute-force grepping:
- `graphify query "<question>"`: BFS search for broad conceptual relationships and flows.
- `graphify query "<question>" --dfs`: DFS traversal to trace specific dependency chains.
- `graphify explain "<concept>"`: Explains a node, component, or configuration file.
- `graphify path "<source>" "<target>"`: Identifies shortest architectural path between components.

### 2. Semantic Update Timing
Do not run graph rebuilds continuously during development. Run an incremental semantic update **once**, when implementation, tests, and code reviews are stable, immediately before committing:
```bash
graphify update .
```

### 3. Rebuild Pause During Plan Execution
The `post-commit` hook rebuilds the graph after **every** commit, which defeats §7.2: each code commit leaves `graphify-out/` dirty and produces a paired `🕸️ sync knowledge graph` commit. Measured on `feat/startup-auth-redesign`: 7 of 14 commits were graph syncs, carrying 28363 lines of `graphify-out/` churn against 5619 lines of actual work, and inflating code-review diffs roughly sixfold.

Pause the automatic rebuild for the duration of a plan execution, then run the single update §7.2 requires:
```bash
touch  "$(git rev-parse --git-common-dir)/graphify-pause"   # pause
rm -f  "$(git rev-parse --git-common-dir)/graphify-pause"   # resume
```
The sentinel gates only the hook. An explicit `graphify update .` still works, so an agent that genuinely needs a fresh graph mid-implementation runs it and commits the graph deliberately, per §7.4.

`.git/hooks/` is not versioned and `graphify hook install` overwrites the hook; `./.graphify/setup.sh` re-applies the pause guard after installing hooks.

### 4. Two-Commit Workflow
Knowledge graph updates are versioned in a dedicated second commit following [`docs/domains/git/commit-conventions.md`](./docs/domains/git/commit-conventions.md):
1. **Feature/Code Commit:** Code and docs without `graphify-out/**`, containing the mandatory structured body.
2. **Graph Sync Commit:** Strictly `graphify-out/**` with title `🕸️ sync knowledge graph` (sole exception where structured body is omitted).

### 5. Linked Worktrees & Environment Setup
In linked Git worktrees (e.g. `.worktrees/`) or new workspaces, Git hooks may not trigger automatically. Run manual updates or environment verification when needed:
```bash
./.graphify/setup.sh --verify-only
```
For complete architectural details and security guardrails, refer to [`docs/architecture/graphify.md`](./docs/architecture/graphify.md).
