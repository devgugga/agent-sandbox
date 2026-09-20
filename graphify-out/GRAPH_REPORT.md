# Graph Report - agent-sandbox-tui  (2026-09-20)

## Corpus Check
- 207 files · ~289,574 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 4499 nodes · 9448 edges · 257 communities (200 shown, 57 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 521 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `95690c43`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- checkouts/manager.py
- layout_for
- assert.sh
- load_profile
- build_staging
- test_startup_auth.py
- patch
- permitted
- What You Must Do When Invoked
- AGENTS.md
- What You Must Do When Invoked
- test_login_flow.py
- common.sh
- sync-skills.mjs
- TestInstallRuntime
- Graphify Knowledge Graph Architecture
- Design: agent-sandbox v2
- graphify reference: extra exports and benchmark
- Correções pós-verificação — agent-sandbox v2, BlackICE e hexmed-stack
- graphify reference: extra exports and benchmark
- agent-sandbox v2 — Implementation Plan
- AGENTS.md
- graphify reference: query, path, explain
- graphify reference: query, path, explain
- discover_mise_dirs
- Model Selection & Routing
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
- TestKeyringServiceLifecycle
- test-guard.sh
- test-recipe.sh
- .agents/skills/graphify/references/extraction-spec.md
- .codex/skills/graphify/references/extraction-spec.md
- TestCheckStatus
- shim.template.sh
- doctor.py
- Singleton Secret Service Implementation Plan
- File Structure
- Rootless Uplink Recovery Implementation Plan
- Configuration Reference (`.agent-sandbox.toml`)
- Sandbox Domain Pack
- Integração project-scoped do Graphify no agent-sandbox
- Git Commit Conventions
- Standard Verification Commands
- Global Constraints
- TestImageProviderInstall
- 2. Explicit Declarations: What Is NOT Protected
- Orca Reboot Persistence Implementation Plan
- Design: persistência profissional do sandbox no Orca
- run
- Skill: Agent Authoring
- Skill: Commit Curator
- Skill: Agent Authoring
- Skill: Commit Curator
- Skill: Agent Authoring
- Skill: Commit Curator
- login_harness
- patch
- _make_session
- Redesenho de inicialização e autenticação
- AgentSession
- tui.py
- .request
- Contratos de Autenticação por Fornecedor e Protocolo de Validação
- test_credential_writers.py
- collect_boot_evidence.py
- TestSupervisorPilot
- 3. Resultados dos Ensaios Empíricos
- TestForwarderIntegration
- lifecycle.py
- IsolationError
- Secret Service singleton para credenciais dos agentes
- integration/__init__.py
- SandboxFixture
- Design: Modular TUI for projects, worktrees, and agent sessions
- TestTeardownCommandClasses
- Path
- test_session_cli.py
- Target file responsibilities
- auth.py
- TestCliParserDispatchParity
- test_entrypoint_concurrency.py
- TestWorkspaceOperations
- _terminal
- CheckoutBinding
- 4.2 Entities
- TestToolDrift
- CheckoutManager
- FixtureHost
- Known Regressions — Sandbox Domain
- forwarder.sh
- ProbeResult
- Layout
- .registry
- .controller
- unit/test_network_gate.py
- test_sandbox_fixture_guard.py
- TuiController
- TestClassifyVerification
- TestCredentialDirectoryMounts
- test_provider_auth.py
- TestOperatorLock
- claim-verifier/agent.md
- regression-sentinel/agent.md
- test-shape-auditor/agent.md
- test_readiness.py
- _healthy_probe
- Global Constraints
- probe_ssh
- supervisor.py
- TestAggregateExitCodeDeniesByDefault
- 14. Incremental migration
- TestProbeSshIdentityAtCallSites
- Emenda A — runtime único systemd e espera única por rede
- LoginBusy
- Profile
- TestForwarderProcessLifecycle
- Piloto real de inicialização e autenticação — T2
- 6.2. Boot 1 — REPROVADO, e o teste estava contaminado
- TestLoginKeyringContract
- TestCodexRemoteScript
- TestVerifyCommand
- TestLoginCommandTable
- TestAgyRealModelListFormat
- TestVerifyClientInfrastructureGates
- ConnectionInfo
- TestVerifyClientCommands
- TestUnitSuiteIsolation
- TestLegacyCredentialLayoutWarning
- TestEntrypointCredentialLayout
- 10. Finishing, merging, and cleanup
- TestLiveAuthDoubleOptIn
- TestDoctor
- TestVerifyFreshClient
- test_auth_verify.py
- test_doctor.py
- Recuperação do uplink rootless do Podman
- 5. Estado de autenticação medido
- TestEmendaAChecks
- 5. Module architecture
- ProjectRegistryError
- git
- Supervisão da inicialização — Implementation Plan
- integration/test_network_gate.py
- TestKeyringRole
- TestVerifyClientAgy
- network_gate.py
- wait_until
- Workspace Lifecycle & Supervision
- Inicialização e autenticação — Implementation Plan
- TestCheckWorkspaceEgress
- TestEntrypointNeverDestroysSharedDirectories
- 7. Session continuity
- Agent Sandbox TUI Implementation Plan
- TestSingleRuntimeUp
- test_agent_drivers.py
- TestFinish
- Autenticação por fornecedor — Implementation Plan
- 6.4. Boot 2 — APROVADO sem comando corretivo
- 6.6. Boot 3 — configuração real: REPROVADO, e com falha silenciosa
- 6.3. Boot 2 preparado — teste discriminante com o drop-in desativado
- 6.8. Troca para o runtime único (Emenda A, Task 13)
- 8. Fases pendentes e janelas
- TestDownKeepsWorkspaceData
- .make
- 6.11. Boot A3 (um ativo, outro suspenso, runtime único): APROVADO
- 6.5. Orca: excluído e depois REINTEGRADO por decisão do operador
- 6.9. Boot A1 (normal, runtime único): APROVADO, com um defeito de partida
- Provider Authentication
- TestPurge
- 6.7. Validação pelo Orca BLOQUEADA por defeito do Orca
- .manager
- build_tree
- 13. Test strategy
- 8. TUI
- _project
- Path
- .write
- .finish
- CodexDriver
- .seed
- TestConversationsThePurgeDeletes
- test_session_manager.py
- LaunchCommand
- TestLazyDiscoveryWithTheRealCodexDriver
- .commit_on
- .services
- test_tui_controller.py
- AgentDriver
- .terminal
- SessionEvidence
- CheckoutId
- _info
- FinishCheckout
- .test_sessions_close_reattach_uncertain_and_completion
- BranchInfo
- TestSessionParser
- ClaudeDriver
- GitRepository
- _Case
- GitError
- 4. Revisão após o piloto (2026-09-19)
- GitResult
- ProjectDetectionTest
- test_supervisor_remove_units.py
- Worktree
- sanitize
- _info
- FakeScreen
- .run
- TestConnectDispatch
- TestStatusCommand
- TestParseClaudeStatus
- TestReconcile
- TestNetworkGateUnits
- Adendo — 2026-09-07, 22:00–22:50 BRT
- Piloto assistido de autenticação — 2026-09-07
- TestParseCodexStatus
- TestAssertNoOrphans
- TestSingleRuntimeResume
- CorruptionAndSchemaRejectionTests
- .offline
- git.py
- .fetch
- TestContainerUnitAndRender
- AgentAvailability
- Acceptance report: Agent Sandbox TUI
- TestInstallGuards
- TestProjectAdd
- session_volume_mountpoint
- asb-seed-claude-state
- TestPodmanKindAndStatus
- TestKeyringUnit
- FakeTerminal
- TestEnumMembership
- TestPurgeAfterDown
- .__init__
- start-keyring.sh
- TestDoctorServiceBlockNeverSwallows
- _AliveRun
- runtime/__init__.py

## God Nodes (most connected - your core abstractions)
1. `SandboxFixture` - 107 edges
2. `CheckoutId` - 73 edges
3. `CodexDriver` - 66 edges
4. `GitRepository` - 66 edges
5. `git()` - 63 edges
6. `CheckoutManager` - 58 edges
7. `AgentSession` - 55 edges
8. `TuiController` - 53 edges
9. `FakeDriver` - 53 edges
10. `PodmanError` - 46 edges

## Surprising Connections (you probably didn't know these)
- `TestCodexTrustOverride` --uses--> `AntigravityDriver`  [INFERRED]
  tests/unit/test_agent_drivers.py → cli/asb/agents/antigravity.py
- `TestProbedFully` --uses--> `AntigravityDriver`  [INFERRED]
  tests/unit/test_agent_drivers.py → cli/asb/agents/antigravity.py
- `TestProbeUnknownVersionOutput` --uses--> `AntigravityDriver`  [INFERRED]
  tests/unit/test_agent_drivers.py → cli/asb/agents/antigravity.py
- `TestSessionServices` --uses--> `AntigravityDriver`  [INFERRED]
  tests/unit/test_session_cli.py → cli/asb/agents/antigravity.py
- `TestCodexTrustOverride` --uses--> `ResumeUnsupported`  [INFERRED]
  tests/unit/test_agent_drivers.py → cli/asb/agents/base.py

## Import Cycles
- None detected.

## Communities (257 total, 57 thin omitted)

### Community 0 - "checkouts/manager.py"
Cohesion: 0.05
Nodes (33): cli/asb/checkouts/manager.py — listar, inspecionar e criar checkouts.…, CheckoutKind, cli/asb/checkouts/model.py — identidade e registro imutavel de checkout. Um…, cli/asb/interfaces/ — pontos de entrada de controlador para um workspace vivo…, cli/asb/projects/model.py — identidade e registro imutavel de projeto. Um…, cli/asb/projects/registry.py — registro atomico de projetos e checkouts.…, cli/asb/runtime/sandbox.py — fronteira de controlador para o runtime.…, tests/integration/sandbox_fixture.py — isolated test fixture for systemd… (+25 more)

### Community 1 - "layout_for"
Cohesion: 0.08
Nodes (30): _git(), layout_for(), prepare_clone(), Exception, Path, cli/asb/workspace.py — identidade do workspace, layout em disco e clone. Duas…, Chamado por `down`. NAO toca no mount: la vive o trabalho do agente., Chamado por `purge`, so apos confirmacao explicita do operador. Depois de… (+22 more)

### Community 2 - "assert.sh"
Cohesion: 0.06
Nodes (40): assert_contains(), assert_eq(), assert_fails(), assert_not_contains(), report(), require(), assert.sh script, wait_for() (+32 more)

### Community 3 - "load_profile"
Cohesion: 0.10
Nodes (24): _choice(), load_profile(), _ports(), ProfileError, _publish_ports(), Exception, Path, cli/asb/profile.py — le .agent-sandbox.toml e devolve um perfil validado. O… (+16 more)

### Community 4 - "build_staging"
Cohesion: 0.07
Nodes (38): _allowed_destination_roots(), _allowed_symlink_roots(), build_staging(), copy_file(), denied(), filter_claude_settings(), filter_codex_config(), _key() (+30 more)

### Community 5 - "test_startup_auth.py"
Cohesion: 0.11
Nodes (13): guard_podman(), Pilot, pilot_cli(), CompletedProcess, Path, Real Podman/systemd/SSH pilot with isolated, synthetic network edges. Home…, Process-local seams; host HOME and Podman storage stay unchanged., Connect I1 resource ownership to lifecycle names and on-disk state. (+5 more)

### Community 7 - "permitted"
Cohesion: 0.10
Nodes (12): Handler, main(), permitted(), relay(), Server, socket, Testa cli/asb/install.py broker()., Testa a função permitted(method, target) do broker. (+4 more)

### Community 8 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 9 - "AGENTS.md"
Cohesion: 0.06
Nodes (24): Role, Available Subagents (`.claude/agents/`), Claude Code Configuration, Knowledge Graph (`graphify-out/`), Skills (`.claude/skills/`), Documents, Git Domain Pack, Available Domain Packs (+16 more)

### Community 10 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native AGENTS.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 11 - "test_login_flow.py"
Cohesion: 0.12
Nodes (10): prepare_workspace_harness(), Testes do fluxo de login seletivo, persistencia e fixacao de versoes (A3).…, Roda `lifecycle.prepare_workspace` DE VERDADE e devolve o `podman run` do…, I6: a credencial e compartilhada; a transcricao nao. Medido no podman 6.1 antes…, `volume-subpath` NAO cria o caminho de origem (A1): um subpath ausente aborta o…, Cancelar no codex nao pode engolir o resultado ja obtido do claude: o operador…, `claude -p ping` e `agy -p ping` mandavam PROMPT ao modelo para checar sessao,…, TestCancellationDuringAll (+2 more)

### Community 12 - "common.sh"
Cohesion: 0.27
Nodes (7): asb_recipe_json(), asb_workspace_id(), common.sh script, create.sh script, destroy.sh script, resume.sh script, suspend.sh script

### Community 13 - "sync-skills.mjs"
Cohesion: 0.17
Nodes (8): BANNER_LINES, CHECK, __dirname, MIRRORS, PRUNE, ROOT, skills, VENDOR

### Community 14 - "TestInstallRuntime"
Cohesion: 0.06
Nodes (15): I2: Header must be at the very start of the file, not matched as substring., I2: remove_project_dropin must verify mode before unlink., I4: a entrada trocada depois da ultima validacao nao e removida. O gancho troca…, Drop-in do projeto pronto para remocao, mais o gancho de reapontamento. Devolve…, Segunda janela TOCTOU, lado observavel: o inode e reconferido antes do unlink.…, Segunda janela TOCTOU, lado irredutivel: a troca cai DENTRO da syscall. Entre…, I3: Manifest must cover all files in asb/ package with sha256 and mode., I4: Non-regular file (e.g. directory) as drop-in must return (False, False) and… (+7 more)

### Community 15 - "Graphify Knowledge Graph Architecture"
Cohesion: 0.15
Nodes (11): 1. Architectural Role & Principles, 2. Baseline & Prerequisites, 3. Setup & Verification, 4. Domain-Specific Ingestion (`.graphify/project.py`), 5. Security Guardrails & Exclusions, 6. Query Cheatsheet, 7. Semantic Update Protocol & Two-Commit Workflow, 8. Linked Worktrees & Headless Environments (+3 more)

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
Cohesion: 0.09
Nodes (21): 1. Agent Architecture: "Domain Packs", 1. Fast Path Querying, 1. Specification Before Implementation (Spec-Driven), 1. Think Before Coding, 2. Available Subagents, 2. Context Hygiene & Progressive Disclosure, 2. Semantic Update Timing, 2. Simplicity First (+13 more)

### Community 22 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 23 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 24 - "discover_mise_dirs"
Cohesion: 0.39
Nodes (3): discover_mise_dirs(), Encontra todos os diretorios que contem mise.toml, podando pastas irrelevantes., TestDiscoverMiseDirs

### Community 25 - "Model Selection & Routing"
Cohesion: 0.09
Nodes (17): 1. Architecture Boundaries, 2. Single Source of Truth (SSoT), 3. Scope and Authorization, Agent Authoring Conventions, Core Principle, Cross-Platform Tier Equivalence, Escalation Governance, Model Selection & Routing (+9 more)

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
Cohesion: 0.09
Nodes (22): 10. Orca Recipe Selector Invisibility, 11. Squid Configuration File Permissions, 12. Missing `--userns=keep-id` on Agent Container, 13. Sibling Worktree Path Collision at Filesystem Root, 14. Claude Code Hanging on Non-Interactive Stdin, 15. Node Header Fetch Failure during Native Module Build, 16. Service Containers Failing under `keep-id` without `--user 0`, 17. Toolchain Installation Failure during Workspace Startup (`up`) (+14 more)

### Community 39 - "TestKeyringServiceLifecycle"
Cohesion: 0.09
Nodes (6): Path, Espelha a estrutura real de Mounts retornada por podman inspect., TestAuthLifecycle, TestCheckKeyringService, TestKeyringServiceLifecycle, valid_keyring_mounts()

### Community 41 - "test-recipe.sh"
Cohesion: 0.40
Nodes (3): RECIPE_STAGE, test-recipe.sh script, XDG_CONFIG_HOME

### Community 48 - "doctor.py"
Cohesion: 0.07
Nodes (44): ArgumentParser, build_parser(), main(), check_legacy_agent_container(), check_network_gate(), check_project_dropin_absent(), check_workspace_egress(), diagnose() (+36 more)

### Community 49 - "Singleton Secret Service Implementation Plan"
Cohesion: 0.22
Nodes (8): Global Constraints, Singleton Secret Service Implementation Plan, Task 1: Criar um teste de regressão isolado para o Secret Service, Task 2: Transformar `start-keyring.sh` em serviço singleton, Task 3: Adicionar o ciclo de vida do serviço global, Task 4: Tornar o entrypoint exclusivamente cliente do Secret Service, Task 5: Validar login real no mesmo serviço e diagnosticar falhas, Task 6: Atualizar o SSoT e executar a verificação completa

### Community 50 - "File Structure"
Cohesion: 0.12
Nodes (16): agent-sandbox Implementation Plan, File Structure, Global Constraints, Self-Review, Task 0: Helper de asserção, Task 10: Domain pack e extensão aos demais projetos, Task 11: Tornar o sandbox o único caminho, Task 1: Imagem base com host keys estáveis (+8 more)

### Community 51 - "Rootless Uplink Recovery Implementation Plan"
Cohesion: 0.29
Nodes (6): Global Constraints, Rootless Uplink Recovery Implementation Plan, Task 1: Encapsular a inicialização do namespace rootless, Task 2: Aplicar o helper em `up` e `resume`, Task 3: Preparar o uplink antes da restauração no login, Task 4: Documentar e verificar a correção de rede

### Community 52 - "Configuration Reference (`.agent-sandbox.toml`)"
Cohesion: 0.14
Nodes (14): 1. Schema Reference, 2. Toolchain Provisioning & Shared Cache (`asb-toolcache`), 3. Agent Context Tools (`rtk`, `graphify`), 3. Worked Examples, Changes from v1 Schema, Configuration Reference (`.agent-sandbox.toml`), Example 1: `hexmed` (Host Services & Filtered Docker Inspection), Example 2: `BlackICE` (Nested Container Runtime) (+6 more)

### Community 53 - "Sandbox Domain Pack"
Cohesion: 0.25
Nodes (8): 1. System Topology, 2. CLI Commands, 3. Where Files Live, 4. What to Do on Failure, Container Roles, Documentation Index, Filesystem Layout, Sandbox Domain Pack

### Community 54 - "Integração project-scoped do Graphify no agent-sandbox"
Cohesion: 0.18
Nodes (10): 1. Objetivo e Contexto, 2.1 Baseline e Tooling Local, 2.2 Adaptador de Domínio (`.graphify/project.py`), 2.3 Governança de Agentes e SSoT, 2.4 Integração de Skills e Git, 2. Decisões Arquiteturais, 3. Arquitetura de Arquivos, 4. Estratégia de Testes e Validação (+2 more)

### Community 55 - "Git Commit Conventions"
Cohesion: 0.25
Nodes (8): 1. Authority and Branching Rules, 2. Safe Scope Selection (Surgical Changes), 3. Prerequisites & Empirical Verification, 4. Commit Message Format, 5. Attribution, Commit Body (Mandatory), Git Commit Conventions, Gitmoji Selection

### Community 56 - "Standard Verification Commands"
Cohesion: 0.13
Nodes (15): Human checkpoint after Task 5, Standard Verification Commands, Task 10: Read-only curses tree and action controller, Task 11: Worktree discovery and safe creation, Task 12: Merge evidence, finish, and idempotent cleanup, Task 13: End-to-end acceptance and documentation, Task 1: Domain types and immutable identities, Task 2: Atomic project registry (+7 more)

### Community 57 - "Global Constraints"
Cohesion: 0.22
Nodes (8): Global Constraints, Graphify Project Integration Implementation Plan, Plan Self-Review, Task 1: Setup script, ignore rules, and gitattributes, Task 2: Custom domain adapter and automated unit tests, Task 3: Install project-scoped skills and verify synchronization, Task 4: Agent governance, documentation, and commit conventions, Task 5: Generate initial knowledge graph and verify query acceptance

### Community 58 - "TestImageProviderInstall"
Cohesion: 0.20
Nodes (4): Fornecedores via mise `latest`, num diretorio de root (decisao humana de…, ~/.local/share/mise vira symlink para o toolcache compartilhado e gravavel pelo…, LABEL nao carrega valor calculado num RUN; um label com versao declarada…, TestImageProviderInstall

### Community 59 - "2. Explicit Declarations: What Is NOT Protected"
Cohesion: 0.17
Nodes (12): 1. Non-Negotiable Invariants, 2. Explicit Declarations: What Is NOT Protected, 3. Network & DNS Boundary, 4. Credential Isolation & The Singleton Secret Service, DNS Tunneling Prevention, Exfiltration to an allowed domain is possible, `host_api = "read"` grants passwordless Docker reading to uid 1000, `mode = "nested"` gives the agent a full container runtime inside the boundary (+4 more)

### Community 60 - "Orca Reboot Persistence Implementation Plan"
Cohesion: 0.29
Nodes (6): Orca Reboot Persistence Implementation Plan, Task 1: readiness de rede e proxy, Task 2: criação transacional e imagem autenticada obrigatória, Task 3: estado completo do Antigravity, Task 4: autenticação verificável e diagnóstico, Task 5: integração Orca e documentação

### Community 61 - "Design: persistência profissional do sandbox no Orca"
Cohesion: 0.33
Nodes (5): Critérios de aceitação, Decisões, Design: persistência profissional do sandbox no Orca, Limites deliberados, Problema confirmado

### Community 62 - "run"
Cohesion: 0.11
Nodes (22): check_keyring_service(), ensure_keyring_data_volume(), ensure_keyring_pass(), ensure_keyring_runtime_volume(), ensure_keyring_service(), _inspect_keyring_container(), _keyring_mount_contract_issue(), Path (+14 more)

### Community 69 - "login_harness"
Cohesion: 0.08
Nodes (17): login_harness(), I5: erro de infraestrutura de UM fornecedor nao apaga o resultado ja…, A evidencia continua sendo texto enlatado: o erro do podman nao e saida…, Caso do brief: o login interativo termina bem, mas o cliente NOVO diz deslogado…, A4 ainda nao esta integrado: sem `verify_client`, o resultado do agy e…, Um fornecedor que falha nao apaga o resultado dos outros, e o codigo agregado…, Cancelar preserva dados: nada de volume, nada de credencial removida — apenas o…, `asb-login` era um nome fixo: duas execucoes concorrentes se matavam. Nenhuma… (+9 more)

### Community 70 - "patch"
Cohesion: 0.18
Nodes (9): probe_host(), probe_proxy(), Checa CONNECT através do proxy até o destino declarado., Checa rota, TCP e TLS do host até o destino de controle declarado., Proves readiness probes distinguish proxy inaccessible from CONNECT denied and…, patch, M1: o casamento de status virou substring nua ("403" in output), e a saida…, TestProbeHost (+1 more)

### Community 71 - "_make_session"
Cohesion: 0.05
Nodes (33): datetime, Exception, Path, _T, Executa `mutate` sob lock exclusivo, recarregando antes de gravar. `mutate`…, Retorna `raw[key]`, ou levanta `SessionStoreError` nomeando o campo quando ele…, Opcional: registros gravados antes do campo nao tem a chave e decodificam como…, Falha ao ler/gravar o registro de sessoes, ou um registro invalido. (+25 more)

### Community 72 - "Redesenho de inicialização e autenticação"
Cohesion: 0.14
Nodes (14): 1. Objetivo e limites, 2. Evidência e incertezas, 3. Alternativas e decisão proposta, 4. Contratos globais, 5.1 Sondas e limites, 5.2 Forwarder e criação transacional, 5. Inicialização: responsabilidades e estado, 6.1 Persistência e concorrência: gate obrigatório (+6 more)

### Community 73 - "AgentSession"
Cohesion: 0.05
Nodes (43): _argv_only(), AttachResult, datetime, RunFn, RuntimeError, cli/asb/sessions/manager.py — maquina de estados de recuperacao de sessoes. Um…, `TmuxTerminal.start` recebe so argv; um `env` seria descartado em silencio,…, Fluxo "abrir sessao": reanexa se vivo, retoma nativamente se morto e retomavel,… (+35 more)

### Community 74 - "tui.py"
Cohesion: 0.05
Nodes (55): cli/asb/agents/antigravity.py — driver do Antigravity CLI (`agy`). O binario de…, cli/asb/agents/base.py — driver base de provedor de agente de IA. Um…, _canonical_uuid(), cli/asb/agents/claude.py — driver do Claude Code CLI. O id da sessao e…, `value` so passa se ja e um UUID na forma canonica (minusculas, com hifens),…, default_drivers(), _existing(), _manager() (+47 more)

### Community 75 - ".request"
Cohesion: 0.10
Nodes (8): _Case, Path, TestCreate, TestInspect, TestList, TestRefusals, TestRollbackEdges, TestTransaction

### Community 76 - "Contratos de Autenticação por Fornecedor e Protocolo de Validação"
Cohesion: 0.08
Nodes (26): 1. Sumário Executivo, 2. Matriz de Contratos por Fornecedor, 3.1 Claude Code: Análise Forense do Binário e a Divergência do Libsecret, 3.2 OpenAI Codex: Análise de Armazenamento e Configuração Efetiva, 3.3 Google Antigravity: Análise de D-Bus, Secret Service e Sessão SSH, 3. Análise Detalhada dos Binários e Divergências Históricas, 4.1 Falha de Symlink sob `replace()` Atômico, 4.2 Rejeição de Symlinks por `O_NOFOLLOW` (+18 more)

### Community 77 - "test_credential_writers.py"
Cohesion: 0.10
Nodes (16): get_test_image(), tests/integration/test_credential_writers.py — Empirical tests for credential…, Container-level validation using SandboxFixture under uid 1000., Proves uid 1000 can create, chmod 0600, write, and read credential files., Exercises absent destination, empty 0-byte file, malformed JSON, and broken…, Simulates the entrypoint.sh symlink layout inside the container as uid 1000.…, Proves Claude Code CLI (2.1.263) status handling under 0-byte, corrupt, broken,…, Returns local agent-sandbox image if available, else alpine fallback. (+8 more)

### Community 78 - "collect_boot_evidence.py"
Cohesion: 0.07
Nodes (29): _auth(), _boot_id(), collect(), _containers(), main(), _manifest(), _network(), _port() (+21 more)

### Community 79 - "TestSupervisorPilot"
Cohesion: 0.12
Nodes (9): tests/integration/test_supervisor_pilot.py — Empirical supervision pilot test.…, Proves runtime launcher helper seamlessly attaches to an already running…, Proves literal unit behavior: podman start --attach on running container…, Proves SandboxFixture refuses foreign resources, production names, and external…, Empirical integration test suite for systemd rootless supervision., Proves systemd Type=exec restarts container on failure, preserving identity and…, Proves systemd Restart=always restarts container even when exiting cleanly…, Proves ExecStopPost stops container when ExecStartPost fails during startup. (+1 more)

### Community 80 - "3. Resultados dos Ensaios Empíricos"
Cohesion: 0.15
Nodes (12): 1. Objetivo e Escopo, 2. Artefatos Desenvolvidos, 3.1. Recuperação após Falha e Preservação de Identidade, 3.2. Saída Limpa Inesperada (Código 0), 3.3. Falha em `ExecStartPost` e Limpeza por `ExecStopPost`, 3.4. Reconexão a Container em Execução, 3.5. Proteção de Isolamento, 3. Resultados dos Ensaios Empíricos (+4 more)

### Community 81 - "TestForwarderIntegration"
Cohesion: 0.12
Nodes (9): tests/integration/test_forwarder.py — Integration tests for port forwarder…, Proves initial bind errors or invalid port arguments fail immediately., Empirical integration tests for asb-forwarder and unprivileged low ports., Proves undeclared ports remain closed and forwarder is not a general proxy., Proves killing one listener causes forwarder failure, supervisor restart, and…, Proves the proxy image explicitly contains bash and the forwarder executable., Proves the old un-supervised script masks child process failure., Proves forwarder handles SIGTERM cleanly and exits status 0. (+1 more)

### Community 82 - "lifecycle.py"
Cohesion: 0.07
Nodes (56): build(), build_proxy(), credential_mount_args(), _current_revision(), down(), ensure_credential_dirs(), ensure_runtime(), ensure_session_volume() (+48 more)

### Community 83 - "IsolationError"
Cohesion: 0.13
Nodes (10): IsolationError, BaseException, Exception, Encerra a sessao se o container ainda roda; ausente nao e erro. O servidor tmux…, Raised when an operation attempts to access or mutate resources outside…, (is-enabled, is-active) da unit no manager, independente de arquivo local., Para e desabilita (persistente e runtime) consultando o estado antes de cada…, Nenhum processo supervisionado ficou para tras. Padrao: o container… (+2 more)

### Community 84 - "Secret Service singleton para credenciais dos agentes"
Cohesion: 0.22
Nodes (9): Ciclo de vida, Compatibilidade e migração, Contexto, Critérios de aceitação, Decisão de arquitetura, Fora de escopo, Objetivo, Secret Service singleton para credenciais dos agentes (+1 more)

### Community 86 - "SandboxFixture"
Cohesion: 0.05
Nodes (26): Registra uma sessao tmux que roda DENTRO de `container` (um container desta…, Sets up dedicated isolated paths, keys, launcher, and volumes., Creates the synthetic persistent container., Renders the systemd unit content for the pilot., Isolated sandbox fixture context manager for integration tests., Installs and reloads the unit in user systemd., Stops the supervised systemd unit., Simulates container failure by sending SIGKILL. (+18 more)

### Community 87 - "Design: Modular TUI for projects, worktrees, and agent sessions"
Cohesion: 0.15
Nodes (13): 11.1 General rule, 11.2 Main cases, 11. Failure handling, 12. Security, 15. Acceptance criteria, 16. Expected outcome, 1. Context, 2. Goals (+5 more)

### Community 88 - "TestTeardownCommandClasses"
Cohesion: 0.10
Nodes (7): _FixtureCase, tests/unit/test_isolation_guard.py — guardas de isolamento, CLI publico e…, `down` remove o arquivo, mas o manager guarda o service 'failed' (is-active…, Exaustao do laco de `_quiesce_unit`: rc=0 em todo `stop`, estado imovel. O laco…, `sentinel_exists` so traduz rc 0/1; qualquer outro e falha de consulta.…, TestPathSeams, TestTeardownCommandClasses

### Community 89 - "Path"
Cohesion: 0.14
Nodes (7): CompletedProcess, Path, Runs a command inside a container via podman exec. `container` defaults to the…, Sobe (ou reaproveita) um cliente PROPRIO da fixture, montando SOMENTE as…, Executes the ASB CLI within the isolated environment., O ambiente isolado que `cli()` passa ao CLI real; um teste que chama o pacote…, Onde units registradas podem morar: runtime do manager e config do usuario.

### Community 90 - "test_session_cli.py"
Cohesion: 0.06
Nodes (39): cli/asb/runtime/connection.py — conexao SSH tipada de um workspace vivo.…, str, Identificador do terminal (tmux) ligado a uma sessao., TerminalId, _encode_utc(), cli/asb/sessions/store.py — registro atomico de sessoes de agente. Persiste,…, `session.<field>` em UTC truncado ao segundo; um datetime naive e recusado., _to_stored_utc() (+31 more)

### Community 91 - "Target file responsibilities"
Cohesion: 0.20
Nodes (10): Agent Sandbox Module Decomposition Implementation Plan, Completion evidence, Global Constraints, Target file responsibilities, Task 1: Freeze observable contracts before extraction, Task 2: Move provider-specific auth rules into agent drivers, Task 3: Extract runtime storage ownership from lifecycle, Task 4: Extract transaction and sandbox orchestration (+2 more)

### Community 92 - "auth.py"
Cohesion: 0.08
Nodes (49): _aggregate_exit_code(), _agy_model_row(), _agy_models_output_valid(), AuthResult, call_budget(), check_status(), classify_verification(), _client_name() (+41 more)

### Community 93 - "TestCliParserDispatchParity"
Cohesion: 0.06
Nodes (23): _dispatched_commands(), _load_cli_module(), _nested_subcommands(), ArgumentParser, Unit tests for cli/asb-agent — paridade entre parser e despacho. B#1: a Tarefa…, Tarefa 4: `connect` e um subcomando de topo como qualquer outro (registrado no…, Tarefa 9: a mesma paridade, nos dois sentidos, para cada subcomando aninhado…, Tarefa 10: `tui` e um comando de topo sem subcomandos nem argumentos; as acoes… (+15 more)

### Community 94 - "test_entrypoint_concurrency.py"
Cohesion: 0.25
Nodes (4): Starts the supervised systemd unit., skipUnless, tests/integration/test_entrypoint_concurrency.py — agentes que partem juntos.…, TestEntrypointConcurrentStart

### Community 95 - "TestWorkspaceOperations"
Cohesion: 0.17
Nodes (3): I1: `remove_workspace_units` removia unidades por glob `asb-{ws}-*.service`,…, Sem manifesto legivel, nao ha como saber quais nomes de servico pertencem a…, TestWorkspaceOperations

### Community 96 - "_terminal"
Cohesion: 0.09
Nodes (12): attach_remote(), _done(), Testes de `asb.sessions.terminal` (Tarefa 7): backend tmux via SSH. Cobre o…, _RunContract, _terminal(), TestAttachArgv, TestCaptureExitStatus, TestInvalidTerminalId (+4 more)

### Community 97 - "CheckoutBinding"
Cohesion: 0.09
Nodes (31): AssertionError, CheckoutBinding, Vinculo entre um checkout do operador e um projeto do registro., BaseException, Exception, Path, Fronteira injetavel: `root` localiza `cli/asb-agent`, `registry` guarda o…, Status explicito do workspace de CADA binding do projeto, na ordem do registro;… (+23 more)

### Community 98 - "4.2 Entities"
Cohesion: 0.25
Nodes (8): 4.1 Relationships, 4.2 Entities, 4.3 Distinct identifiers, 4. Domain model, `AgentSession`, `Checkout`, `Project`, `SandboxRuntime`

### Community 100 - "CheckoutManager"
Cohesion: 0.08
Nodes (27): checkout_kind(), CheckoutError, CheckoutManager, CreatePreview, Exception, Path, `PRIMARY` quando `path` e o checkout primario, comparando caminhos RESOLVIDOS:…, O checkout como o Git o ve agora. Levanta se o caminho sumiu, se o Git nao o… (+19 more)

### Community 102 - "Known Regressions — Sandbox Domain"
Cohesion: 0.14
Nodes (14): Known Regressions — Sandbox Domain, R10 — Initializing the rootless network namespace before real connectivity, R11 — Driving a systemd-supervised container with Podman directly, R12 — PID-derived names for temporary paths on a shared volume, R13 — A test that pins the defect's own output, R1 — Prefix matching without a delimiter, R2 — Credential storage behind a symlink or a single-file bind mount, R3 — Treating a provider CLI's exit 0 as proof the action happened (+6 more)

### Community 104 - "ProbeResult"
Cohesion: 0.18
Nodes (7): ProbeResult, A#2: `resume` so publica conexao depois do gate de prontidao; falha de…, Executa o callback UMA vez: exercita o `check_ws` real sem gastar os 30s de…, TestResumeReadinessGate, TestProbeResult, TestProbeWorkspace, TestRuntimeCheck

### Community 105 - "Layout"
Cohesion: 0.05
Nodes (28): emit(), Recarrega a allowlist do proxy sem tocar no container do agente. Preserva a…, A linha que o recipe do Orca consome. A porta e LIDA do podman, nunca…, reload_allowlist(), Layout, C1 regression: `manifest_containers["forwarder"]` referenciava `fwd_name`, uma…, I4: `up` resolvia a porta SSH duas vezes (uma para o gate de prontidao, outra…, I5: `WorkspaceTransaction.rollback` engolia qualquer excecao ao remover… (+20 more)

### Community 106 - ".registry"
Cohesion: 0.08
Nodes (15): CheckoutBindingTests, ConcurrencyAndIsolationTests, DiscoveryAndDeduplicationTests, _init_repo(), IntegrationBranchDiscoveryTests, _linked_worktree(), LookupAndIdempotencyTests, PersistenceShapeTests (+7 more)

### Community 107 - ".controller"
Cohesion: 0.09
Nodes (7): Piloto 1: o curses apagava o erro do tmux assim que o filho saia; com exit != 0…, Contexto §E: o `manager.attach` da Tarefa 8 retoma nativamente um…, TestActions, TestAttach, TestRefresh, TestRender, _type()

### Community 108 - "unit/test_network_gate.py"
Cohesion: 0.14
Nodes (8): _FakeClock, Unit tests for cli/asb/network_gate.py — espera unica por conectividade real…, Cada leitura avanca `step` segundos., _result(), TestGateNeverSpawnsProcesses, TestGateTarget, TestRuntimeShipsNetworkGate, TestWaitForNetwork

### Community 109 - "test_sandbox_fixture_guard.py"
Cohesion: 0.31
Nodes (6): _podman_names(), skipUnless, Integration test for tests/integration/sandbox_fixture.py — guarda do setup.…, O volume de sessao e criado por `lifecycle`, nao pela fixture. Por nao estar…, TestSandboxFixtureEnterGuard, TestSessionVolumeTeardown

### Community 110 - "TuiController"
Cohesion: 0.09
Nodes (18): CreateCheckout, `base_commit` e o commit que a previa mostrou e o operador confirmou; `create`…, _last_line(), Uma linha desenhavel. `key` e estavel entre refreshes (`p:`, `c:`, `s:` + id) e…, TreeRow, Prompt, BaseException, Pergunta de uma tecla na linha de status. Tecla fora de `choices` cancela. (+10 more)

### Community 111 - "TestClassifyVerification"
Cohesion: 0.07
Nodes (10): 403 puro tambem e a assinatura de uma negativa de ACL do proxy. So a evidencia…, Mesmo espirito do R4 (docs/domains/sandbox/known-regressions.md), mas em texto:…, R4 do catalogo de regressoes (docs/domains/sandbox/known- regressions.md):…, Guarda do proprio guarda: a delimitacao nao pode se tornar tao estrita a ponto…, A evidencia e sempre texto enlatado (categoria), nunca o `output` interpolado…, Guarda contra estado inventado: cada estado que classify_verification pode…, O teste verbatim do brief: rede ruim nunca vira logout., O texto capturado da CHAMADA (nao a pre-checagem) tambem pode denunciar timeout… (+2 more)

### Community 112 - "TestCredentialDirectoryMounts"
Cohesion: 0.12
Nodes (7): A1 provou: `rename` sobre symlink corta o vinculo com o volume, e sobre arquivo…, `ensure_credential_dirs` toca um caminho REAL (o mountpoint que o podman…, A causa confirmada: `: > "$stored"` deixava um arquivo de 0 bytes que nunca…, M10: um volume cujo `_data` nao aceita escrita — o estado que o piloto real…, O ponto de integracao inteiro do diff: os mounts tem de chegar a LINHA DE…, Guarda do proprio teste acima: uma harness que nao chegasse a emitir o `podman…, TestCredentialDirectoryMounts

### Community 113 - "test_provider_auth.py"
Cohesion: 0.13
Nodes (12): get_test_image(), _live_auth_enabled(), _live_auth_file_selected(), skipUnless, tests/integration/test_provider_auth.py — verificacao real e piloto (A4). Duas…, Guarda de isolamento: os volumes NOMEADOS nos mounts sao SOMENTE os desta…, Chamadas REAIS via `auth.verify_client()`. So rodam com `ASB_LIVE_AUTH=1` E…, Returns the local agent-sandbox image name if available, else ''. (+4 more)

### Community 118 - "test_readiness.py"
Cohesion: 0.10
Nodes (11): Unit tests for cli/asb/readiness.py and cli/asb/runtime_check.py., Emenda A: nenhuma orientacao pode mandar rodar `podman unshare --rootless-…, `host_ports` e uma pos-condicao prometida ao projeto: sem sonda, o `up`…, A remediacao vai para o stderr do operador e para o journal. Interpolar saida…, R11: orientacao que dirige container supervisionado por fora do systemd. O…, T3: o domain pack e o que agentes e operador leem antes de agir. Ele descreveu…, TestDomainPackDescribesTheSingleRuntime, TestHostPortsProbe (+3 more)

### Community 119 - "_healthy_probe"
Cohesion: 0.19
Nodes (5): _gate_then(), _healthy_probe(), _ok(), O orcamento e gasto na TENTATIVA, nao no sucesso: nao ha retry escondido so…, Resultados do gate SSH observacional e da unica chamada real.

### Community 120 - "Global Constraints"
Cohesion: 0.12
Nodes (17): Global Constraints, Runtime único systemd — Implementation Plan, Task 10: Teste de integração da espera com systemd real, Task 11: Testes em shell no runtime único, Task 12: Verificação completa antes da máquina real, Task 13: Troca na máquina real (janela do operador), Task 14: Boots reais (janelas do operador, spec §7.2), Task 15: Fechamento (+9 more)

### Community 121 - "probe_ssh"
Cohesion: 0.23
Nodes (8): probe_keyring(), probe_ssh(), Path, Executa 'true' via SSH com chave e porta informadas. `user` omitido resolve…, Checa saúde do Secret Service / keyring singleton., main(), cli/asb/runtime_check.py — entry point para sondas de prontidão do systemd.…, TestProbeSSH

### Community 122 - "supervisor.py"
Cohesion: 0.06
Nodes (61): broker(), check_project_dropin(), get_dropin_path(), guards(), install_runtime(), _is_project_dropin(), _link(), _manifest_of() (+53 more)

### Community 123 - "TestAggregateExitCodeDeniesByDefault"
Cohesion: 0.18
Nodes (6): C1: o agregado nega por padrao. A versao anterior testava os estados RUINS e…, A regressao propriamente dita: um estado que ninguem previu., O caminho exato do achado: quando a A4 alimentar `pending` no `auth status`, um…, Nao ter perguntado a ninguem nao e prova de nada., Duas copias da regra foi como `pending` ficou certo num caminho e valendo 0 no…, TestAggregateExitCodeDeniesByDefault

### Community 124 - "14. Incremental migration"
Cohesion: 0.29
Nodes (7): 14. Incremental migration, Stage 1 — Model and connection without runtime changes, Stage 2 — Agent drivers, Stage 3 — Persistent sessions, Stage 4 — Navigator TUI, Stage 5 — Worktrees and cleanup, Stage 6 — Reduce large modules

### Community 126 - "Emenda A — runtime único systemd e espera única por rede"
Cohesion: 0.14
Nodes (14): 10. Evidência, 1. Motivo, 2. Decisões do operador, 3. Arquitetura, 4. A espera por rede, 5. Keyring e troca, 6. O que sai e o que muda, 7.1. Testes automatizados (+6 more)

### Community 127 - "LoginBusy"
Cohesion: 0.50
Nodes (3): LoginBusy, Exception, Ja existe uma sessao de login deste fornecedor nesta maquina.

### Community 128 - "Profile"
Cohesion: 0.08
Nodes (25): Encaminha SO as portas declaradas para o host., start_forwarder(), Profile, normalize_domains(), Exception, Path, cli/asb/squid.py — junta a allowlist base com o perfil e emite squid.conf. A…, read_base() (+17 more)

### Community 129 - "TestForwarderProcessLifecycle"
Cohesion: 0.14
Nodes (6): Popen, tests/unit/test_forwarder_script.py — Unit tests for image/forwarder.sh…, Tests input validation of image/forwarder.sh., Tests process supervision semantics: fail-fast on child death and SIGTERM…, TestForwarderProcessLifecycle, TestForwarderScriptValidation

### Community 130 - "Piloto real de inicialização e autenticação — T2"
Cohesion: 0.15
Nodes (13): 1.1. A imagem foi reconstruída antes do piloto, 1. Ambiente e versões, 2. Inventário de coexistência (spec §7), 3. Workspace-piloto, 4. Coletor de evidência, 6.10. Boot A2 (rede atrasada, runtime único): APROVADO, 6.12. Retomada do suspenso (critério 2), 6.1. Fase (c) preparada — aguardando janela de reboot (+5 more)

### Community 131 - "6.2. Boot 1 — REPROVADO, e o teste estava contaminado"
Cohesion: 0.15
Nodes (13): 6.2. Boot 1 — REPROVADO, e o teste estava contaminado, A ferramenta tinha avisado, Causa-raiz: o drop-in do próprio projeto cria o namespace em todo boot, Diagnóstico, Duas medições descartadas por serem inválidas, Estado preparado depois do boot 1, Linha do tempo medida, O papel do workspace legacy (+5 more)

### Community 132 - "TestLoginKeyringContract"
Cohesion: 0.19
Nodes (6): _ok(), Contrato herdado de `TestLoginKeyringIntegration`, que vivia em `test_auth.py`…, O cliente fala com o Secret Service pelo socket. A passphrase e do singleton;…, `PodmanError` na verificacao nao escapa mais do laco (I5): vira resultado…, Herdado de `TestVerificacaoDeLogin`: `--version` responde 0 com o agente…, TestLoginKeyringContract

### Community 134 - "TestVerifyCommand"
Cohesion: 0.18
Nodes (4): `verify` nunca muta estado: nenhuma chamada a login()/operator_lock., O teste de log exigido pelo brief: fixtures com token, bearer e codigo OAuth…, `verify(ws, provider, json_output=...)`: mesmo schema de relatorio de…, TestVerifyCommand

### Community 135 - "TestLoginCommandTable"
Cohesion: 0.18
Nodes (5): O contrato exato dos comandos de login, verbatim do brief da A3., `claude /login` sai com 0 SEM logar (A1): um falso verde que manda o operador…, `--console` seleciona faturamento por API em vez da assinatura., `--version` responde 0 com o agente deslogado., TestLoginCommandTable

### Community 138 - "ConnectionInfo"
Cohesion: 0.07
Nodes (23): connect(), cli/asb/interfaces/cli.py — acesso SSH direto a um workspace vivo, sem depender…, Substitui o processo do host por um `ssh` conectado a `workspace`. So a parte…, ConnectionInfo, Path, Argumentos de `ssh` para esta conexao, como LISTA — nunca uma string de shell.…, Delega para `lifecycle_payload`: mesmas quatro chaves, mesma ordem, que…, Construtor de payload que NAO exige uma instancia completa de `ConnectionInfo`… (+15 more)

### Community 140 - "TestUnitSuiteIsolation"
Cohesion: 0.20
Nodes (4): Guarda do proprio guarda: um invólucro que recusasse tudo faria os testes acima…, A costura exata que contaminou o volume de producao, agora com o guarda no…, C2: o isolamento da suite e IMPOSTO, nao pedido em docstring. O que aconteceu…, TestUnitSuiteIsolation

### Community 141 - "TestLegacyCredentialLayoutWarning"
Cohesion: 0.29
Nodes (4): I3: o layout de raiz e detectado e ANUNCIADO. Nada e apagado., A politica de migracao nao e desta funcao, e apagar credencial nunca e…, Um `claude/auth.json` DENTRO do subdiretorio e o layout novo: nao pode ser…, TestLegacyCredentialLayoutWarning

### Community 142 - "TestEntrypointCredentialLayout"
Cohesion: 0.20
Nodes (4): A causa confirmada em A1 vive nestas linhas do entrypoint., Guarda do proprio teste: os assertos acima varrem so o codigo, e passariam num…, A copia acontece ao lado e so entra no lugar pronta. O contrato completo —…, TestEntrypointCredentialLayout

### Community 143 - "10. Finishing, merging, and cleanup"
Cohesion: 0.33
Nodes (6): 10.1 Principle, 10.2 `finish`, 10.3 Integration evidence, 10.4 External merge, 10.5 Policy, 10. Finishing, merging, and cleanup

### Community 146 - "TestVerifyFreshClient"
Cohesion: 0.25
Nodes (3): O `try` comeca ANTES do `podman run`: um Ctrl-C ou uma falha entre a criacao e…, `agy -p ping` bloqueia 60s quando deslogado (A1). Enquanto A4 nao entrega…, TestVerifyFreshClient

### Community 147 - "test_auth_verify.py"
Cohesion: 0.13
Nodes (12): Testes de cli/asb/auth.py — verificacao real e orcamento explicito (A4).…, Contexto local minimo; a chamada ao fornecedor continua sintetica., Uma chamada por fornecedor por `verify_client`, sem retry, e sempre observavel…, A protecao mais critica desta tarefa: se a chamada em si expirar (o caso mais…, Evidencia de sucesso exige resposta no formato solicitado, nao um grep de 'ok'.…, _SSHInfraCase, TestAgentsBehindProxyExitStatus, TestVerifyClientCallBudget (+4 more)

### Community 148 - "test_doctor.py"
Cohesion: 0.25
Nodes (5): _load_cli_module(), Testes de cli/asb/doctor.py e pull/purge em cli/asb/lifecycle.py., Roda `pull("test-ws")` (ou `main`) com o Git simulado: `head` e a saida de…, O branch vem do checkout que o agente escreve: um HEAD destacado, uma opcao…, TestPull

### Community 149 - "Recuperação do uplink rootless do Podman"
Cohesion: 0.29
Nodes (7): Contexto, Critérios de aceitação, Decisão de arquitetura, Fora de escopo, Invariantes, Objetivo, Recuperação do uplink rootless do Podman

### Community 150 - "5. Estado de autenticação medido"
Cohesion: 0.20
Nodes (10): 5.1. Antes do login humano (imagem já reconstruída), 5.2. Depois do login humano (2026-09-16T17:59Z), 5.3.1. Correção da guarda (autorizada pelo operador) e resultado real, 5.3.2. Cliente novo e dois workspaces simultâneos, 5.3. Antigravity: evidência direta contradiz o classificador, 5.4. ACHADO DE SEGURANÇA: credencial viva exposta na raiz do volume, 5.5. CORREÇÃO: `codex-auth.json` é a credencial VIVA do Codex, 5.6. Opção A executada — symlink eliminado (+2 more)

### Community 151 - "TestEmendaAChecks"
Cohesion: 0.17
Nodes (3): Emenda A: o doctor aponta o drop-in legado, a espera de rede e produtores…, Toda unidade de workspace tem Requires=asb-network.service: com a espera em…, TestEmendaAChecks

### Community 152 - "5. Module architecture"
Cohesion: 0.40
Nodes (5): 5.1 `CheckoutManager`, 5.2 `SessionManager`, 5.3 `AgentDriver`, 5.4 Interfaces, 5. Module architecture

### Community 153 - "ProjectRegistryError"
Cohesion: 0.11
Nodes (22): ProjectId, str, Identificador estavel de um projeto (prefixo "p-" + hex aleatorio)., _checkout_workspace(), _discover_integration_branch(), _git_common_dir(), _project_id_for(), ProjectRegistry (+14 more)

### Community 154 - "git"
Cohesion: 0.11
Nodes (3): TestCleanupAfterProof, git(), TestRemoteDefaultBranch

### Community 155 - "Supervisão da inicialização — Implementation Plan"
Cohesion: 0.22
Nodes (9): Global Constraints, I1 — Provar supervisão e criar fixture isolada, I2 — Diagnóstico tipado e prontidão observacional, I3 — Instalação versionada e uma única supervisão, I4 — Forwarder com falha visível e portas baixas, I5 — Integrar ciclo de vida, prontidão e rollback de criação, I6 — Adoção e rollback sem recriação dos workspaces, Saída desta frente (+1 more)

### Community 156 - "integration/test_network_gate.py"
Cohesion: 0.31
Nodes (6): _free_port(), _is_active(), skipUnless, Integracao real: a espera por rede segura unidades dependentes (Emenda A §7.1).…, TestNetworkGateHoldsDependents, _wait_for()

### Community 157 - "TestKeyringRole"
Cohesion: 0.36
Nodes (3): _once(), Unit tests for cli/asb/runtime_check.py — papel keyring (Emenda A §5)., TestKeyringRole

### Community 159 - "network_gate.py"
Cohesion: 0.32
Nodes (6): gate_target(), main(), cli/asb/network_gate.py — espera unica por conectividade real do host.…, Destino sondado; `ASB_NETWORK_GATE_TARGET` o substitui em ambiente isolado., Bloqueia ate o host alcancar `target`; devolve 0. O journal recebe so mudancas…, wait_for_network()

### Community 160 - "wait_until"
Cohesion: 0.39
Nodes (3): Executa probe repetidamente até que retorne state=='healthy' ou expire o…, wait_until(), TestWaitUntil

### Community 161 - "Workspace Lifecycle & Supervision"
Cohesion: 0.11
Nodes (18): 1. Ownership: systemd starts, Podman creates, 2. Commands and State Transitions, 3. Recovery by Category, 4. Direct SSH access without Orca, 5. Persistent agent sessions, 6. The TUI, 7. Finishing a worktree, Boot order (+10 more)

### Community 163 - "Inicialização e autenticação — Implementation Plan"
Cohesion: 0.25
Nodes (8): Estrutura de arquivos, Global Constraints, Inicialização e autenticação — Implementation Plan, Investimento e critério de interrupção, Ordem e pontos de decisão, T1 — Integrar as frentes e provar o fluxo Orca, T2 — Piloto real, reboot e retorno, T3 — Aceitar operação e atualizar documentação

### Community 165 - "TestEntrypointNeverDestroysSharedDirectories"
Cohesion: 0.29
Nodes (3): I6, segunda metade: com `~/.claude` compartilhado, todo `up` apagava e recriava…, O limite fica escrito: `mv` sobre diretorio nao e `renameat2(RENAME_EXCHANGE)`,…, TestEntrypointNeverDestroysSharedDirectories

### Community 166 - "7. Session continuity"
Cohesion: 0.40
Nodes (5): 7.1 Two continuity levels, 7.2 Recovery flow, 7.3 States, 7.4 Terminal, 7. Session continuity

### Community 167 - "Agent Sandbox TUI Implementation Plan"
Cohesion: 0.40
Nodes (3): Agent Sandbox TUI Implementation Plan, Global Constraints, Rollout and rollback

### Community 168 - "TestSingleRuntimeUp"
Cohesion: 0.31
Nodes (3): Emenda A: `up` tem runtime unico, remove o drop-in, verifica o host e nunca…, `host_ports` e pos-condicao prometida ao projeto: sem sonda, o `up` imprimia a…, TestSingleRuntimeUp

### Community 169 - "test_agent_drivers.py"
Cohesion: 0.09
Nodes (17): Exception, Levantada quando `resume()` e chamado sem a opcao de resume confirmada (por…, ResumeUnsupported, _FakeRun, Exception, Testes dos drivers de provedor de agente (Tarefa 5). Um `AgentDriver` apenas…, Rama nao nomeada explicitamente no brief, mas alcancavel: --version responde,…, Rama distinta de session_id_provable: aqui a opcao de resume esta literalmente… (+9 more)

### Community 170 - "TestFinish"
Cohesion: 0.10
Nodes (7): ListedCheckout, Um worktree que o Git lista (`worktree`) e o vinculo do registro (`binding`,…, FinishResult, `f`: alvo -> confirmacao com toggles explicitos -> so `y` roda. Os servicos de…, O `notice` some na proxima tecla; a razao fica na linha de status, saneada e…, TestFinish, TestNewWorktree

### Community 171 - "Autenticação por fornecedor — Implementation Plan"
Cohesion: 0.29
Nodes (7): A1 — Caracterizar o login real antes de escolher a correção, A2 — Separar status de conta, rede e infraestrutura, A3 — Login seletivo, persistência comprovada e versões, A4 — Verificação real e orçamento explícito, Autenticação por fornecedor — Implementation Plan, Global Constraints, Saída desta frente

### Community 172 - "6.4. Boot 2 — APROVADO sem comando corretivo"
Cohesion: 0.29
Nodes (7): 6.4. Boot 2 — APROVADO sem comando corretivo, A incerteza residual da §6.3 foi resolvida, Contraste com o boot 1 — hipótese principal, não comprovada, Linha do tempo medida, O que ainda falta neste boot, O que o boot 2 comprova, Verificação pelo caminho real, não só pelo estado do systemd

### Community 173 - "6.6. Boot 3 — configuração real: REPROVADO, e com falha silenciosa"
Cohesion: 0.29
Nodes (7): 6.6. Boot 3 — configuração real: REPROVADO, e com falha silenciosa, Linha do tempo medida, O que o boot 3 comprova, Pendente neste boot, Terceiro ponto a favor da hipótese do namespace preso, Workspace adotado: não se recuperou, Workspace do Orca (legacy): FALHA SILENCIOSA

### Community 174 - "6.3. Boot 2 preparado — teste discriminante com o drop-in desativado"
Cohesion: 0.33
Nodes (6): 6.3. Boot 2 preparado — teste discriminante com o drop-in desativado, Estado salvo, Exceção de janela, não remoção definitiva, O que o desenho adotado promete — e o que isto testa, RESTAURAÇÃO OBRIGATÓRIA ao fim da janela, Verificação de produtores — pela ferramenta

### Community 175 - "6.8. Troca para o runtime único (Emenda A, Task 13)"
Cohesion: 0.40
Nodes (5): 6.8. Troca para o runtime único (Emenda A, Task 13), Medições, Pendências abertas pela troca, Resíduo de teste removido antes da troca, Suítes em shell com o keyring de produção (Step 6)

### Community 176 - "8. Fases pendentes e janelas"
Cohesion: 0.33
Nodes (6): 8. Fases pendentes e janelas, Decisões pendentes do operador, Defeitos menores achados durante a troca e os boots, Fora do escopo desta emenda, registrado para T3, Recursos criados por este piloto, Revisão final da T3 (2026-09-17)

### Community 178 - ".make"
Cohesion: 0.17
Nodes (6): FakeDriver, Driver falso com a mesma superficie que o manager usa. A descoberta devolve,…, Um Codex real cria o rollout na primeira mensagem, depois da janela do start: a…, Irmaos do mesmo agente e cwd, sem id, vivos OU finais: a janela vai do inicio…, TestAttachMatrix, TestLazyDiscovery

### Community 179 - "6.11. Boot A3 (um ativo, outro suspenso, runtime único): APROVADO"
Cohesion: 0.50
Nodes (4): 6.11. Boot A3 (um ativo, outro suspenso, runtime único): APROVADO, Critérios do boot, Incidente: commit do relatório cortado pelo reboot, Linha do tempo

### Community 180 - "6.5. Orca: excluído e depois REINTEGRADO por decisão do operador"
Cohesion: 0.50
Nodes (4): 6.5. Orca: excluído e depois REINTEGRADO por decisão do operador, O caminho de criação do Orca reinstalou o drop-in, O forwarder, Workspace criado pelo Orca

### Community 181 - "6.9. Boot A1 (normal, runtime único): APROVADO, com um defeito de partida"
Cohesion: 0.50
Nodes (4): 6.9. Boot A1 (normal, runtime único): APROVADO, com um defeito de partida, Critérios do boot, Defeito: corrida no entrypoint entre agentes que partem juntos, Linha do tempo (journal, `short-precise`)

### Community 182 - "Provider Authentication"
Cohesion: 0.40
Nodes (5): 1. Three Separate Questions, 2. Where Credentials Live, 3. Logging In, Provider Authentication, States

### Community 184 - "6.7. Validação pelo Orca BLOQUEADA por defeito do Orca"
Cohesion: 0.67
Nodes (3): 6.7. Validação pelo Orca BLOQUEADA por defeito do Orca, Consequência para o plano, Por que o Orca cria workspaces `legacy`

### Community 185 - ".manager"
Cohesion: 0.13
Nodes (4): O operador integra por fora: `pull` + `merge` manuais., TestCleanupWithoutMerge, TestFinishPreview, TestUnreadableEvidence

### Community 186 - "build_tree"
Cohesion: 0.13
Nodes (22): _branch_label(), build_tree(), checkout_key(), _checkout_text(), CheckoutView, _fold(), project_key(), Path (+14 more)

### Community 187 - "13. Test strategy"
Cohesion: 0.50
Nodes (4): 13.1 Interfaces as test surfaces, 13.2 Required cases, 13.3 Verification by stage, 13. Test strategy

### Community 188 - "8. TUI"
Cohesion: 0.50
Nodes (4): 8.1 Technology, 8.2 Main tree, 8.3 First-version actions, 8. TUI

### Community 189 - "_project"
Cohesion: 0.14
Nodes (13): StrEnum, Estado de um workspace visto por `discover`, sem muta-lo., WorkspaceStatus, _checkout(), _keys(), _project(), Testes de `asb.interfaces.tui_model` (Tarefa 10): a arvore pura da TUI.…, A arvore mostra o estado que o refresh reconciliou, nao o que o store tinha… (+5 more)

### Community 190 - "Path"
Cohesion: 0.17
Nodes (5): Path, O volume de sessao e gravavel pelo agente: um symlink, um FIFO ou uma primeira…, Roda `fn` numa thread daemon com prazo de 5 s. Se ela ficar presa num FIFO,…, TestCodexSessionEvidence, TestHostileSessionVolume

### Community 191 - ".write"
Cohesion: 0.20
Nodes (10): Lifetime, Janela `[start, end]` de uma OUTRA sessao do mesmo agente e cwd sem id do…, _CodexCase, Descoberta do start: so arquivos criados depois do baseline., Descoberta preguicosa: todo arquivo atual, sem baseline., Sem baseline (a sessao comecou ha muito): todo arquivo atual e candidato,…, _subagent_meta(), TestCodexIgnoresSubagentThreads (+2 more)

### Community 193 - "CodexDriver"
Cohesion: 0.12
Nodes (7): CodexDriver, Argv exatos. Claude e Codex rodam sem prompts de permissao, como o Orca os…, O Codex guarda o trust do diretorio em `~/.codex/config.toml`, que no sandbox…, Sem `sessions_root`, nenhum driver le o diretorio de estado do HOST, mesmo…, TestCodexTrustOverride, TestLaunchAndResumeArgv, TestNoHostDefaultScanRoot

### Community 194 - ".seed"
Cohesion: 0.14
Nodes (6): RuntimeError, Falha ao iniciar ou encerrar um terminal tmux., TerminalError, Um refresh (ou resume) concorrente grava `concurrent` entre o `stop` do tmux e…, TestResume, TestStopAndSuspend

### Community 195 - "TestConversationsThePurgeDeletes"
Cohesion: 0.14
Nodes (6): `f` numa linha `missing` chega ao `cleanup()` real., I2: um worktree cujo sandbox nunca existiu (criado com `w`, nunca usado) ou foi…, M4: a confirmacao lista as sessoes cuja historia do provedor o purge apaga…, TestConversationsThePurgeDeletes, TestMissingRowFromTheTui, TestWorktreeWithoutSandbox

### Community 196 - "test_session_manager.py"
Cohesion: 0.09
Nodes (9): _FakeRemoteRun, FakeTerminal, ManagerCase, datetime, Path, Testes de `asb.sessions.manager` (Tarefa 8): a maquina de estados de…, Terminal falso: `probe` devolve os valores de `probes` em ordem (o ultimo se…, TestList (+1 more)

### Community 197 - "LaunchCommand"
Cohesion: 0.12
Nodes (19): LaunchCommand, Um comando pronto para execucao externa — nunca executado aqui., _aware_instant(), datetime, Path, cli/asb/agents/codex.py — driver do Codex CLI. Fonte do session-id comprovada…, `command` com o override de trust anexado ao FIM do argv; sem override, o…, `projects."<cwd>".trust_level="trusted"` para o `-c` do Codex, ou `None` quando… (+11 more)

### Community 198 - "TestLazyDiscoveryWithTheRealCodexDriver"
Cohesion: 0.20
Nodes (9): Pedido de uma nova sessao. `cwd` e o checkout de EXECUCAO do sandbox…, StartSession, Cenarios da revisao, com o `CodexDriver` e o `SessionStore` reais., A e B no mesmo checkout; A conversa depois do inicio de B, B nunca conversa; A…, `NOW` tem .123456 s; o store guarda segundos inteiros. Um rollout 0,1 s antes…, S7: A ja tem id; dentro de A o usuario roda `/new` e abre outro thread do…, S11: o escopo (irmaos, ids) e lido DEPOIS da varredura; um irmao inserido, com…, Uma primeira linha que estoura a recursao do parser JSON, ou um inteiro alem do… (+1 more)

### Community 200 - ".services"
Cohesion: 0.20
Nodes (6): _Case, _forbidden(), `manager.attach` retoma nativamente (Tarefa 8): e assim que o CLI honra o…, TestSessionAttach, TestSessionStart, TestSessionStopResume

### Community 201 - "test_tui_controller.py"
Cohesion: 0.13
Nodes (8): _Case, _forbidden(), _info(), Path, Testes de `asb.interfaces.tui` (Tarefa 10): o controlador da TUI e a camada…, TestNavigation, TestRunLoop, TestWorktreeListing

### Community 202 - "AgentDriver"
Cohesion: 0.15
Nodes (12): ABC, AgentDriver, _is_real_dir(), _is_regular_file(), datetime, Path, Driver de um provedor de agente. Subclasses fixam `kind`, `binary`,…, `cwd` nao entra no argv AQUI: `LaunchCommand` nao tem campo de cwd porque quem… (+4 more)

### Community 204 - "SessionEvidence"
Cohesion: 0.12
Nodes (10): AntigravityDriver, Path, Instantaneo de CAMINHOS de estado do provedor — nunca conteudo de transcript.…, SessionEvidence, _Harmless, Test driver: launches only its fixed harmless command. No provider id is ever…, A construcao do argv (`("agy", "--conversation", id)`) continua no codigo,…, Antigravity: mesmo com --conversation presente no --help do binario de HOST,… (+2 more)

### Community 205 - "CheckoutId"
Cohesion: 0.16
Nodes (8): CheckoutId, str, Identificador estavel de um checkout (prefixo "c-" + hex aleatorio)., datetime, Path, TestDomainRelationships, Tarefa 12: so a ausencia PROVADA de tudo que `purge` removeria pula a guarda e…, TestSandboxAbsent

### Community 206 - "_info"
Cohesion: 0.16
Nodes (5): _info(), `interactive=False`: sem TTY (`-T` no lugar de `-tt`), nunca pede senha…, TestLifecyclePayloadContract, TestSshArgvContract, TestSshArgvNonInteractive

### Community 207 - "FinishCheckout"
Cohesion: 0.15
Nodes (13): FinishCheckout, FinishState, StrEnum, Resultado de `finish`/`cleanup`. So `CLEANED` removeu recursos; um…, Pedido de integracao de um worktree em `target_branch`. Limpeza e remocao do…, _git(), _in_sandbox(), Path (+5 more)

### Community 208 - ".test_sessions_close_reattach_uncertain_and_completion"
Cohesion: 0.15
Nodes (16): ClaudeFake, CodexFake, completing_driver(), _git(), _init_repo(), _pane_pids(), Path, TestCase (+8 more)

### Community 209 - "BranchInfo"
Cohesion: 0.18
Nodes (10): BranchInfo, Path, Branch de `path` pelo `GitRepository` (§C): a TUI nao monta argv de Git. `None`…, read_branch(), Path, O comportamento de `read_branch` da Tarefa 10, agora aqui (§C)., TestBranch, TestBranchRunner (+2 more)

### Community 210 - "TestSessionParser"
Cohesion: 0.15
Nodes (5): _load_cli_module(), _nested_choices(), ArgumentParser, TestSessionDispatch, TestSessionParser

### Community 211 - "ClaudeDriver"
Cohesion: 0.15
Nodes (7): ClaudeDriver, Path, Nunca descobre: o id e atribuido no lancamento., Um provider-session-id invalido nunca vira argv — reusa a validacao de…, O id do Claude e atribuido no lancamento (`--session-id`): o driver nao varre…, TestClaudeNeverDiscovers, TestResumeValidatesProviderSessionId

### Community 212 - "GitRepository"
Cohesion: 0.18
Nodes (7): GitRepository, Git de UM caminho. `runner` e injetavel so para simular falhas que um…, `DIRTY` com qualquer mudanca, inclusive arquivo nao rastreado; senao `CLEAN`.…, CheckoutState, _RepoCase, TestRefs, TestStatus

### Community 213 - "_Case"
Cohesion: 0.15
Nodes (5): _Case, Path, O laco de prova do caminho sem worktree passa por TODAS as refs., O `store.replace(... COMPLETED)` da TUI, sobre a lista falsa., TestSeveralExportRefs

### Community 214 - "GitError"
Cohesion: 0.17
Nodes (9): GitError, Exception, Commit do branch LOCAL `name`, ou `None` se ele nao existe., Commit completo que `rev` nomeia, ou `None` se nao resolve., `(commit, ref)` de cada ref sob `patterns`. Levanta se nao da para listar: uma…, Commits do reflog de `ref`, do mais novo ao mais antigo. E como se leem as…, Caminhos em conflito no indice (`ls-files -u`), sem repeticao., O Git nao pode ser executado, ou respondeu algo que nao se prova. (+1 more)

### Community 215 - "4. Revisão após o piloto (2026-09-19)"
Cohesion: 0.13
Nodes (14): 1. Matriz de contratos, 2.1 Codex — raiz de estado, 2.2 Claude — slug do diretório de projeto, 2.3 Antigravity — ausência de estado local, 2.4 Limite desta tarefa, 2. Notas de caracterização, 3. Decisão consolidada, 4.1 Claude — id atribuído no lançamento (+6 more)

### Community 216 - "GitResult"
Cohesion: 0.19
Nodes (6): GitResult, `git merge --no-edit <ref>` com uma ref completa ja validada; sem `--` entre…, `git branch -d`: o proprio Git recusa um branch nao integrado. Nunca `-D`., So para o rollback que ja provou ter criado `name` no commit registrado., Rodada 1: o motivo de uma falha e a causa, nunca o progresso., TestFailureReason

### Community 218 - "test_supervisor_remove_units.py"
Cohesion: 0.21
Nodes (10): clean_env(), env_for(), Path, Unit tests for supervisor.remove_workspace_units., Ambiente minimo: config/drop-in e keyring sinteticos, nada do operador., Aplica `env` e remove seams herdados que mudariam as raizes., R6: um symlink de wants que sobra reabilita o target no proximo boot., R6: manifesto corrompido nunca e silenciado como se estivesse ausente. (+2 more)

### Community 219 - "Worktree"
Cohesion: 0.21
Nodes (5): parse_worktrees(), Parser do formato `--porcelain -z`: campos terminados por NUL, registros…, Um registro de `git worktree list --porcelain -z`. `branch` e o nome curto (sem…, Worktree, TestWorktreeList

### Community 220 - "sanitize"
Cohesion: 0.23
Nodes (11): FinishPreview, O que a confirmacao do finish mostra. `source_commit` e o HEAD do worktree do…, _cleanup_lines(), _finish_lines(), _lost_line(), Troca cada caractere de controle por um marcador visivel., sanitize(), _preview_lines() (+3 more)

### Community 221 - "_info"
Cohesion: 0.23
Nodes (6): _binding(), _info(), Path, O contrato de ponta a ponta: um probe real sobre `remote_run` nunca aborta, so…, TestRemoteRun, TestSessionServices

### Community 222 - "FakeScreen"
Cohesion: 0.17
Nodes (3): FakeScreen, Tela falsa: guarda o texto por linha e levanta `curses.error` ao escrever fora…, TestCursesTerminal

### Community 223 - ".run"
Cohesion: 0.17
Nodes (6): `timeout`: o das leituras (curto) por padrao; mutacoes passam…, Branch do checkout, ou o commit abreviado num HEAD destacado; `None` em…, O branch que um `refs/remotes/origin/HEAD` simbolico e inequivoco nomeia, ou…, `git check-ref-format --branch` aceita E devolve o nome intacto: a forma…, O branch de `HEAD` como o Git o nomeia, ou `None` num HEAD destacado (ou em…, `git check-ref-format <ref>` para um nome de ref completo.

### Community 224 - "TestConnectDispatch"
Cohesion: 0.20
Nodes (4): _load_cli_module(), Guarda contra regressao: adicionar `connect` nao pode remover ou reescrever…, TestConnectDispatch, TestConnectParserRegistration

### Community 227 - "TestReconcile"
Cohesion: 0.20
Nodes (3): Tarefa 10: um refresh da TUI nao pode subir a revisao de cada sessao a cada…, Um `starting` pertence a um start em voo noutro processo: nem sonda nem grava.…, TestReconcile

### Community 229 - "Adendo — 2026-09-07, 22:00–22:50 BRT"
Cohesion: 0.22
Nodes (9): A1. Correção de escopo: a topologia do piloto anterior não era fiel, A2. Achado bloqueante: namespace rootless sem uplink, A3. Antigravity: reclassificado, não era falha de autenticação, A4. Codex: login sob topologia fiel — PASS, A5. Claude: causa confirmada também por inspeção direta, A6. Correção de redação sobre a cobertura dos testes, A7. Situação por fornecedor, com as quatro separações exigidas, A8. Pendências que impedem fechar o gate (+1 more)

### Community 230 - "Piloto assistido de autenticação — 2026-09-07"
Cohesion: 0.22
Nodes (9): Escopo e estado, Evidência anterior ao login, Login Antigravity — executado pelo operador, Login Claude — executado pelo operador, Piloto assistido de autenticação — 2026-09-07, Recursos efetivamente criados, Resultado observado (2026-09-07, aproximadamente 20:14–20:16 BRT), Resultado observado após o login (2026-09-07, aproximadamente 20:11 BRT) (+1 more)

### Community 233 - "TestSingleRuntimeResume"
Cohesion: 0.36
Nodes (3): Emenda A: `resume` verifica o host, garante o keyring, sobe o target e nunca…, R6: manifesto corrompido em resume levanta PodmanError em vez de silenciar., TestSingleRuntimeResume

### Community 236 - "git.py"
Cohesion: 0.25
Nodes (6): _decode(), GitTimeout, _printable(), cli/asb/checkouts/git.py — o unico ponto que fala com o Git de um checkout.…, O Git foi morto pelo timeout: uma mutacao pode ter ficado pela metade…, A causa de uma falha: as linhas `fatal:`/`error:` do stderr primeiro, depois…

### Community 237 - ".fetch"
Cohesion: 0.25
Nodes (4): CompletedProcess, Path, Nunca `--force`: um worktree com mudancas e recusado pelo Git., Busca `refspec` do repositorio local `source`. As opcoes terminam antes do…

### Community 239 - "AgentAvailability"
Cohesion: 0.29
Nodes (5): AgentAvailability, _first_line(), RunFn, Sanitiza a saida de `--version` para a primeira linha apenas., Resultado sanitizado de `probe()`. `resume_supported` e o unico valor que o…

### Community 240 - "Acceptance report: Agent Sandbox TUI"
Cohesion: 0.29
Nodes (6): 1. Scope and method, 2. Automated scenarios, 3. Complete automated verification, 4. Human pilot (Task 13 Step 3), 5. Known limitations and deferred items, Acceptance report: Agent Sandbox TUI

### Community 241 - "TestInstallGuards"
Cohesion: 0.29
Nodes (3): O CLI precisa rodar de qualquer diretorio, nao so do checkout. Ele ja funciona…, Modo de falha da §16.1: a pasta muda de lugar e o link fica orfao., TestInstallGuards

### Community 243 - "session_volume_mountpoint"
Cohesion: 0.40
Nodes (4): Mountpoint, no host, do volume de sessao de `workspace`. E por ele que o host…, session_volume_mountpoint(), Podman inteiramente mockado: nenhum volume real e inspecionado., TestSessionVolumeMountpoint

### Community 244 - "asb-seed-claude-state"
Cohesion: 0.60
Nodes (5): main(), Grava ao lado e troca por rename. Sem `replace`, usa link(2), que falha se o…, seed(), warn(), write_atomic()

### Community 250 - ".__init__"
Cohesion: 0.50
Nodes (3): LivenessProbe, SessionLister, SessionWriter

## Knowledge Gaps
- **664 isolated node(s):** `entrypoint.sh script`, `start-keyring.sh script`, `DBUS_SESSION_BUS_ADDRESS`, `common.sh script`, `shim.template.sh script` (+659 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **57 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `SandboxFixture` connect `SandboxFixture` to `checkouts/manager.py`, `test_startup_auth.py`, `patch`, `test_credential_writers.py`, `test_sandbox_fixture_guard.py`, `TestSupervisorPilot`, `.test_sessions_close_reattach_uncertain_and_completion`, `TestForwarderIntegration`, `test_provider_auth.py`, `IsolationError`, `FinishCheckout`, `TestTeardownCommandClasses`, `Path`, `test_session_cli.py`, `integration/test_network_gate.py`, `test_entrypoint_concurrency.py`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Why does `GitRepository` connect `GitRepository` to `checkouts/manager.py`, `CheckoutBinding`, `CheckoutManager`, `tui.py`, `.request`, `git.py`, `.fetch`, `BranchInfo`, `lifecycle.py`, `_Case`, `GitError`, `GitResult`, `.__init__`, `Worktree`, `.run`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._
- **Why does `PodmanError` connect `lifecycle.py` to `ConnectionInfo`, `test_doctor.py`, `TestEmendaAChecks`, `TestSingleRuntimeUp`, `TestFinish`, `doctor.py`, `TestPurge`, `run`, `.services`, `test_tui_controller.py`, `TestSessionParser`, `auth.py`, `TestConnectDispatch`, `Layout`, `TestSingleRuntimeResume`, `.controller`, `TestPodmanKindAndStatus`, `TestPurgeAfterDown`, `TestDoctorServiceBlockNeverSwallows`?**
  _High betweenness centrality (0.031) - this node is a cross-community bridge._
- **Are the 18 inferred relationships involving `SandboxFixture` (e.g. with `TestBindMountAtomicReplace` and `TestContainerPermissionsAndPaths`) actually correct?**
  _`SandboxFixture` has 18 INFERRED edges - model-reasoned connections that need verification._
- **Are the 24 inferred relationships involving `CheckoutId` (e.g. with `CheckoutManager` and `CheckoutBinding`) actually correct?**
  _`CheckoutId` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Are the 24 inferred relationships involving `CodexDriver` (e.g. with `LaunchCommand` and `SessionEvidence`) actually correct?**
  _`CodexDriver` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `GitRepository` (e.g. with `CheckoutState` and `CheckoutManager`) actually correct?**
  _`GitRepository` has 13 INFERRED edges - model-reasoned connections that need verification._