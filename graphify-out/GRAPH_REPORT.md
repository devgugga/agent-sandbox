# Graph Report - agent-sandbox  (2026-09-06)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 659 nodes · 1129 edges · 48 communities (37 shown, 11 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 52 edges (avg confidence: 0.79)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `eea01eb4`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- lifecycle.py
- layout_for
- assert.sh
- load_profile
- build_staging
- Profile
- patch
- permitted
- What You Must Do When Invoked
- __init__.py
- What You Must Do When Invoked
- ProjectDetectionTest
- common.sh
- sync-skills.mjs
- install.py
- Graphify Knowledge Graph Architecture
- AGENTS.md
- graphify reference: extra exports and benchmark
- /graphify
- graphify reference: extra exports and benchmark
- Git Commit Conventions
- 4. Agent Workflow & Operational Rules
- graphify reference: query, path, explain
- graphify reference: query, path, explain
- 7. Graphify
- 3. Fundamental Engineering Guidelines
- Claude Code Configuration
- asb-guard
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native AGENTS.md integration
- graphify reference: incremental update and cluster-only
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: incremental update and cluster-only
- Google Antigravity & Gemini CLI Configuration
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- entrypoint.sh
- test-guard.sh
- test-recipe.sh
- .agents/skills/graphify/references/extraction-spec.md
- .codex/skills/graphify/references/extraction-spec.md
- reload_allowlist
- shim.template.sh

## God Nodes (most connected - your core abstractions)
1. `load_profile()` - 35 edges
2. `up()` - 25 edges
3. `layout_for()` - 21 edges
4. `repo_with()` - 21 edges
5. `run()` - 20 edges
6. `build_staging()` - 20 edges
7. `exists()` - 18 edges
8. `PodmanError` - 17 edges
9. `Profile` - 17 edges
10. `render()` - 16 edges

## Surprising Connections (you probably didn't know these)
- `TestPull` --uses--> `PodmanError`  [INFERRED]
  tests/unit/test_doctor.py → cli/asb/podman.py
- `TestPurge` --uses--> `PodmanError`  [INFERRED]
  tests/unit/test_doctor.py → cli/asb/podman.py
- `TestPodmanBinary` --uses--> `PodmanError`  [INFERRED]
  tests/unit/test_podman.py → cli/asb/podman.py
- `TestPodmanKindAndStatus` --uses--> `PodmanError`  [INFERRED]
  tests/unit/test_podman.py → cli/asb/podman.py
- `TestPodmanRun` --uses--> `PodmanError`  [INFERRED]
  tests/unit/test_podman.py → cli/asb/podman.py

## Import Cycles
- None detected.

## Communities (48 total, 11 thin omitted)

### Community 0 - "lifecycle.py"
Cohesion: 0.05
Nodes (71): Any, ArgumentParser, build_parser(), main(), check_workspace_egress(), doctor(), _host_version(), _image_version() (+63 more)

### Community 1 - "layout_for"
Cohesion: 0.10
Nodes (23): _git(), layout_for(), prepare_clone(), Exception, Path, cli/asb/workspace.py — identidade do workspace, layout em disco e clone. Duas…, Identidade do workspace, sempre reproduzivel a partir das entradas. O Orca…, Onde tudo mora. `home` e o mesmo caminho no host e no container (D4). (+15 more)

### Community 2 - "assert.sh"
Cohesion: 0.08
Nodes (20): assert_contains(), assert_eq(), assert_fails(), report(), require(), assert.sh script, sa(), test-agents-behind-proxy.sh script (+12 more)

### Community 3 - "load_profile"
Cohesion: 0.10
Nodes (24): _choice(), load_profile(), _ports(), ProfileError, _publish_ports(), Exception, Path, cli/asb/profile.py — le .agent-sandbox.toml e devolve um perfil validado. O… (+16 more)

### Community 4 - "build_staging"
Cohesion: 0.10
Nodes (29): _allowed_destination_roots(), _allowed_symlink_roots(), build_staging(), copy_file(), denied(), filter_claude_settings(), filter_codex_config(), _key() (+21 more)

