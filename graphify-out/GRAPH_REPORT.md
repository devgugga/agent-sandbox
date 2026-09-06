# Graph Report - agent-sandbox  (2026-09-06)

## Corpus Check
- 103 files · ~102,766 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 971 nodes · 1424 edges · 69 communities (52 shown, 17 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 52 edges (avg confidence: 0.77)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `cc5ab1fb`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- run
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
- Design: agent-sandbox v2
- graphify reference: extra exports and benchmark
- Correções pós-verificação — agent-sandbox v2, BlackICE e hexmed-stack
- graphify reference: extra exports and benchmark
- agent-sandbox v2 — Implementation Plan
- AGENTS.md
- graphify reference: query, path, explain
- graphify reference: query, path, explain
- lifecycle.py
- agent-authoring/README.md
- Design: agent-sandbox
- asb-guard
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native AGENTS.md integration
- graphify reference: incremental update and cluster-only
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: incremental update and cluster-only
- Failure Modes & Forensic Record
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
- names
- Secret Service singleton para credenciais dos agentes
- File Structure
- Recuperação do uplink rootless do Podman
- Configuration Reference (`.agent-sandbox.toml`)
- Sandbox Domain Pack
- Integração project-scoped do Graphify no agent-sandbox
- down
- exists
- Global Constraints
- discover_mise_dirs
- Security Boundaries & Isolation Model
- Orca Reboot Persistence Implementation Plan
- Design: persistência profissional do sandbox no Orca
- 2. Explicit Declarations: What Is NOT Protected
- Skill: Agent Authoring
- Skill: Commit Curator
- Skill: Agent Authoring
- Skill: Commit Curator
- Skill: Agent Authoring
- Skill: Commit Curator

## God Nodes (most connected - your core abstractions)
1. `load_profile()` - 35 edges
2. `up()` - 25 edges
3. `layout_for()` - 21 edges
4. `repo_with()` - 21 edges
5. `run()` - 20 edges
6. `build_staging()` - 20 edges
7. `Failure Modes & Forensic Record` - 20 edges
8. `agent-sandbox v2 — Implementation Plan` - 20 edges
9. `Correções pós-verificação — agent-sandbox v2, BlackICE e hexmed-stack` - 19 edges
10. `exists()` - 18 edges

## Surprising Connections (you probably didn't know these)
- `TestPull` --uses--> `PodmanError`  [INFERRED]
  tests/unit/test_doctor.py → cli/asb/podman.py
- `TestPurge` --uses--> `PodmanError`  [INFERRED]
  tests/unit/test_doctor.py → cli/asb/podman.py
- `TestPodmanKindAndStatus` --uses--> `PodmanError`  [INFERRED]
  tests/unit/test_podman.py → cli/asb/podman.py
- `TestPodmanBinary` --uses--> `PodmanError`  [INFERRED]
  tests/unit/test_podman.py → cli/asb/podman.py
- `TestPodmanRun` --uses--> `PodmanError`  [INFERRED]
  tests/unit/test_podman.py → cli/asb/podman.py

## Import Cycles
- None detected.

## Communities (69 total, 17 thin omitted)

### Community 0 - "run"
Cohesion: 0.14
Nodes (16): Any, emit(), A linha que o recipe do Orca consome. A porta e LIDA do podman, nunca…, Religa o workspace. E `podman start`, e so. Nao ha ordem a respeitar por…, resume(), json_out(), out(), PodmanError (+8 more)

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
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native AGENTS.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 12 - "common.sh"
Cohesion: 0.27
Nodes (7): asb_recipe_json(), asb_workspace_id(), common.sh script, create.sh script, destroy.sh script, resume.sh script, suspend.sh script

### Community 13 - "sync-skills.mjs"
Cohesion: 0.17
Nodes (8): BANNER_LINES, CHECK, __dirname, MIRRORS, PRUNE, ROOT, skills, VENDOR

### Community 14 - "install.py"
Cohesion: 0.24
Nodes (10): broker(), guards(), _link(), podman_restart(), Path, cli/asb/install.py — o que o sandbox instala no host. Regra da §16: tudo aqui e…, Habilita a unidade que o proprio podman ja instala. `podman start --all…, Symlink para o checkout, nunca copia: uma copia envelhece em silencio e o… (+2 more)

### Community 15 - "Graphify Knowledge Graph Architecture"
Cohesion: 0.05
Nodes (32): Role, Available Subagents (`.claude/agents/`), Claude Code Configuration, Knowledge Graph (`graphify-out/`), Skills (`.claude/skills/`), 1. Architectural Role & Principles, 2. Baseline & Prerequisites, 3. Setup & Verification (+24 more)

### Community 16 - "Design: agent-sandbox v2"
Cohesion: 0.04
Nodes (48): 10. Documentação, 11. Superfície do CLI, 12. Testes, 13. O que é removido, 14. Riscos, 15. Modos de falha que não podem voltar, 16.1 Regras, 16.2 Dependências, e o que acontece sem cada uma (+40 more)

### Community 17 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 18 - "Correções pós-verificação — agent-sandbox v2, BlackICE e hexmed-stack"
Cohesion: 0.07
Nodes (27): Contexto: dois falsos verdes achados em uso real (JÁ CORRIGIDOS), Correções pós-verificação — agent-sandbox v2, BlackICE e hexmed-stack, Decisão pendente [HUMANO]: destruir ou preservar o workspace, Estado (atualizado 2026-09-05, após a entrega do Gemini), O que já está verificado e NÃO deve ser mexido, Ordem de execução, T10.1 [HUMANO] — o teste que nenhuma suíte substitui, T10.2 — documentar o que `Linger=no` implica (+19 more)

### Community 19 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 20 - "agent-sandbox v2 — Implementation Plan"
Cohesion: 0.08
Nodes (24): agent-sandbox v2 — Implementation Plan, Created, Deleted, File Structure, Global Constraints, Preserved unchanged, Renamed, Self-Review (+16 more)

### Community 21 - "AGENTS.md"
Cohesion: 0.10
Nodes (20): 1. Agent Architecture: "Domain Packs", 1. Fast Path Querying, 1. Specification Before Implementation (Spec-Driven), 1. Think Before Coding, 2. Available Subagents, 2. Context Hygiene & Progressive Disclosure, 2. Semantic Update Timing, 2. Simplicity First (+12 more)

### Community 22 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 23 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 24 - "lifecycle.py"
Cohesion: 0.17
Nodes (17): build(), build_proxy(), ensure_credentials_volume(), ensure_keyring_pass(), ensure_ssh_key(), login(), Path, cli/asb/lifecycle.py — up, down, suspend, resume, purge, pull, build. (+9 more)

### Community 25 - "agent-authoring/README.md"
Cohesion: 0.10
Nodes (16): 1. Architecture Boundaries, 2. Single Source of Truth (SSoT), 3. Scope and Authorization, Agent Authoring Conventions, Core Principle, Escalation Governance, Model Selection & Routing, Workload Classification (+8 more)

### Community 26 - "Design: agent-sandbox"
Cohesion: 0.10
Nodes (20): 10. Sequenciamento, 1. Problema, 2. Decisões, 3.1 Visão geral, 3.2 Rede — arquitetura validada empiricamente, 3.3 Componentes, 3.4 Modos de acesso a dados, 3.5 Credenciais (+12 more)

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

### Community 34 - "Failure Modes & Forensic Record"
Cohesion: 0.10
Nodes (20): 10. Orca Recipe Selector Invisibility, 11. Squid Configuration File Permissions, 12. Missing `--userns=keep-id` on Agent Container, 13. Sibling Worktree Path Collision at Filesystem Root, 14. Claude Code Hanging on Non-Interactive Stdin, 15. Node Header Fetch Failure during Native Module Build, 16. Service Containers Failing under `keep-id` without `--user 0`, 17. Toolchain Installation Failure during Workspace Startup (`up`) (+12 more)

### Community 44 - "reload_allowlist"
Cohesion: 0.26
Nodes (9): Recarrega a allowlist do proxy sem tocar no container do agente. Preserva a…, reload_allowlist(), Layout, Chamado por `down`. NAO toca no mount: la vive o trabalho do agente., Chamado por `purge`, so apos confirmacao explicita do operador., remove_state(), remove_workspace(), A politica de egresso e do operador, nunca do agente. `layout.project_root`… (+1 more)

### Community 48 - "names"
Cohesion: 0.16
Nodes (17): ArgumentParser, build_parser(), main(), check_workspace_egress(), doctor(), _host_version(), _image_version(), _line() (+9 more)

### Community 49 - "Secret Service singleton para credenciais dos agentes"
Cohesion: 0.11
Nodes (17): Global Constraints, Singleton Secret Service Implementation Plan, Task 1: Criar um teste de regressão isolado para o Secret Service, Task 2: Transformar `start-keyring.sh` em serviço singleton, Task 3: Adicionar o ciclo de vida do serviço global, Task 4: Tornar o entrypoint exclusivamente cliente do Secret Service, Task 5: Validar login real no mesmo serviço e diagnosticar falhas, Task 6: Atualizar o SSoT e executar a verificação completa (+9 more)

### Community 50 - "File Structure"
Cohesion: 0.12
Nodes (16): agent-sandbox Implementation Plan, File Structure, Global Constraints, Self-Review, Task 0: Helper de asserção, Task 10: Domain pack e extensão aos demais projetos, Task 11: Tornar o sandbox o único caminho, Task 1: Imagem base com host keys estáveis (+8 more)

### Community 51 - "Recuperação do uplink rootless do Podman"
Cohesion: 0.13
Nodes (13): Global Constraints, Rootless Uplink Recovery Implementation Plan, Task 1: Encapsular a inicialização do namespace rootless, Task 2: Aplicar o helper em `up` e `resume`, Task 3: Preparar o uplink antes da restauração no login, Task 4: Documentar e verificar a correção de rede, Contexto, Critérios de aceitação (+5 more)

### Community 52 - "Configuration Reference (`.agent-sandbox.toml`)"
Cohesion: 0.15
Nodes (13): 1. Schema Reference, 2. Toolchain Provisioning & Shared Cache (`asb-toolcache`), 3. Agent Context Tools (`rtk`, `graphify`), 3. Worked Examples, Changes from v1 Schema, Configuration Reference (`.agent-sandbox.toml`), Example 1: `hexmed` (Host Services & Filtered Docker Inspection), Example 2: `BlackICE` (Nested Container Runtime) (+5 more)

### Community 53 - "Sandbox Domain Pack"
Cohesion: 0.18
Nodes (8): 1. System Topology, 2. CLI Commands, 3. Where Files Live, 4. What to Do on Failure, Container Roles, Documentation Index, Filesystem Layout, Sandbox Domain Pack

### Community 54 - "Integração project-scoped do Graphify no agent-sandbox"
Cohesion: 0.18
Nodes (10): 1. Objetivo e Contexto, 2.1 Baseline e Tooling Local, 2.2 Adaptador de Domínio (`.graphify/project.py`), 2.3 Governança de Agentes e SSoT, 2.4 Integração de Skills e Git, 2. Decisões Arquiteturais, 3. Arquitetura de Arquivos, 4. Estratégia de Testes e Validação (+2 more)

### Community 55 - "down"
Cohesion: 0.22
Nodes (10): down(), _origin_of(), pull(), purge(), Remove todo container do workspace pelo LABEL, nunca por prefixo solto: casar…, Remove containers e redes. NAO remove ~/asb-agent/<proj>/<ws>: ali vive o…, Le o caminho de origem gravado no estado. `down` precisa dele para achar o…, Traz o trabalho do workspace para o checkout primario, SEM merge. O operador… (+2 more)

### Community 56 - "exists"
Cohesion: 0.29
Nodes (7): ensure_toolcache_volume(), list_workspaces(), _require_workspace(), suspend(), exists(), running(), TestPodmanKindAndStatus

### Community 57 - "Global Constraints"
Cohesion: 0.22
Nodes (8): Global Constraints, Graphify Project Integration Implementation Plan, Plan Self-Review, Task 1: Setup script, ignore rules, and gitattributes, Task 2: Custom domain adapter and automated unit tests, Task 3: Install project-scoped skills and verify synchronization, Task 4: Agent governance, documentation, and commit conventions, Task 5: Generate initial knowledge graph and verify query acceptance

### Community 58 - "discover_mise_dirs"
Cohesion: 0.39
Nodes (3): discover_mise_dirs(), Encontra todos os diretorios que contem mise.toml, podando pastas irrelevantes., TestDiscoverMiseDirs

### Community 59 - "Security Boundaries & Isolation Model"
Cohesion: 0.25
Nodes (7): 1. Non-Negotiable Invariants, 3. Network & DNS Boundary, 4. Credential Isolation & The Antigravity Keyring, DNS Tunneling Prevention, Keyring Passphrase Protection, Security Boundaries & Isolation Model, Topology Enforcement (Fail-Closed)

### Community 60 - "Orca Reboot Persistence Implementation Plan"
Cohesion: 0.29
Nodes (6): Orca Reboot Persistence Implementation Plan, Task 1: readiness de rede e proxy, Task 2: criação transacional e imagem autenticada obrigatória, Task 3: estado completo do Antigravity, Task 4: autenticação verificável e diagnóstico, Task 5: integração Orca e documentação

### Community 61 - "Design: persistência profissional do sandbox no Orca"
Cohesion: 0.33
Nodes (5): Critérios de aceitação, Decisões, Design: persistência profissional do sandbox no Orca, Limites deliberados, Problema confirmado

### Community 62 - "2. Explicit Declarations: What Is NOT Protected"
Cohesion: 0.40
Nodes (5): 2. Explicit Declarations: What Is NOT Protected, Exfiltration to an allowed domain is possible, `host_api = "read"` grants passwordless Docker reading to uid 1000, `mode = "nested"` gives the agent a full container runtime inside the boundary, The command guard is NOT containment

## Knowledge Gaps
- **354 isolated node(s):** `start-keyring.sh script`, `common.sh script`, `shim.template.sh script`, `__dirname`, `ROOT` (+349 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **17 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `load_profile()` connect `load_profile` to `lifecycle.py`, `reload_allowlist`, `Profile`?**
  _High betweenness centrality (0.027) - this node is a cross-community bridge._
- **Why does `up()` connect `lifecycle.py` to `run`, `layout_for`, `load_profile`, `build_staging`, `Profile`, `install.py`, `names`, `down`, `exists`, `discover_mise_dirs`?**
  _High betweenness centrality (0.024) - this node is a cross-community bridge._
- **Why does `Profile` connect `Profile` to `lifecycle.py`, `load_profile`?**
  _High betweenness centrality (0.023) - this node is a cross-community bridge._
- **What connects `start-keyring.sh script`, `common.sh script`, `shim.template.sh script` to the rest of the system?**
  _354 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `run` be split into smaller, more focused modules?**
  _Cohesion score 0.14 - nodes in this community are weakly interconnected._
- **Should `layout_for` be split into smaller, more focused modules?**
  _Cohesion score 0.09872241579558652 - nodes in this community are weakly interconnected._
- **Should `assert.sh` be split into smaller, more focused modules?**
  _Cohesion score 0.08235294117647059 - nodes in this community are weakly interconnected._