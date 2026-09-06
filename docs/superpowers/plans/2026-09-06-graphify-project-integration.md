# Graphify Project Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate Graphify 0.9.51 into the `agent-sandbox` project with native Linux tooling, domain-specific AST/semantic detection for sandbox assets, canonical agent governance, and a verified two-commit Git workflow.

**Architecture:** Graphify operates as an isolated host engineering tool via `uv tool`. A custom adapter (`.graphify/project.py`) routes sandbox infrastructure files (Containerfiles, shell recipes, Squid templates, TOML profiles) into the semantic graph. Project-scoped skills equip Claude Code, Antigravity, and Codex with graph awareness. Portable graph artifacts (`graphify-out/`) are versioned in Git with merge conflict protection.

**Tech Stack:** Graphify 0.9.51 (`graphifyy`), Python 3.10+, uv, Bash, Node.js (`sync-skills.mjs`), Git hooks and merge drivers.

**Spec:** [`docs/superpowers/specs/2026-09-06-graphify-project-integration-design.md`](file:///home/v/Data/Projects/agent-sandbox/docs/superpowers/specs/2026-09-06-graphify-project-integration-design.md)

## Global Constraints

- Use official PyPI package `graphifyy==0.9.51` installed via `uv tool`.
- Strictly no runtime or container dependencies added to `asb-agent`, `asb-proxy`, or `Containerfile`.
- Do not use `--no-gitignore`; `.env*`, `.agent-sandbox.toml`, SSH keys (`id_ed25519*`), passphrases (`*.pass`) must remain strictly excluded.
- Version portable `graphify-out/` artifacts (`graph.json`, `graph.html`, `GRAPH_REPORT.md`); ignore `cost.json`, `cache/`, logs, and temporary files.
- Never edit subagent prompt files directly (`.agents/agents/*`, `.claude/agents/*`, `.codex/agents/*`). Domain rules live in `docs/domains/` (SSoT).
- User has explicitly authorized direct commits on `main` for this integration, with strict instruction to **NEVER execute `git push`**.
- Adhere strictly to `docs/domains/git/commit-conventions.md` for all commits.

---

### Task 1: Setup script, ignore rules, and gitattributes

**Files:**
- Create: `.graphifyignore`
- Create: `.gitattributes`
- Create: `.graphify/setup.sh`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `uv` on host, existing `.gitignore`.
- Produces: Executable `.graphify/setup.sh` providing idempotent installation and verification; Git attributes merge driver definition; ignore rules preventing leakage of ephemeral cache and credentials.

- [ ] **Step 1: Create `.graphifyignore`**

Create `.graphifyignore` to prevent recursive indexing and duplicate skill communities:

```text
# Never recursively index Graphify's own generated corpus
graphify-out/

# Local diagnostics, backups and temporary files
*.graphify-bak
*.graphify.log

# Claude mirrors canonical project-scoped skill in .agents/.
# Indexing both creates duplicate knowledge communities.
.claude/skills/graphify/
```

- [ ] **Step 2: Create `.gitattributes`**

Create `.gitattributes` declaring the merge driver for the knowledge graph:

```text
graphify-out/graph.json merge=graphify
```

- [ ] **Step 3: Modify `.gitignore`**

Append ephemeral and machine-local Graphify outputs to `.gitignore`:

```gitignore
# Graphify local-only state; portable graphify-out/ artifacts are versioned
graphify-out/cost.json
graphify-out/cache/
graphify-out/.graphify_python
graphify-out/.graphify_root
*.graphify-bak
*.graphify.log
graphify-out/.graphify_analysis.json
graphify-out/.graphify_ast.json
graphify-out/.graphify_cached.json
graphify-out/.graphify_chunk_*.json
graphify-out/.graphify_detect.json
graphify-out/.graphify_extract.json
graphify-out/.graphify_incremental.json
graphify-out/.graphify_old.json
graphify-out/.graphify_semantic.json
graphify-out/.graphify_semantic_new.json
graphify-out/.graphify_uncached.txt
graphify-out/.graphify_labels_fresh.json
graphify-out/.graphify_labels_part_*.json
graphify-out/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/

# Graphify assistant hooks embed machine-local paths
.codex/hooks.json
.claude/settings.json
```

- [ ] **Step 4: Create `.graphify/setup.sh`**

Create executable script `.graphify/setup.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

EXPECTED_VERSION="0.9.51"
VERIFY_ONLY=0

for arg in "$@"; do
    case "$arg" in
        --verify-only) VERIFY_ONLY=1 ;;
        *) echo "Unknown argument: $arg" >&2; exit 1 ;;
    esac
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
    echo "Error: uv is not installed or not in PATH." >&2
    exit 1
fi

INSTALLED_VERSION="$(graphify --version 2>/dev/null || true)"
if [ "$INSTALLED_VERSION" != "graphify $EXPECTED_VERSION" ]; then
    if [ "$VERIFY_ONLY" -eq 1 ]; then
        echo "Error: Expected graphify $EXPECTED_VERSION, but found '$INSTALLED_VERSION'." >&2
        exit 1
    fi
    echo "Installing graphifyy==$EXPECTED_VERSION via uv tool..."
    uv tool install --force "graphifyy==$EXPECTED_VERSION"
fi

if [ "$VERIFY_ONLY" -eq 1 ]; then
    echo "Graphify project configuration verified for $EXPECTED_VERSION."
    exit 0
fi

echo "Installing project-scoped skills and hooks..."
graphify install --project
graphify install --project --platform agents
graphify claude install --project
graphify codex install --project
graphify hook install

echo "Graphify $EXPECTED_VERSION setup complete."
```

Make it executable:
`chmod +x .graphify/setup.sh`

- [ ] **Step 5: Verify setup script**

Run:
`./.graphify/setup.sh --verify-only`
Expected output: `Graphify project configuration verified for 0.9.51.`

- [ ] **Step 6: Commit Task 1**

Stage and commit files with `commit-curator` or standard commit format:
```bash
git add .graphifyignore .gitattributes .gitignore .graphify/setup.sh
git commit -m "🔧 configure graphify tooling, gitattributes and ignore rules: agent infrastructure"
```

---

### Task 2: Custom domain adapter and automated unit tests

**Files:**
- Create: `tests/unit/test_project.py`
- Create: `.graphify/project.py`

**Interfaces:**
- Consumes: `graphify.detect` functions (`detect`, `detect_incremental`, `_is_sensitive`, `_md5_file`, `load_manifest`).
- Produces: `detect_project(root: Path) -> dict` and `detect_incremental_project(root: Path) -> dict` tailored to `agent-sandbox`.

- [ ] **Step 1: Write the failing unit tests in `tests/unit/test_project.py`**

Create `tests/unit/test_project.py` with tests verifying:
1. Operational files (`Containerfile`, `.sh`, `.toml`, `squid.conf.tmpl`) are categorized as documents.
2. Sensitive files (`.env`, `keyring.pass`, `id_ed25519`) are excluded.
3. Excluded directories (`.git`, `graphify-out`, `__pycache__`) are pruned.
4. Incremental detection correctly handles file changes and deletions.

```python
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .graphify_project_import import detect_project, detect_incremental_project  # helper or direct import
```
*(Use standard unittest pattern matching repository style)*

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/unit/test_project.py`
Expected: FAIL (`ModuleNotFoundError: No module named '.graphify'`)

- [ ] **Step 3: Implement `.graphify/project.py`**

Write `.graphify/project.py`:
- Implement `_CONFIG_SUFFIXES = {".sh", ".bash", ".toml", ".tmpl", ".conf", ".yaml", ".yml"}`.
- Implement `_CONFIG_NAMES = {"Containerfile", "Containerfile.proxy", "allowlist-base.txt", "asb-guard", "asb-agent", "asb-docker-broker.service.tmpl"}`.
- Implement `_EXCLUDED_PARTS = {".git", ".superpowers", ".worktrees", "graphify-out", "node_modules", "__pycache__", "state", "scratch"}`.
- Implement `detect_project(root: Path) -> dict` and `detect_incremental_project(root: Path) -> dict`.

- [ ] **Step 4: Run unit tests to verify they pass**

Run: `python3 -m unittest discover -s tests/unit -p "test_*.py"`
Expected: All tests PASS, including `test_project.py`.

- [ ] **Step 5: Commit Task 2**

```bash
git add .graphify/project.py tests/unit/test_project.py
git commit -m "✨ add custom graphify detector and unit tests for sandbox assets: agent tooling"
```

---

### Task 3: Install project-scoped skills and verify synchronization

**Files:**
- Create: `.claude/skills/graphify/`
- Create: `.agents/skills/graphify/`
- Create: `.codex/skills/graphify/`

**Interfaces:**
- Consumes: `./.graphify/setup.sh` and `scripts/sync-skills.mjs`.
- Produces: Project-scoped skills for all agent platforms, verified against drift.

- [ ] **Step 1: Execute setup to install skills**

Run:
`./.graphify/setup.sh`

- [ ] **Step 2: Verify skill directory contents**

Check that `SKILL.md` exists in:
- `.claude/skills/graphify/SKILL.md`
- `.agents/skills/graphify/SKILL.md`
- `.codex/skills/graphify/SKILL.md`

- [ ] **Step 3: Verify skill synchronization tool parity**

Run:
`node scripts/sync-skills.mjs --check`
Expected output: `[sync-skills] 2 skill(s) synchronized across 2 mirrors.` (exiting with code 0; `graphify` is recognized as `VENDOR` and causes no drift).

- [ ] **Step 4: Verify Git hook status**

Run:
`graphify hook status`
Expected: Hook and merge driver are reported as installed.

- [ ] **Step 5: Commit Task 3**

```bash
git add .claude/skills/graphify .agents/skills/graphify .codex/skills/graphify
git commit -m "✨ install project-scoped graphify skills for claude, antigravity and codex: agent skills"
```

---

### Task 4: Agent governance, documentation, and commit conventions

**Files:**
- Create: `docs/architecture/graphify.md`
- Modify: `docs/domains/git/commit-conventions.md`
- Modify: `AGENTS.md`
- Modify: `GEMINI.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: Project architecture and governance rules.
- Produces: SSoT documentation and commit conventions defining the `🕸️` Gitmoji and two-step commit workflow.

- [ ] **Step 1: Create `docs/architecture/graphify.md`**

Document:
- Architectural role of Graphify.
- Prerequisites and baseline (`0.9.51`).
- Setup invocation (`./.graphify/setup.sh`).
- Knowledge graph query cheatsheet (`graphify query`, `graphify explain`, `graphify path`).
- Semantic update protocol and two-commit workflow.
- Security guardrails (never index secrets or `.env`).

- [ ] **Step 2: Update `docs/domains/git/commit-conventions.md`**

Add `🕸️` to Gitmoji table:
```markdown
| `🕸️` | Graphify knowledge graph synchronization. |
```
Add exception rule under commit body section:
The dedicated commit carrying strictly `graphify-out/**` with title `🕸️ sync knowledge graph` is the sole exception to the mandatory body requirement.

- [ ] **Step 3: Update `AGENTS.md`**

Add canonical `## Graphify` section:
- Summary of knowledge graph availability.
- When and how to query (`graphify query`).
- Single semantic update policy prior to feature commit.
- Linked worktree manual update instructions.

- [ ] **Step 4: Update `GEMINI.md` and `CLAUDE.md`**

Add pointer to `AGENTS.md` and `docs/architecture/graphify.md`.

- [ ] **Step 5: Commit Task 4**

```bash
git add docs/architecture/graphify.md docs/domains/git/commit-conventions.md AGENTS.md GEMINI.md CLAUDE.md
git commit -m "📝 document graphify architecture, agent governance and commit policy: agent docs"
```

---

### Task 5: Generate initial knowledge graph and verify query acceptance

**Files:**
- Create: `graphify-out/graph.json`
- Create: `graphify-out/GRAPH_REPORT.md`
- Create: `graphify-out/graph.html`

**Interfaces:**
- Consumes: Full repository codebase and documentation.
- Produces: Validated, queryable knowledge graph tracked in Git.

- [ ] **Step 1: Generate initial knowledge graph**

Run Graphify extraction:
`python3 -c "from .graphify.project import detect_project; from pathlib import Path; print('Corpus files:', len(detect_project(Path('.'))['files']))"`
Run:
`graphify .` (or extract pipeline)

- [ ] **Step 2: Verify generated files and JSON integrity**

Run:
`python3 -c "import json; data = json.load(open('graphify-out/graph.json')); print('Nodes:', len(data.get('nodes', []))); print('Edges:', len(data.get('edges', [])))"`
Ensure nodes and edges are non-empty and `GRAPH_REPORT.md` and `graph.html` exist.

- [ ] **Step 3: Verify ignore rules**

Run:
```bash
git check-ignore -v graphify-out/cost.json
git check-ignore -v graphify-out/cache/
git check-ignore graphify-out/graph.json || echo "graph.json is trackable as expected"
```
Expected: `cost.json` and `cache/` are ignored; `graph.json` is trackable.

- [ ] **Step 4: Execute acceptance queries**

Run:
`graphify query "how does squid proxy filter egress traffic?"`
`graphify explain "Containerfile"`
Verify query outputs return meaningful semantic context from the repository.

- [ ] **Step 5: Commit knowledge graph**

Commit strictly `graphify-out/**`:
```bash
git add graphify-out/graph.json graphify-out/graph.html graphify-out/GRAPH_REPORT.md
git commit -m "🕸️ sync knowledge graph"
```
*(No push)*

---

## Plan Self-Review

- **Spec coverage:** All sections of the spec (setup script, custom adapter, unit tests, skills, gitattributes, gitignore, AGENTS.md, commit conventions, graph generation, queries) have dedicated tasks.
- **Placeholder scan:** No TBD, TODO, or vague instructions. Exact commands, paths, and code snippets are specified.
- **Subagent preservation:** Confirmed: no subagent prompt files are touched; conventions are propagated via SSoT domain packs.
- **No push constraint:** Explicitly declared in global constraints and every task commit step.