### Community 5 - "Profile"
Cohesion: 0.09
Nodes (22): Profile, normalize_domains(), Exception, Path, cli/asb/squid.py — junta a allowlist base com o perfil e emite squid.conf. A…, read_base(), render(), SquidError (+14 more)

### Community 6 - "patch"
Cohesion: 0.09
Nodes (9): patch, Testes de cli/asb/doctor.py e pull/purge em cli/asb/lifecycle.py., Defasagem entre a versao assada na imagem e a instalada no host. O host e a…, Sem o link o CLI so roda de dentro do checkout, e isso fica mudo., TestCheckWorkspaceEgress, TestDoctor, TestPull, TestPurge (+1 more)

### Community 7 - "permitted"
Cohesion: 0.10
Nodes (12): Handler, main(), permitted(), relay(), Server, socket, Testa cli/asb/install.py broker()., Testa a função permitted(method, target) do broker. (+4 more)

### Community 8 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 9 - "__init__.py"
Cohesion: 0.10
Nodes (8): Testes de autenticação e volume de credenciais em cli/asb/lifecycle.py., A verificacao do login tem de EXERCITAR autenticacao. `asb-agy --version`…, TestAuthLifecycle, TestVerificacaoDeLogin, Testes de cli/asb/install.py — instaladores do host., O CLI precisa rodar de qualquer diretorio, nao so do checkout. Ele ja funciona…, Modo de falha da §16.1: a pasta muda de lugar e o link fica orfao., TestInstallGuards

### Community 10 - "What You Must Do When Invoked"
Cohesion: 0.13
Nodes (15): Part A - Structural extraction for code files, Part B - Semantic extraction (parallel subagents), Part C - Merge AST + semantic into final extraction, Step 0 - GitHub repos and multi-path merge (only if a URL or several paths), Step 1 - Ensure graphify is installed, Step 2.5 - Video and audio (only if video files detected), Step 2 - Detect files, Step 3 - Extract entities and relationships (+7 more)

### Community 12 - "common.sh"
Cohesion: 0.26
Nodes (7): asb_recipe_json(), asb_workspace_id(), common.sh script, create.sh script, destroy.sh script, resume.sh script, suspend.sh script

### Community 13 - "sync-skills.mjs"
Cohesion: 0.17
Nodes (8): BANNER_LINES, CHECK, __dirname, MIRRORS, PRUNE, ROOT, skills, VENDOR

