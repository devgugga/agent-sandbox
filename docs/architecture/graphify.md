# Graphify Knowledge Graph Architecture

> **Canonical architecture and operational reference** for Graphify integration in `agent-sandbox`. Consumed by developers and AI agents (Google Antigravity, Claude Code, OpenAI Codex).

---

## 1. Architectural Role & Principles

Graphify provides a persistent, queryable knowledge graph of the repository that unifies code AST parsing, documentation, and operational infrastructure files into a navigable semantic model.

Key architectural boundaries:
- **Engineering Tooling Only:** Graphify runs strictly on the developer host as developer and agent tooling. It is **never** a runtime dependency of the `agent-sandbox` software itself.
- **No Container Ingestion:** Graphify is **never** installed into runtime container images (`image/Containerfile`, `image/Containerfile.proxy`, `asb-agent`, `asb-proxy`).
- **Tri-Platform Parity:** Project-scoped skills equip Google Antigravity (`.agents/skills/graphify`), Claude Code (`.claude/skills/graphify`), and OpenAI Codex (`.codex/skills/graphify`) with identical query and navigation capabilities.
- **Git-Native Versioning:** The knowledge graph (`graphify-out/graph.json`, `graphify-out/graph.html`, `graphify-out/GRAPH_REPORT.md`) is versioned directly in Git, protected by a dedicated custom merge driver.

---

## 2. Baseline & Prerequisites

- **Pinned Version:** `graphifyy==0.9.51`
- **Host Toolchain:** Managed via `uv tool` for hermetic host isolation.
- **Runtime Requirement:** Python 3.10+ on the host system.
- **Merge Driver:** Registered in `.gitattributes`:
  ```text
  graphify-out/graph.json merge=graphify
  ```

---

## 3. Setup & Verification

The repository includes an idempotent setup script at [`.graphify/setup.sh`](file:///home/v/Data/Projects/agent-sandbox/.graphify/setup.sh):

```bash
# Verify installation and environment integrity without modifying state
./.graphify/setup.sh --verify-only

# Full idempotent installation: tool pin, project skills, git hook, merge driver
./.graphify/setup.sh
```

The setup script guarantees:
1. `graphifyy==0.9.51` is installed via `uv tool`.
2. Project-scoped skills are deployed across `.claude/skills/`, `.agents/skills/`, and `.codex/skills/`.
3. Git post-commit / post-checkout hooks and merge driver configurations are active (`graphify hook status`).

---

## 4. Domain-Specific Ingestion (`.graphify/project.py`)

Standard Graphify AST extractors target source languages. For `agent-sandbox`, the custom adapter at [`.graphify/project.py`](file:///home/v/Data/Projects/agent-sandbox/.graphify/project.py) routes infrastructure, automation, and operational configuration files into the semantic graph as documents:

- **Shell scripts and CLI executables:** `.sh`, `.bash`, `cli/asb-guard`, `cli/asb-agent`.
- **Container specifications:** `image/Containerfile`, `image/Containerfile.proxy`.
- **Proxy and network templates:** `image/squid/squid.conf.tmpl`, `image/squid/allowlist-base.txt`.
- **System services & sandbox profiles:** `broker/*.service.tmpl`, `profiles/*.toml`.

---

## 5. Security Guardrails & Exclusions

Sensitive data, credentials, and transient execution state must **never** enter the knowledge graph or Git repository:

1. **Active Exclusions in Ingestion (`.graphify/project.py`):**
   - Credentials & secrets: `.env*`, `.agent-sandbox.toml`, SSH keys (`id_ed25519*`), passphrases (`*.pass`, `keyring.pass`).
   - Volatile and runtime directories: `.git/`, `graphify-out/`, `state/`, `scratch/`, `dist/`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.superpowers/`.
   - File size ceiling: Files exceeding 1 MB are bypassed to prevent token explosion and parser stalling.
2. **Git Ignore Rules (`.gitignore` & `.graphifyignore`):**
   - Ephemeral cache and cost files (`graphify-out/cache/`, `graphify-out/cost.json`, intermediate `.graphify_*.json`, logs, backups) are ignored.
   - Machine-specific configuration (`.claude/settings.json`, `.codex/hooks.json`) is ignored.
   - Portable graph artifacts (`graph.json`, `graph.html`, `GRAPH_REPORT.md`) are explicitly tracked.

---

## 6. Query Cheatsheet

When `graphify-out/graph.json` is present, agents and engineers should query the graph before performing expensive brute-force file searches:

```bash
# BFS traversal for broad context and conceptual explanations
graphify query "how does squid proxy filter egress traffic?"

# DFS traversal to trace execution paths, dependencies, or call stacks
graphify query "trace configuration load path in asb profile manager" --dfs

# Plain-language explanation of a specific entity, node, or component
graphify explain "Containerfile"
graphify explain "asb-guard"

# Shortest path between two architectural concepts or components
graphify path "SquidProxy" "ProfileManager"
```

---

## 7. Semantic Update Protocol & Two-Commit Workflow

To keep Git diffs clean and prevent graph re-extraction thrashing during active development, updates follow a deterministic protocol:

### Single Semantic Update
Execute graph re-indexing **once**, only after code changes, tests, and self-reviews are stable and passing, immediately before committing:

```bash
# Incremental update of new and modified files
graphify update .
```

### Two-Commit Workflow
Knowledge graph updates are **never** bundled into the same Git commit as product code or infrastructure changes:

1. **Commit 1: Implementation / Code Changes**
   - Stage code, tests, and documentation: `git add <files>` (excluding `graphify-out/**`).
   - Format commit message with mandatory structured body wrapped at 76 columns, following [`docs/domains/git/commit-conventions.md`](file:///home/v/Data/Projects/agent-sandbox/docs/domains/git/commit-conventions.md).
2. **Commit 2: Knowledge Graph Synchronization**
   - Update knowledge graph: `graphify update .`
   - Stage strictly graph artifacts:
     ```bash
     git add graphify-out/graph.json graphify-out/graph.html graphify-out/GRAPH_REPORT.md
     ```
   - Commit with exact title:
     ```bash
     git commit -m "🕸️ sync knowledge graph"
     ```
   - **Exception Rule:** This synchronization commit is the **sole exception** where the mandatory structured body is omitted.

---

## 8. Linked Worktrees & Headless Environments

In linked Git worktrees (e.g. temporary worktrees created under `.worktrees/`) or headless container environments:
- Git hooks installed in `.git/hooks` of the main worktree may not trigger automatically in secondary worktrees.
- If graph synchronization is needed in a worktree, invoke manual update:
  ```bash
  graphify update .
  ```
- Always verify environment health before operations:
  ```bash
  ./.graphify/setup.sh --verify-only
  ```