### Community 14 - "install.py"
Cohesion: 0.24
Nodes (10): broker(), guards(), _link(), podman_restart(), Path, cli/asb/install.py — o que o sandbox instala no host. Regra da §16: tudo aqui e…, Habilita a unidade que o proprio podman ja instala. `podman start --all…, Symlink para o checkout, nunca copia: uma copia envelhece em silencio e o… (+2 more)

### Community 15 - "Graphify Knowledge Graph Architecture"
Cohesion: 0.14
Nodes (11): 1. Architectural Role & Principles, 2. Baseline & Prerequisites, 3. Setup & Verification, 4. Domain-Specific Ingestion (`.graphify/project.py`), 5. Security Guardrails & Exclusions, 6. Query Cheatsheet, 7. Semantic Update Protocol & Two-Commit Workflow, 8. Linked Worktrees & Headless Environments (+3 more)

### Community 16 - "AGENTS.md"
Cohesion: 0.28
Nodes (4): 1. Agent Architecture: "Domain Packs", 2. Available Subagents, 5. Skills: Single Source of Truth & Synchronization, 6. Git & Commit Governance

### Community 17 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 18 - "/graphify"
Cohesion: 0.22
Nodes (9): For /graphify add and --watch, For /graphify query, For the commit hook and native AGENTS.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Usage (+1 more)

### Community 19 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 20 - "Git Commit Conventions"
Cohesion: 0.25
Nodes (8): 1. Authority and Branching Rules, 2. Safe Scope Selection (Surgical Changes), 3. Prerequisites & Empirical Verification, 4. Commit Message Format, 5. Attribution, Commit Body (Mandatory), Git Commit Conventions, Gitmoji Selection

### Community 21 - "4. Agent Workflow & Operational Rules"
Cohesion: 0.33
Nodes (6): 1. Specification Before Implementation (Spec-Driven), 2. Context Hygiene & Progressive Disclosure, 3. Least Privilege & Role Separation, 4. Agent Workflow & Operational Rules, 4. Verification Before Assertions, 5. Human Gatekeeper

### Community 22 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 23 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 24 - "7. Graphify"
Cohesion: 0.40
Nodes (5): 1. Fast Path Querying, 2. Semantic Update Timing, 3. Two-Commit Workflow, 4. Linked Worktrees & Environment Setup, 7. Graphify

### Community 25 - "3. Fundamental Engineering Guidelines"
Cohesion: 0.40
Nodes (5): 1. Think Before Coding, 2. Simplicity First, 3. Fundamental Engineering Guidelines, 3. Surgical Changes, 4. Goal-Driven Execution

### Community 26 - "Claude Code Configuration"
Cohesion: 0.40
Nodes (4): Available Subagents (`.claude/agents/`), Claude Code Configuration, Knowledge Graph (`graphify-out/`), Skills (`.claude/skills/`)

### Community 27 - "asb-guard"
Cohesion: 0.80
Nodes (4): asb-guard script, launch(), launched_by_orca(), resolve_real()

### Community 28 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 29 - "graphify reference: commit hook and native AGENTS.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native AGENTS.md integration, graphify reference: commit hook and native AGENTS.md integration

### Community 30 - "graphify reference: incremental update and cluster-only"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

### Community 31 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 32 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 33 - "graphify reference: incremental update and cluster-only"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

### Community 34 - "Google Antigravity & Gemini CLI Configuration"
Cohesion: 0.50
Nodes (4): Available Subagents (`.agents/agents/`), Google Antigravity & Gemini CLI Configuration, Knowledge Graph (`graphify-out/`), Skills (`.agents/skills/`)

### Community 44 - "reload_allowlist"
Cohesion: 0.21
Nodes (8): discover_mise_dirs(), Encontra todos os diretorios que contem mise.toml, podando pastas irrelevantes., Recarrega a allowlist do proxy sem tocar no container do agente. Preserva a…, reload_allowlist(), Layout, A politica de egresso e do operador, nunca do agente. `layout.project_root`…, TestDiscoverMiseDirs, TestReloadAllowlist

## Knowledge Gaps
- **133 isolated node(s):** `Part A - Structural extraction for code files`, `Part B - Semantic extraction (parallel subagents)`, `Part C - Merge AST + semantic into final extraction`, `Step 0 - GitHub repos and multi-path merge (only if a URL or several paths)`, `Step 1 - Ensure graphify is installed` (+128 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **11 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `load_profile()` connect `load_profile` to `lifecycle.py`, `reload_allowlist`, `Profile`?**
  _High betweenness centrality (0.060) - this node is a cross-community bridge._
- **Why does `up()` connect `lifecycle.py` to `layout_for`, `load_profile`, `build_staging`, `Profile`, `reload_allowlist`, `common.sh`, `install.py`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Why does `Profile` connect `Profile` to `lifecycle.py`, `load_profile`?**
  _High betweenness centrality (0.051) - this node is a cross-community bridge._
- **What connects `Part A - Structural extraction for code files`, `Part B - Semantic extraction (parallel subagents)`, `Part C - Merge AST + semantic into final extraction` to the rest of the system?**
  _133 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `lifecycle.py` be split into smaller, more focused modules?**
  _Cohesion score 0.054075235109717866 - nodes in this community are weakly interconnected._
- **Should `layout_for` be split into smaller, more focused modules?**
  _Cohesion score 0.09872241579558652 - nodes in this community are weakly interconnected._
- **Should `assert.sh` be split into smaller, more focused modules?**
  _Cohesion score 0.08235294117647059 - nodes in this community are weakly interconnected._