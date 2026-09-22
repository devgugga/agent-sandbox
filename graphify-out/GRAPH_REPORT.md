# Graph Report - agent-sandbox  (2026-09-22)

## Corpus Check
- 297 files · ~355,460 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 5881 nodes · 12187 edges · 318 communities (260 shown, 58 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 655 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `2caa3f59`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- interfaces/snapshot.py
- layout_for
- assert.sh
- load_profile
- build_staging
- Pilot
- patch
- permitted
- What You Must Do When Invoked
- AGENTS.md
- What You Must Do When Invoked
- runtime/workspace.py
- RuntimeStorage
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
- test_public_contracts.py
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
- models.py
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
- PodmanError
- Skill: Agent Authoring
- Skill: Commit Curator
- Skill: Agent Authoring
- Skill: Commit Curator
- Skill: Agent Authoring
- Skill: Commit Curator
- login_harness
- asb_server/auth.py
- _make_session
- Redesenho de inicialização e autenticação
- AgentSession
- sessions.py
- .request
- Contratos de Autenticação por Fornecedor e Protocolo de Validação
- get_test_image
- collect_boot_evidence.py
- TestSupervisorPilot
- 3. Resultados dos Ensaios Empíricos
- TestForwarderIntegration
- lifecycle.py
- WorkspaceTransaction
- Secret Service singleton para credenciais dos agentes
- integration/__init__.py
- SandboxFixture
- Design: Modular TUI for projects, worktrees, and agent sessions
- TestTeardownCommandClasses
- .teardown
- TmuxTerminal
- Target file responsibilities
- asb/auth.py
- TestCliParserDispatchParity
- test_entrypoint_concurrency.py
- TestNetworkGateUnits
- _terminal
- CheckoutId
- 4.2 Entities
- TestToolDrift
- CheckoutManager
- TestVerifyClientCommands
- Known Regressions — Sandbox Domain
- forwarder.sh
- FixtureTestCase
- Profile
- .registry
- .controller
- unit/test_network_gate.py
- test_sandbox_fixture_guard.py
- tui.py
- client.ts
- TestCredentialDirectoryMounts
- test_provider_auth.py
- CheckResult
- claim-verifier/agent.md
- regression-sentinel/agent.md
- test-shape-auditor/agent.md
- ProbeResult
- _healthy_probe
- Global Constraints
- Settings
- supervisor.py
- TestAggregateExitCodeDeniesByDefault
- 14. Incremental migration
- _diag
- Emenda A — runtime único systemd e espera única por rede
- install.py
- render
- TestForwarderProcessLifecycle
- Piloto real de inicialização e autenticação — T2
- 6.2. Boot 1 — REPROVADO, e o teste estava contaminado
- DetailPanel.tsx
- _Harness
- TestVerifyCommand
- app.py
- compilerOptions
- test_single_flight.py
- ConnectionInfo
- Module decomposition — final validation — 2026-09-17
- TestUnitSuiteIsolation
- TestLegacyCredentialLayoutWarning
- TestEntrypointCredentialLayout
- 10. Finishing, merging, and cleanup
- TestLiveAuthDoubleOptIn
- lib/tree.ts
- TestVerifyFreshClient
- TestVerifyClientCallBudget
- create_app
- Recuperação do uplink rootless do Podman
- 5. Estado de autenticação medido
- TestEmendaAChecks
- 5. Module architecture
- ProjectRegistryError
- git
- Supervisão da inicialização — Implementation Plan
- integration/test_network_gate.py
- main.py
- DetailPanel.test.tsx
- TestDoctorWebChecksInstalled
- test_login_flow.py
- Workspace Lifecycle & Supervision
- 2026-09-07-startup-auth-redesign-design.md
- Inicialização e autenticação — Implementation Plan
- TestManagedLifecycleCommands
- TestEntrypointNeverDestroysSharedDirectories
- 7. Session continuity
- Agent Sandbox TUI Implementation Plan
- lifecycle.md
- test_agent_drivers.py
- TestFinish
- Autenticação por fornecedor — Implementation Plan
- 6.4. Boot 2 — APROVADO sem comando corretivo
- 6.6. Boot 3 — configuração real: REPROVADO, e com falha silenciosa
- 6.3. Boot 2 preparado — teste discriminante com o drop-in desativado
- 6.8. Troca para o runtime único (Emenda A, Task 13)
- 8. Fases pendentes e janelas
- TestDownKeepsWorkspaceData
- FakeDriver
- 6.11. Boot A3 (um ativo, outro suspenso, runtime único): APROVADO
- 6.5. Orca: excluído e depois REINTEGRADO por decisão do operador
- 6.9. Boot A1 (normal, runtime único): APROVADO, com um defeito de partida
- Provider Authentication
- TestReadSnapshot
- 6.7. Validação pelo Orca BLOQUEADA por defeito do Orca
- .manager
- TestConversationsThePurgeDeletes
- 13. Test strategy
- 8. TUI
- build_tree
- Path
- .write
- .finish
- CodexDriver
- .make
- .commit_on
- test_session_manager.py
- codex.py
- TestLazyDiscoveryWithTheRealCodexDriver
- test_diagnostic_checks.py
- .services
- _Case
- SessionEvidence
- .terminal
- AntigravityDriver
- aggregate_exit_code
- _info
- FakeRun
- test_tui_acceptance.py
- GitRepository
- TestSessionParser
- ClaudeDriver
- TestTreeSuccess
- _Case
- App.tsx
- 4. Revisão após o piloto (2026-09-19)
- Baseline pré-decomposição de módulos — 2026-09-17
- ProjectDetectionTest
- test_supervisor_remove_units.py
- ListedCheckout
- Server Conventions
- _info
- Design: Web interface for agent-sandbox — program and foundation (item 1)
- patch
- TestConnectDispatch
- devDependencies
- Plan: Web interface foundation (item 1)
- agent-sandbox
- .load
- Adendo — 2026-09-07, 22:00–22:50 BRT
- TestDoctor
- ProjectTree.tsx
- TestAssertNoOrphans
- TestServiceState
- prepare_workspace_harness
- scripts
- check_web_health
- Web foundation — operator pilot checklist (NOT EXECUTED)
- common.sh
- test_auth_verify.py
- Acceptance report: Agent Sandbox TUI
- _run_openapi
- TestProjectAdd
- Path
- asb-seed-claude-state
- TestLoginKeyringContract
- test_uv_workspace.py
- FakeTerminal
- e2e.spec.ts
- IsolationError
- GitResult
- test_doctor.py
- TestNoDuplicateProbing
- _AliveRun
- TestCheckGuard
- TestUiBrowserSelection
- test_workspace_supervision.py
- TestPathSeams
- test_keyring_readiness.py
- /graphify
- CommandPalette.tsx
- TestCheckGitInstalled
- TestCheckPodmanInstalled
- TestCheckPodmanVersion
- TestCollectWorkspaces
- CLAUDE.md
- Web Domain Pack
- dependencies
- Web Conventions
- test_session_lifecycle.py
- TestCheckWorkspaceEgress
- 7. The daemon (`asb_server`)
- TestBrokerHandler
- TestInstallServerHappyPath
- 7. Graphify
- 4. Agent Workflow & Operational Rules
- Server Domain Pack
- 9. The front end (`web/`)
- TestCredentialWritersFilesystem
- test_install_server.py
- schema.d.ts
- Skill: asb-dev-stack
- Skill: asb-dev-stack
- Skill: asb-dev-stack
- Claim Verification
- Test Shape
- TestPurgeAfterDown
- .test_evidence_never_carries_captured_provider_output
- 13. Test strategy
- 8. Installation, unit, `ui`, `doctor`
- Google Antigravity & Gemini CLI Configuration
- start-keyring.sh
- TestDoctorServiceBlockNeverSwallows
- TestPurge
- TestLoginPreservesResultsAcrossFailures
- eslint-plugin-react-hooks
- eslint-plugin-react-refresh
- jsdom
- @playwright/test
- asb_server/__init__.py
- tailwindcss
- @tailwindcss/vite
- @testing-library/jest-dom
- @testing-library/react
- @testing-library/user-event
- @types/node
- @types/react
- @types/react-dom
- typescript-eslint
- vite

## God Nodes (most connected - your core abstractions)
1. `SandboxFixture` - 107 edges
2. `CodexDriver` - 104 edges
3. `CheckoutId` - 77 edges
4. `ClaudeDriver` - 73 edges
5. `_completed()` - 73 edges
6. `AntigravityDriver` - 67 edges
7. `GitRepository` - 66 edges
8. `AgentSession` - 64 edges
9. `git()` - 63 edges
10. `CheckoutManager` - 61 edges

## Surprising Connections (you probably didn't know these)
- `pilot_cli()` --uses--> `AntigravityDriver`  [INFERRED]
  tests/integration/test_startup_auth.py → cli/asb/agents/antigravity.py
- `TestAntigravityResumeArgvOnceProvable` --uses--> `AntigravityDriver`  [INFERRED]
  tests/unit/test_agent_drivers.py → cli/asb/agents/antigravity.py
- `TestLaunchAndResumeArgv` --uses--> `AntigravityDriver`  [INFERRED]
  tests/unit/test_agent_drivers.py → cli/asb/agents/antigravity.py
- `TestProbedFully` --uses--> `AntigravityDriver`  [INFERRED]
  tests/unit/test_agent_drivers.py → cli/asb/agents/antigravity.py
- `TestProbeUnknownVersionOutput` --uses--> `AntigravityDriver`  [INFERRED]
  tests/unit/test_agent_drivers.py → cli/asb/agents/antigravity.py

## Import Cycles
- None detected.

## Communities (318 total, 58 thin omitted)

### Community 0 - "interfaces/snapshot.py"
Cohesion: 0.05
Nodes (56): CheckoutKind, cli/asb/checkouts/git.py — o unico ponto que fala com o Git de um checkout.…, checkout_kind(), cli/asb/checkouts/manager.py — listar, inspecionar e criar checkouts.…, `PRIMARY` quando `path` e o checkout primario, comparando caminhos RESOLVIDOS:…, Checkout, CheckoutKind, CheckoutState (+48 more)

### Community 1 - "layout_for"
Cohesion: 0.09
Nodes (25): _git(), layout_for(), prepare_clone(), Exception, Path, cli/asb/workspace.py — identidade do workspace, layout em disco e clone. Duas…, Identidade do workspace, sempre reproduzivel a partir das entradas. O Orca…, Onde tudo mora. `home` e o mesmo caminho no host e no container (D4). (+17 more)

### Community 2 - "assert.sh"
Cohesion: 0.06
Nodes (40): assert_contains(), assert_eq(), assert_fails(), assert_not_contains(), report(), require(), assert.sh script, wait_for() (+32 more)

### Community 3 - "load_profile"
Cohesion: 0.07
Nodes (29): _choice(), load_profile(), _ports(), ProfileError, _publish_ports(), Exception, Path, cli/asb/profile.py — le .agent-sandbox.toml e devolve um perfil validado. O… (+21 more)

### Community 4 - "build_staging"
Cohesion: 0.07
Nodes (38): _allowed_destination_roots(), _allowed_symlink_roots(), build_staging(), copy_file(), denied(), filter_claude_settings(), filter_codex_config(), _key() (+30 more)

### Community 5 - "Pilot"
Cohesion: 0.14
Nodes (9): Pilot, pilot_cli(), CompletedProcess, Path, Process-local seams; host HOME and Podman storage stay unchanged., Connect I1 resource ownership to lifecycle names and on-disk state., Defensive unit contract for WorkspaceTransaction(is_existing=True). Production…, run() (+1 more)

### Community 7 - "permitted"
Cohesion: 0.19
Nodes (7): Handler, main(), permitted(), relay(), Server, Testa a função permitted(method, target) do broker., TestBrokerPermitted

### Community 8 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 9 - "AGENTS.md"
Cohesion: 0.19
Nodes (4): Role, Documents, Git Domain Pack, Review Domain Pack

### Community 10 - "What You Must Do When Invoked"
Cohesion: 0.13
Nodes (15): Part A - Structural extraction for code files, Part B - Semantic extraction (parallel subagents), Part C - Merge AST + semantic into final extraction, Step 0 - GitHub repos and multi-path merge (only if a URL or several paths), Step 1 - Ensure graphify is installed, Step 2.5 - Video and audio (only if video files detected), Step 2 - Detect files, Step 3 - Extract entities and relationships (+7 more)

### Community 11 - "runtime/workspace.py"
Cohesion: 0.07
Nodes (32): _AgentResult, build_proxy(), _get_container_id(), _OptionalContainersResult, Path, cli/asb/runtime/workspace.py — preparo de recursos do workspace (containers,…, Valores produzidos pela preparacao inicial (imagem, clone, squid.conf, redes)…, Resultado de §2-4: servicos adicionais, forwarder e broker Docker — so… (+24 more)

### Community 12 - "RuntimeStorage"
Cohesion: 0.05
Nodes (38): credential_mount_args(), ensure_credential_dirs(), ensure_credentials_volume(), ensure_session_volume(), ensure_toolcache_volume(), _mkdir_private(), Path, cli/asb/runtime/storage.py — dona dos volumes de credencial, sessao e cache de… (+30 more)

### Community 13 - "sync-skills.mjs"
Cohesion: 0.17
Nodes (8): BANNER_LINES, CHECK, __dirname, MIRRORS, PRUNE, ROOT, skills, VENDOR

### Community 14 - "TestInstallRuntime"
Cohesion: 0.05
Nodes (18): I2: Header must be at the very start of the file, not matched as substring., I2: remove_project_dropin must verify mode before unlink., I4: a entrada trocada depois da ultima validacao nao e removida. O gancho troca…, Drop-in do projeto pronto para remocao, mais o gancho de reapontamento. Devolve…, Segunda janela TOCTOU, lado observavel: o inode e reconferido antes do unlink.…, Segunda janela TOCTOU, lado irredutivel: a troca cai DENTRO da syscall. Entre…, O CLI precisa rodar de qualquer diretorio, nao so do checkout. Ele ja funciona…, I3: Manifest must cover all files in asb/ package with sha256 and mode. (+10 more)

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
Cohesion: 0.20
Nodes (9): 1. Agent Architecture: "Domain Packs", 1. Think Before Coding, 2. Available Subagents, 2. Simplicity First, 3. Fundamental Engineering Guidelines, 3. Surgical Changes, 4. Goal-Driven Execution, 5. Skills: Single Source of Truth & Synchronization (+1 more)

### Community 22 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 23 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 24 - "test_public_contracts.py"
Cohesion: 0.06
Nodes (26): Path, Delega para `lifecycle_payload`: mesmas quatro chaves, mesma ordem, que…, Construtor de payload que NAO exige uma instancia completa de `ConnectionInfo`…, _load_cli_module(), _mixed_verify_ssh_response(), _nested_subcommands(), _ok(), ArgumentParser (+18 more)

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
Nodes (7): Path, Testes de autenticação e volume de credenciais em cli/asb/lifecycle.py., Espelha a estrutura real de Mounts retornada por podman inspect., TestAuthLifecycle, TestCheckKeyringService, TestKeyringServiceLifecycle, valid_keyring_mounts()

### Community 41 - "test-recipe.sh"
Cohesion: 0.40
Nodes (3): RECIPE_STAGE, test-recipe.sh script, XDG_CONFIG_HOME

### Community 44 - "TestCheckStatus"
Cohesion: 0.07
Nodes (4): Testes de cli/asb/auth.py — separacao de status de conta, rede e…, TestAuthResult, TestCheckStatus, TestStatusCommand

### Community 48 - "doctor.py"
Cohesion: 0.32
Nodes (6): ArgumentParser, build_parser(), main(), doctor(), Path, cli/asb/doctor.py — diagnostica o ambiente e nomeia a correcao. Regra: toda…

### Community 49 - "Singleton Secret Service Implementation Plan"
Cohesion: 0.22
Nodes (8): Global Constraints, Singleton Secret Service Implementation Plan, Task 1: Criar um teste de regressão isolado para o Secret Service, Task 2: Transformar `start-keyring.sh` em serviço singleton, Task 3: Adicionar o ciclo de vida do serviço global, Task 4: Tornar o entrypoint exclusivamente cliente do Secret Service, Task 5: Validar login real no mesmo serviço e diagnosticar falhas, Task 6: Atualizar o SSoT e executar a verificação completa

### Community 50 - "File Structure"
Cohesion: 0.12
Nodes (16): agent-sandbox Implementation Plan, File Structure, Global Constraints, Self-Review, Task 0: Helper de asserção, Task 10: Domain pack e extensão aos demais projetos, Task 11: Tornar o sandbox o único caminho, Task 1: Imagem base com host keys estáveis (+8 more)

### Community 51 - "models.py"
Cohesion: 0.09
Nodes (34): A arvore inteira de UMA leitura: projetos, um `CheckoutView` por checkout,…, Snapshot, Um worktree que o Git lista mas o registro nao conhece (criado fora da TUI).…, UnregisteredView, _checkout_node(), CheckoutNode, _project_node(), ProjectNode (+26 more)

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

### Community 62 - "PodmanError"
Cohesion: 0.08
Nodes (33): check_keyring_service(), ensure_keyring_data_volume(), ensure_keyring_pass(), ensure_keyring_runtime_volume(), ensure_keyring_service(), _inspect_keyring_container(), _keyring_mount_contract_issue(), Path (+25 more)

### Community 69 - "login_harness"
Cohesion: 0.11
Nodes (11): login_harness(), Caso do brief: o login interativo termina bem, mas o cliente NOVO diz deslogado…, A4 ainda nao esta integrado: sem `verify_client`, o resultado do agy e…, Um fornecedor que falha nao apaga o resultado dos outros, e o codigo agregado…, Cancelar preserva dados: nada de volume, nada de credencial removida — apenas o…, `asb-login` era um nome fixo: duas execucoes concorrentes se matavam. Nenhuma…, Encerrar o cliente de login e verificar OUTRO cliente antes de declarar…, Isola `auth.login` do mundo: nenhum podman, nenhum subprocesso real. Devolve um… (+3 more)

### Community 70 - "asb_server/auth.py"
Cohesion: 0.05
Nodes (41): FastAPI, FileResponse, post, create_session(), BaseModel, get, Response, server/asb_server/api/auth.py — POST /api/auth/session, GET /api/auth/me. The… (+33 more)

### Community 71 - "_make_session"
Cohesion: 0.05
Nodes (33): datetime, Exception, Path, Retorna `raw[key]`, ou levanta `SessionStoreError` nomeando o campo quando ele…, Opcional: registros gravados antes do campo nao tem a chave e decodificam como…, Falha ao ler/gravar o registro de sessoes, ou um registro invalido., Registro atomico, sem estado em memoria, de sessoes de agente. Cada chamada le…, SessionStore (+25 more)

### Community 72 - "Redesenho de inicialização e autenticação"
Cohesion: 0.14
Nodes (14): 1. Objetivo e limites, 2. Evidência e incertezas, 3. Alternativas e decisão proposta, 4. Contratos globais, 5.1 Sondas e limites, 5.2 Forwarder e criação transacional, 5. Inicialização: responsabilidades e estado, 6.1 Persistência e concorrência: gate obrigatório (+6 more)

### Community 73 - "AgentSession"
Cohesion: 0.04
Nodes (54): default_checkouts(), _default_liveness(), _probe_liveness(), O corpo da sonda de liveness, numa UNICA implementacao: pela conexao viva do…, Sonda padrao (usa o `TmuxTerminal` deste modulo): o fallback de…, O `CheckoutManager` padrao (spec §7.4: o daemon monta o seu assim), com o que…, Sonda do tmux da sessao pela conexao viva do workspace. O corpo (try/except,…, session_liveness() (+46 more)

### Community 74 - "sessions.py"
Cohesion: 0.11
Nodes (30): default_drivers(), _existing(), _manager(), project_add(), AgentKind, Path, TextIO, cli/asb/interfaces/sessions.py — sessoes persistentes de agente pelo CLI. `asb-… (+22 more)

### Community 75 - ".request"
Cohesion: 0.10
Nodes (8): _Case, Path, TestCreate, TestInspect, TestList, TestRefusals, TestRollbackEdges, TestTransaction

### Community 76 - "Contratos de Autenticação por Fornecedor e Protocolo de Validação"
Cohesion: 0.08
Nodes (26): 1. Sumário Executivo, 2. Matriz de Contratos por Fornecedor, 3.1 Claude Code: Análise Forense do Binário e a Divergência do Libsecret, 3.2 OpenAI Codex: Análise de Armazenamento e Configuração Efetiva, 3.3 Google Antigravity: Análise de D-Bus, Secret Service e Sessão SSH, 3. Análise Detalhada dos Binários e Divergências Históricas, 4.1 Falha de Symlink sob `replace()` Atômico, 4.2 Rejeição de Symlinks por `O_NOFOLLOW` (+18 more)

### Community 77 - "get_test_image"
Cohesion: 0.15
Nodes (11): get_test_image(), Container-level validation using SandboxFixture under uid 1000., Proves uid 1000 can create, chmod 0600, write, and read credential files., Exercises absent destination, empty 0-byte file, malformed JSON, and broken…, Simulates the entrypoint.sh symlink layout inside the container as uid 1000.…, Proves Claude Code CLI (2.1.263) status handling under 0-byte, corrupt, broken,…, Returns local agent-sandbox image if available, else alpine fallback., Tests atomic replace behavior on bind-mounted files vs bind-mounted directories. (+3 more)

### Community 78 - "collect_boot_evidence.py"
Cohesion: 0.07
Nodes (29): _auth(), _boot_id(), collect(), _containers(), main(), _manifest(), _network(), _port() (+21 more)

### Community 79 - "TestSupervisorPilot"
Cohesion: 0.14
Nodes (8): Proves runtime launcher helper seamlessly attaches to an already running…, Proves literal unit behavior: podman start --attach on running container…, Proves SandboxFixture refuses foreign resources, production names, and external…, Empirical integration test suite for systemd rootless supervision., Proves systemd Type=exec restarts container on failure, preserving identity and…, Proves systemd Restart=always restarts container even when exiting cleanly…, Proves ExecStopPost stops container when ExecStartPost fails during startup., TestSupervisorPilot

### Community 80 - "3. Resultados dos Ensaios Empíricos"
Cohesion: 0.15
Nodes (12): 1. Objetivo e Escopo, 2. Artefatos Desenvolvidos, 3.1. Recuperação após Falha e Preservação de Identidade, 3.2. Saída Limpa Inesperada (Código 0), 3.3. Falha em `ExecStartPost` e Limpeza por `ExecStopPost`, 3.4. Reconexão a Container em Execução, 3.5. Proteção de Isolamento, 3. Resultados dos Ensaios Empíricos (+4 more)

### Community 81 - "TestForwarderIntegration"
Cohesion: 0.12
Nodes (9): tests/integration/test_forwarder.py — Integration tests for port forwarder…, Proves initial bind errors or invalid port arguments fail immediately., Empirical integration tests for asb-forwarder and unprivileged low ports., Proves undeclared ports remain closed and forwarder is not a general proxy., Proves killing one listener causes forwarder failure, supervisor restart, and…, Proves the proxy image explicitly contains bash and the forwarder executable., Proves the old un-supervised script masks child process failure., Proves forwarder handles SIGTERM cleanly and exits status 0. (+1 more)

### Community 82 - "lifecycle.py"
Cohesion: 0.05
Nodes (58): build(), _current_revision(), discover_mise_dirs(), down(), emit(), ensure_runtime(), ensure_ssh_key(), list_workspaces() (+50 more)

### Community 83 - "WorkspaceTransaction"
Cohesion: 0.06
Nodes (24): Path, cli/asb/runtime/transaction.py — livro-razao de posse de recursos criados…, Rastreia recursos criados durante a transacao de up para rollback estrito por…, WorkspaceTransaction, _once(), Unit tests for cli/asb/runtime_check.py — papel keyring (Emenda A §5)., TestKeyringRole, tests/unit/test_runtime_transaction.py — fronteira de rollback de… (+16 more)

### Community 84 - "Secret Service singleton para credenciais dos agentes"
Cohesion: 0.22
Nodes (9): Ciclo de vida, Compatibilidade e migração, Contexto, Critérios de aceitação, Decisão de arquitetura, Fora de escopo, Objetivo, Secret Service singleton para credenciais dos agentes (+1 more)

### Community 86 - "SandboxFixture"
Cohesion: 0.05
Nodes (24): Registra uma sessao tmux que roda DENTRO de `container` (um container desta…, Encerra a sessao se o container ainda roda; ausente nao e erro. O servidor tmux…, Sets up dedicated isolated paths, keys, launcher, and volumes., Creates the synthetic persistent container., Renders the systemd unit content for the pilot., Isolated sandbox fixture context manager for integration tests., Installs and reloads the unit in user systemd., Stops the supervised systemd unit. (+16 more)

### Community 87 - "Design: Modular TUI for projects, worktrees, and agent sessions"
Cohesion: 0.15
Nodes (13): 11.1 General rule, 11.2 Main cases, 11. Failure handling, 12. Security, 15. Acceptance criteria, 16. Expected outcome, 1. Context, 2. Goals (+5 more)

### Community 88 - "TestTeardownCommandClasses"
Cohesion: 0.11
Nodes (6): _FixtureCase, tests/unit/test_isolation_guard.py — guardas de isolamento, CLI publico e…, `down` remove o arquivo, mas o manager guarda o service 'failed' (is-active…, Exaustao do laco de `_quiesce_unit`: rc=0 em todo `stop`, estado imovel. O laco…, `sentinel_exists` so traduz rc 0/1; qualquer outro e falha de consulta.…, TestTeardownCommandClasses

### Community 89 - ".teardown"
Cohesion: 0.11
Nodes (10): BaseException, CompletedProcess, Path, Runs a command inside a container via podman exec. `container` defaults to the…, Sobe (ou reaproveita) um cliente PROPRIO da fixture, montando SOMENTE as…, Executes the ASB CLI within the isolated environment., O ambiente isolado que `cli()` passa ao CLI real; um teste que chama o pacote…, Onde units registradas podem morar: runtime do manager e config do usuario. (+2 more)

### Community 90 - "TmuxTerminal"
Cohesion: 0.11
Nodes (21): Identificador do terminal (tmux) ligado a uma sessao., TerminalId, _detail(), _filter(), _no_server(), CompletedProcess, Path, Protege um argumento do separador ";" do proprio tmux. (+13 more)

### Community 91 - "Target file responsibilities"
Cohesion: 0.20
Nodes (10): Agent Sandbox Module Decomposition Implementation Plan, Completion evidence, Global Constraints, Target file responsibilities, Task 1: Freeze observable contracts before extraction, Task 2: Move provider-specific auth rules into agent drivers, Task 3: Extract runtime storage ownership from lifecycle, Task 4: Extract transaction and sandbox orchestration (+2 more)

### Community 92 - "asb/auth.py"
Cohesion: 0.06
Nodes (50): cli/asb/agents/antigravity.py — driver do Antigravity CLI (`agy`). O binario de…, Sempre `unknown`, SEM tocar podman: `agy` nao possui comando de status local…, AuthResult, _contains_code(), _now_iso(), cli/asb/agents/base.py — driver base de provedor de agente de IA. Um…, Casa um CODIGO NUMERICO delimitado (nao digito antes nem depois). R4 do…, Classifica o RESULTADO de uma chamada real (ou a decisao de nao faze-la). Pura:… (+42 more)

### Community 93 - "TestCliParserDispatchParity"
Cohesion: 0.06
Nodes (23): _dispatched_commands(), _load_cli_module(), _nested_subcommands(), ArgumentParser, Unit tests for cli/asb-agent — paridade entre parser e despacho. B#1: a Tarefa…, Tarefa 4: `connect` e um subcomando de topo como qualquer outro (registrado no…, Tarefa 9: a mesma paridade, nos dois sentidos, para cada subcomando aninhado…, Tarefa 10: `tui` e um comando de topo sem subcomandos nem argumentos; as acoes… (+15 more)

### Community 94 - "test_entrypoint_concurrency.py"
Cohesion: 0.25
Nodes (4): Starts the supervised systemd unit., skipUnless, tests/integration/test_entrypoint_concurrency.py — agentes que partem juntos.…, TestEntrypointConcurrentStart

### Community 95 - "TestNetworkGateUnits"
Cohesion: 0.06
Nodes (9): Unit tests for cli/asb/supervisor.py — systemd supervision and unit generation., I1: `remove_workspace_units` removia unidades por glob `asb-{ws}-*.service`,…, Sem manifesto legivel, nao ha como saber quais nomes de servico pertencem a…, Emenda A §3/§4: toda unidade de container espera a conectividade real., Emenda A §5: o keyring e uma unidade systemd com sonda de prontidao., TestContainerUnitAndRender, TestKeyringUnit, TestNetworkGateUnits (+1 more)

### Community 96 - "_terminal"
Cohesion: 0.08
Nodes (16): attach_remote(), _connection(), _done(), Testes de `asb.sessions.terminal` (Tarefa 7): backend tmux via SSH. Cobre o…, tmux falso de uma sessao RENOMEADA (o `C-b $` do operador, ou o proprio…, _renamed_tmux(), _RunContract, _terminal() (+8 more)

### Community 97 - "CheckoutId"
Cohesion: 0.06
Nodes (41): AssertionError, CheckoutId, str, Identificador estavel de um checkout (prefixo "c-" + hex aleatorio)., CheckoutBinding, Vinculo entre um checkout do operador e um projeto do registro., BaseException, Exception (+33 more)

### Community 98 - "4.2 Entities"
Cohesion: 0.25
Nodes (8): 4.1 Relationships, 4.2 Entities, 4.3 Distinct identifiers, 4. Domain model, `AgentSession`, `Checkout`, `Project`, `SandboxRuntime`

### Community 100 - "CheckoutManager"
Cohesion: 0.07
Nodes (27): CheckoutError, CheckoutManager, CreatePreview, Exception, Path, O checkout como o Git o ve agora. Levanta se o caminho sumiu, se o Git nao o…, Valida o pedido inteiro sem escrever nada., Caminho absoluto com o pai resolvido, contido na raiz resolvida. (+19 more)

### Community 101 - "TestVerifyClientCommands"
Cohesion: 0.24
Nodes (4): As chamadas usam flags CONFIRMADAS na versao fixada (A1/A4), stdin fechado, e…, TestVerifyClientCommands, FixtureHost, systemctl/podman/pgrep simulados para o teardown da SandboxFixture.

### Community 102 - "Known Regressions — Sandbox Domain"
Cohesion: 0.14
Nodes (14): Known Regressions — Sandbox Domain, R10 — Initializing the rootless network namespace before real connectivity, R11 — Driving a systemd-supervised container with Podman directly, R12 — PID-derived names for temporary paths on a shared volume, R13 — A test that pins the defect's own output, R1 — Prefix matching without a delimiter, R2 — Credential storage behind a symlink or a single-file bind mount, R3 — Treating a provider CLI's exit 0 as proof the action happened (+6 more)

### Community 104 - "FixtureTestCase"
Cohesion: 0.08
Nodes (16): _build_dist(), FixtureTestCase, Path, TestClient, `/api/*` never falls back to `index.html`, status AND body., `web/dist` missing: `/` is 503 naming the fix; `/api` still works — a front end…, Common fixture for `--fixture`-reader tests: a real token/session (auth is…, A minimal but real `web/dist`: an `index.html` distinguishable from a 404 body,… (+8 more)

### Community 105 - "Profile"
Cohesion: 0.08
Nodes (18): Profile, Encaminha SO as portas declaradas para o host., start_forwarder(), Testa cli/asb/install.py broker()., Testa o comportamento de host_api em cli/asb/lifecycle.py., TestBrokerInstaller, TestLifecycleHostApi, _fake_storage() (+10 more)

### Community 106 - ".registry"
Cohesion: 0.07
Nodes (16): CheckoutBindingTests, ConcurrencyAndIsolationTests, CorruptionAndSchemaRejectionTests, DiscoveryAndDeduplicationTests, _init_repo(), IntegrationBranchDiscoveryTests, _linked_worktree(), LookupAndIdempotencyTests (+8 more)

### Community 107 - ".controller"
Cohesion: 0.07
Nodes (11): FakeScreen, Piloto 1: o curses apagava o erro do tmux assim que o filho saia; com exit != 0…, Contexto §E: o `manager.attach` da Tarefa 8 retoma nativamente um…, Tela falsa: guarda o texto por linha e levanta `curses.error` ao escrever fora…, TestActions, TestAttach, TestCursesTerminal, TestRefresh (+3 more)

### Community 108 - "unit/test_network_gate.py"
Cohesion: 0.14
Nodes (8): _FakeClock, Unit tests for cli/asb/network_gate.py — espera unica por conectividade real…, Cada leitura avanca `step` segundos., _result(), TestGateNeverSpawnsProcesses, TestGateTarget, TestRuntimeShipsNetworkGate, TestWaitForNetwork

### Community 109 - "test_sandbox_fixture_guard.py"
Cohesion: 0.31
Nodes (6): _podman_names(), skipUnless, Integration test for tests/integration/sandbox_fixture.py — guarda do setup.…, O volume de sessao e criado por `lifecycle`, nao pela fixture. Por nao estar…, TestSandboxFixtureEnterGuard, TestSessionVolumeTeardown

### Community 110 - "tui.py"
Cohesion: 0.05
Nodes (51): CreateCheckout, FinishPreview, `base_commit` e o commit que a previa mostrou e o operador confirmou; `create`…, O que a confirmacao do finish mostra. `source_commit` e o HEAD do worktree do…, BaseException, _reason(), _cleanup_lines(), CursesTerminal (+43 more)

### Community 111 - "client.ts"
Cohesion: 0.09
Nodes (21): client, createSession(), errorDetail(), ForbiddenError, getHealth(), getMe(), getTree(), HealthResponse (+13 more)

### Community 112 - "TestCredentialDirectoryMounts"
Cohesion: 0.14
Nodes (6): A1 provou: `rename` sobre symlink corta o vinculo com o volume, e sobre arquivo…, `ensure_credential_dirs` toca um caminho REAL (o mountpoint que o podman…, A causa confirmada: `: > "$stored"` deixava um arquivo de 0 bytes que nunca…, M10: um volume cujo `_data` nao aceita escrita — o estado que o piloto real…, O ponto de integracao inteiro do diff: os mounts tem de chegar a LINHA DE…, TestCredentialDirectoryMounts

### Community 113 - "test_provider_auth.py"
Cohesion: 0.12
Nodes (12): get_test_image(), _live_auth_enabled(), _live_auth_file_selected(), skipUnless, tests/integration/test_provider_auth.py — verificacao real e piloto (A4). Duas…, Guarda de isolamento: os volumes NOMEADOS nos mounts sao SOMENTE os desta…, Chamadas REAIS via `auth.verify_client()`. So rodam com `ASB_LIVE_AUTH=1` E…, Returns the local agent-sandbox image name if available, else ''. (+4 more)

### Community 114 - "CheckResult"
Cohesion: 0.08
Nodes (52): check_cli_guard(), check_credentials_volume(), check_docker_broker(), check_git_installed(), check_guard(), check_image(), check_legacy_agent_container(), check_netns_producers_third_party() (+44 more)

### Community 118 - "ProbeResult"
Cohesion: 0.03
Nodes (55): gate_target(), main(), cli/asb/network_gate.py — espera unica por conectividade real do host.…, Destino sondado; `ASB_NETWORK_GATE_TARGET` o substitui em ambiente isolado., Bloqueia ate o host alcancar `target`; devolve 0. O journal recebe so mudancas…, wait_for_network(), probe_host(), probe_host_ports() (+47 more)

### Community 119 - "_healthy_probe"
Cohesion: 0.17
Nodes (8): _gate_then(), _healthy_probe(), _ok(), Sem prompt, sem `-p`: `agy models` e a chamada real (A1 confirmou o subcomando;…, Resultados do gate SSH observacional e da unica chamada real., TestVerifyClientAgy, TestVerifyClientFormatNormalization, TestVerifyClientInfrastructureGates

### Community 120 - "Global Constraints"
Cohesion: 0.12
Nodes (17): Global Constraints, Runtime único systemd — Implementation Plan, Task 10: Teste de integração da espera com systemd real, Task 11: Testes em shell no runtime único, Task 12: Verificação completa antes da máquina real, Task 13: Troca na máquina real (janela do operador), Task 14: Boots reais (janelas do operador, spec §7.2), Task 15: Fechamento (+9 more)

### Community 121 - "Settings"
Cohesion: 0.09
Nodes (16): server/asb_server/settings.py — the daemon's configuration. `Settings` is a…, The daemon's resolved configuration. Task 4 reads `token_path` and…, Settings, AuthTestCase, TestClient, server/tests/test_auth.py — Task 4: daemon authentication. Deliberately named…, A syntactically valid `<id>.<signature>` cookie whose signature does not match…, Whole-branch review, Important 1: `_sign` calls `session_id.encode("ascii")`… (+8 more)

### Community 122 - "supervisor.py"
Cohesion: 0.09
Nodes (37): _atomic_write_text(), ContainerUnit, escape_systemd_arg(), install_keyring_unit(), install_workspace(), keyring_container_name(), keyring_unit_name(), network_unit_name() (+29 more)

### Community 123 - "TestAggregateExitCodeDeniesByDefault"
Cohesion: 0.18
Nodes (6): C1: o agregado nega por padrao. A versao anterior testava os estados RUINS e…, A regressao propriamente dita: um estado que ninguem previu., O caminho exato do achado: quando a A4 alimentar `pending` no `auth status`, um…, Nao ter perguntado a ninguem nao e prova de nada., Duas copias da regra foi como `pending` ficou certo num caminho e valendo 0 no…, TestAggregateExitCodeDeniesByDefault

### Community 124 - "14. Incremental migration"
Cohesion: 0.29
Nodes (7): 14. Incremental migration, Stage 1 — Model and connection without runtime changes, Stage 2 — Agent drivers, Stage 3 — Persistent sessions, Stage 4 — Navigator TUI, Stage 5 — Worktrees and cleanup, Stage 6 — Reduce large modules

### Community 125 - "_diag"
Cohesion: 0.08
Nodes (25): _line(), Any, cli/asb/diagnostics/report.py — apresentacao (texto/JSON) e politica de codigo…, JSON identico ao que `doctor(as_json=True)` imprimia antes desta Tarefa:…, Codigo de saida agregado do modo texto. NAO esta na lista de interfaces do…, Primitiva de renderizacao de uma linha de texto do doctor. Escreve em `lines`…, Texto identico ao que `doctor()` imprimia antes desta Tarefa. Caso especial…, render_json() (+17 more)

### Community 126 - "Emenda A — runtime único systemd e espera única por rede"
Cohesion: 0.14
Nodes (14): 10. Evidência, 1. Motivo, 2. Decisões do operador, 3. Arquitetura, 4. A espera por rede, 5. Keyring e troca, 6. O que sai e o que muda, 7.1. Testes automatizados (+6 more)

### Community 127 - "install.py"
Cohesion: 0.07
Nodes (45): check_project_dropin_absent(), Emenda A: o drop-in do projeto criava o namespace rootless cedo em todo boot., Produtores do namespace rootless no boot que NAO sao do ASB. Duas classes, as…, third_party_netns_producers(), broker(), check_project_dropin(), _check_tool_version(), get_dropin_path() (+37 more)

### Community 128 - "render"
Cohesion: 0.10
Nodes (19): normalize_domains(), Exception, Path, cli/asb/squid.py — junta a allowlist base com o perfil e emite squid.conf. A…, read_base(), render(), SquidError, a_file() (+11 more)

### Community 129 - "TestForwarderProcessLifecycle"
Cohesion: 0.14
Nodes (6): Popen, tests/unit/test_forwarder_script.py — Unit tests for image/forwarder.sh…, Tests input validation of image/forwarder.sh., Tests process supervision semantics: fail-fast on child death and SIGTERM…, TestForwarderProcessLifecycle, TestForwarderScriptValidation

### Community 130 - "Piloto real de inicialização e autenticação — T2"
Cohesion: 0.15
Nodes (13): 1.1. A imagem foi reconstruída antes do piloto, 1. Ambiente e versões, 2. Inventário de coexistência (spec §7), 3. Workspace-piloto, 4. Coletor de evidência, 6.10. Boot A2 (rede atrasada, runtime único): APROVADO, 6.12. Retomada do suspenso (critério 2), 6.1. Fase (c) preparada — aguardando janela de reboot (+5 more)

### Community 131 - "6.2. Boot 1 — REPROVADO, e o teste estava contaminado"
Cohesion: 0.15
Nodes (13): 6.2. Boot 1 — REPROVADO, e o teste estava contaminado, A ferramenta tinha avisado, Causa-raiz: o drop-in do próprio projeto cria o namespace em todo boot, Diagnóstico, Duas medições descartadas por serem inválidas, Estado preparado depois do boot 1, Linha do tempo medida, O papel do workspace legacy (+5 more)

### Community 132 - "DetailPanel.tsx"
Cohesion: 0.12
Nodes (24): CheckoutFields(), CheckoutRow(), CheckoutRowNode, CheckoutRowProps, UnregisteredFields(), CheckoutDetails(), formatTimestamp(), SessionDetails() (+16 more)

### Community 133 - "_Harness"
Cohesion: 0.10
Nodes (17): _fake_storage(), _Harness, Path, Ordem REAL de `WorkspaceRuntime.prepare()` (R6): prepare-clone, create-network…, §2-4 (servicos, forwarder, broker docker) rodam DEPOIS do proxy e ANTES do…, Ja coberto em test_lifecycle.py via `up()`; repetido aqui no nivel de…, §7: `supervisor.install_workspace` REESCREVE o gate de rede compartilhado…, `RuntimeStorage` REAL com os quatro pontos que tocariam disco ou Podman… (+9 more)

### Community 134 - "TestVerifyCommand"
Cohesion: 0.18
Nodes (4): `verify(ws, provider, json_output=...)`: mesmo schema de relatorio de…, `verify` nunca muta estado: nenhuma chamada a login()/operator_lock., O teste de log exigido pelo brief: fixtures com token, bearer e codigo OAuth…, TestVerifyCommand

### Community 135 - "app.py"
Cohesion: 0.11
Nodes (21): Future, server/asb_server/api — the daemon's route modules, one per resource. `auth.py`…, get_snapshot_service(), get_tree(), get, Request, TreeResponse, server/asb_server/api/tree.py — GET /api/tree. Requires the session cookie:… (+13 more)

### Community 136 - "compilerOptions"
Cohesion: 0.07
Nodes (26): DOM, DOM.Iterable, ES2022, playwright.config.ts, src, tests, vite/client, vite.config.ts (+18 more)

### Community 137 - "test_single_flight.py"
Cohesion: 0.10
Nodes (14): _empty_snapshot(), TestClient, server/tests/test_single_flight.py — Task 5: the three spec Section 7.4…, Regression coverage for fix round 1, Important 1: `get_snapshot_service`…, Property 1 (single-flight) and property 3 (fresh services every read, proven by…, Property 2 (worker thread). This test demonstrates — with a wall-clock bound,…, The daemon imports `asb.interfaces.snapshot`, never `asb.interfaces.tui` (which…, The other half of `TestDaemonNeverImportsCurses` above: not only must `curses`… (+6 more)

### Community 138 - "ConnectionInfo"
Cohesion: 0.08
Nodes (22): connect(), cli/asb/interfaces/cli.py — acesso SSH direto a um workspace vivo, sem depender…, Substitui o processo do host por um `ssh` conectado a `workspace`. So a parte…, CompletedProcess, Roda `argv` DENTRO do sandbox por SSH nao interativo e devolve o stdout, com…, remote_run(), ConnectionInfo, Argumentos de `ssh` para esta conexao, como LISTA — nunca uma string de shell.… (+14 more)

### Community 139 - "Module decomposition — final validation — 2026-09-17"
Cohesion: 0.10
Nodes (20): 10. Tests removed in this task, 1. Size: before → after, 2.1 `cli/asb/lifecycle.py` — CLI-facing workspace facade, 2.2 `cli/asb/auth.py` — provider account orchestration, 2.3 `cli/asb/doctor.py` — diagnostic composition only, 2.4 `cli/asb/agents/base.py` + `{claude,codex,antigravity}.py` — provider drivers, 2.5 `cli/asb/runtime/storage.py` — credential/session/toolcache volume ownership, 2.6 `cli/asb/runtime/transaction.py` — creation-rollback ledger (+12 more)

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

### Community 145 - "lib/tree.ts"
Cohesion: 0.19
Nodes (15): ancestorKeys(), buildRows(), checkoutKey(), cmp(), FoldableRow, noteKey(), projectKey(), sessionKey() (+7 more)

### Community 146 - "TestVerifyFreshClient"
Cohesion: 0.25
Nodes (3): O `try` comeca ANTES do `podman run`: um Ctrl-C ou uma falha entre a criacao e…, `agy -p ping` bloqueia 60s quando deslogado (A1). Enquanto A4 nao entrega…, TestVerifyFreshClient

### Community 147 - "TestVerifyClientCallBudget"
Cohesion: 0.18
Nodes (3): Uma chamada por fornecedor por `verify_client`, sem retry, e sempre observavel…, TestVerifyClientCallBudget, _unreachable_probe()

### Community 148 - "create_app"
Cohesion: 0.13
Nodes (15): JSONResponse, create_app(), _log_requests(), Exception, Request, Response, SnapshotReader, The daemon's FastAPI app. `settings`, `snapshot_reader` and the ONE… (+7 more)

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
Cohesion: 0.12
Nodes (18): _checkout_workspace(), _discover_integration_branch(), _git_common_dir(), ProjectRegistry, ProjectRegistryError, Exception, Path, _T (+10 more)

### Community 154 - "git"
Cohesion: 0.09
Nodes (4): TestCleanupAfterProof, git(), TestRefs, TestRemoteDefaultBranch

### Community 155 - "Supervisão da inicialização — Implementation Plan"
Cohesion: 0.22
Nodes (9): Global Constraints, I1 — Provar supervisão e criar fixture isolada, I2 — Diagnóstico tipado e prontidão observacional, I3 — Instalação versionada e uma única supervisão, I4 — Forwarder com falha visível e portas baixas, I5 — Integrar ciclo de vida, prontidão e rollback de criação, I6 — Adoção e rollback sem recriação dos workspaces, Saída desta frente (+1 more)

### Community 156 - "integration/test_network_gate.py"
Cohesion: 0.31
Nodes (6): _free_port(), _is_active(), skipUnless, Integracao real: a espera por rede segura unidades dependentes (Emenda A §7.1).…, TestNetworkGateHoldsDependents, _wait_for()

### Community 157 - "main.py"
Cohesion: 0.16
Nodes (19): Namespace, InsecureModeError, RuntimeError, A secret file's mode is looser than 0600. `str(exc)` names the exact `chmod`…, _build_parser(), main(), _openapi(), ArgumentParser (+11 more)

### Community 158 - "DetailPanel.test.tsx"
Cohesion: 0.14
Nodes (13): jsonResponse(), loadInitialTree(), renderApp(), wrapper(), DetailPanel(), agentSandbox, checkout(), docsSite (+5 more)

### Community 159 - "TestDoctorWebChecksInstalled"
Cohesion: 0.17
Nodes (3): patch, As seis checagens da Emenda F, uma por vez, com sistema de arquivos e…, TestDoctorWebChecksInstalled

### Community 160 - "test_login_flow.py"
Cohesion: 0.11
Nodes (7): cli/asb/runtime/ — fronteira tipada de descoberta e execucao de sandboxes.…, Testes do fluxo de login seletivo, persistencia e fixacao de versoes (A3).…, `driver_for` e o unico ponto de despacho publico de `auth.py` para os tres…, Cancelar no codex nao pode engolir o resultado ja obtido do claude: o operador…, TestCancellationDuringAll, TestDriverFor, TestOperatorLock

### Community 161 - "Workspace Lifecycle & Supervision"
Cohesion: 0.11
Nodes (19): 1. Ownership: systemd starts, Podman creates, 2. Commands and State Transitions, 3. Recovery by Category, 4. Direct SSH access without Orca, 5. Persistent agent sessions, 6. The TUI, 7. Finishing a worktree, 8. Internal Module Boundaries (+11 more)

### Community 162 - "2026-09-07-startup-auth-redesign-design.md"
Cohesion: 0.19
Nodes (6): Global Constraints, Rootless Uplink Recovery Implementation Plan, Task 1: Encapsular a inicialização do namespace rootless, Task 2: Aplicar o helper em `up` e `resume`, Task 3: Preparar o uplink antes da restauração no login, Task 4: Documentar e verificar a correção de rede

### Community 163 - "Inicialização e autenticação — Implementation Plan"
Cohesion: 0.25
Nodes (8): Estrutura de arquivos, Global Constraints, Inicialização e autenticação — Implementation Plan, Investimento e critério de interrupção, Ordem e pontos de decisão, T1 — Integrar as frentes e provar o fluxo Orca, T2 — Piloto real, reboot e retorno, T3 — Aceitar operação e atualizar documentação

### Community 164 - "TestManagedLifecycleCommands"
Cohesion: 0.14
Nodes (6): Achado da revisao final: `systemctl` falhando (hook sem barramento do usuario,…, S1: suspend deve verificar que os containers pararam de fato, e retornar codigo…, B#4: `remove_workspace_units` termina em `daemon-reload` com check=True. Numa…, Mesmo contrato para `FileNotFoundError`: host sem `systemctl` no PATH tambem…, `down` e a saida de emergencia: um runtime.json corrompido que faz…, TestManagedLifecycleCommands

### Community 165 - "TestEntrypointNeverDestroysSharedDirectories"
Cohesion: 0.29
Nodes (3): I6, segunda metade: com `~/.claude` compartilhado, todo `up` apagava e recriava…, O limite fica escrito: `mv` sobre diretorio nao e `renameat2(RENAME_EXCHANGE)`,…, TestEntrypointNeverDestroysSharedDirectories

### Community 166 - "7. Session continuity"
Cohesion: 0.40
Nodes (5): 7.1 Two continuity levels, 7.2 Recovery flow, 7.3 States, 7.4 Terminal, 7. Session continuity

### Community 167 - "Agent Sandbox TUI Implementation Plan"
Cohesion: 0.40
Nodes (3): Agent Sandbox TUI Implementation Plan, Global Constraints, Rollout and rollback

### Community 169 - "test_agent_drivers.py"
Cohesion: 0.08
Nodes (19): Exception, Levantada quando `resume()` e chamado sem a opcao de resume confirmada (por…, ResumeUnsupported, _FakeRun, Exception, Testes dos drivers de provedor de agente (Tarefa 5; auth desde a Tarefa 2). Um…, A construcao do argv (`("agy", "--conversation", id)`) continua no codigo,…, Rama nao nomeada explicitamente no brief, mas alcancavel: --version responde,… (+11 more)

### Community 170 - "TestFinish"
Cohesion: 0.13
Nodes (4): `f`: alvo -> confirmacao com toggles explicitos -> so `y` roda. Os servicos de…, O `notice` some na proxima tecla; a razao fica na linha de status, saneada e…, TestFinish, TestNewWorktree

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

### Community 178 - "FakeDriver"
Cohesion: 0.22
Nodes (5): FakeDriver, Driver falso com a mesma superficie que o manager usa. A descoberta devolve,…, Um Codex real cria o rollout na primeira mensagem, depois da janela do start: a…, Irmaos do mesmo agente e cwd, sem id, vivos OU finais: a janela vai do inicio…, TestLazyDiscovery

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
Cohesion: 0.33
Nodes (6): 1. Three Separate Questions, 2. Where Credentials Live, 3. Logging In, 4. Internal Module Boundaries, Provider Authentication, States

### Community 183 - "TestReadSnapshot"
Cohesion: 0.18
Nodes (7): _Case, §7.4 (spec): o daemon monta o `CheckoutManager` por…, §A: `snapshot.py` e o que o futuro daemon importa; nunca pode arrastar…, Cada caso chama `read_snapshot` direto (sem `TuiController`) e confere o…, TestDefaultCheckoutsLivenessFallback, TestReadSnapshot, TestSnapshotImportsWithoutCurses

### Community 184 - "6.7. Validação pelo Orca BLOQUEADA por defeito do Orca"
Cohesion: 0.67
Nodes (3): 6.7. Validação pelo Orca BLOQUEADA por defeito do Orca, Consequência para o plano, Por que o Orca cria workspaces `legacy`

### Community 185 - ".manager"
Cohesion: 0.11
Nodes (6): O operador integra por fora: `pull` + `merge` manuais., O commit que a confirmacao mostrou e o que o finish exporta., TestCleanupWithoutMerge, TestConfirmedSandboxCommit, TestFinishPreview, TestUnreadableEvidence

### Community 186 - "TestConversationsThePurgeDeletes"
Cohesion: 0.21
Nodes (4): `f` numa linha `missing` chega ao `cleanup()` real., M4: a confirmacao lista as sessoes cuja historia do provedor o purge apaga…, TestConversationsThePurgeDeletes, TestMissingRowFromTheTui

### Community 187 - "13. Test strategy"
Cohesion: 0.50
Nodes (4): 13.1 Interfaces as test surfaces, 13.2 Required cases, 13.3 Verification by stage, 13. Test strategy

### Community 188 - "8. TUI"
Cohesion: 0.50
Nodes (4): 8.1 Technology, 8.2 Main tree, 8.3 First-version actions, 8. TUI

### Community 189 - "build_tree"
Cohesion: 0.09
Nodes (30): _branch_label(), build_tree(), _checkout_text(), CheckoutView, _fold(), Path, StrEnum, cli/asb/interfaces/tui_model.py — a arvore pura da TUI. `build_tree` transforma… (+22 more)

### Community 190 - "Path"
Cohesion: 0.09
Nodes (11): Path, Um provider-session-id invalido nunca vira argv — reusa a validacao de…, Argv exatos. Claude e Codex rodam sem prompts de permissao, como o Orca os…, Sem `sessions_root`, nenhum driver le o diretorio de estado do HOST, mesmo…, O volume de sessao e gravavel pelo agente: um symlink, um FIFO ou uma primeira…, Roda `fn` numa thread daemon com prazo de 5 s. Se ela ficar presa num FIFO,…, TestCodexSessionEvidence, TestHostileSessionVolume (+3 more)

### Community 191 - ".write"
Cohesion: 0.17
Nodes (10): Lifetime, Janela `[start, end]` de uma OUTRA sessao do mesmo agente e cwd sem id do…, _CodexCase, Descoberta do start: so arquivos criados depois do baseline., Descoberta preguicosa: todo arquivo atual, sem baseline., Sem baseline (a sessao comecou ha muito): todo arquivo atual e candidato,…, _subagent_meta(), TestCodexIgnoresSubagentThreads (+2 more)

### Community 192 - ".finish"
Cohesion: 0.16
Nodes (4): FinishCheckout, Pedido de integracao de um worktree em `target_branch`. Limpeza e remocao do…, TestFinishRefusesBeforeMutation, TestInterruptedMutations

### Community 193 - "CodexDriver"
Cohesion: 0.06
Nodes (11): CodexDriver, Script remoto de UMA chamada real: `codex exec --skip-git-repo-check --sandbox…, O Codex guarda o trust do diretorio em `~/.codex/config.toml`, que no sandbox…, Executa o script remoto de verdade contra um wrapper falso `asb-codex` -- prova…, Casos verbatim de tests/unit/test_auth_verify.py que usavam "codex" como…, TestCodexClassifyVerification, TestCodexLoginArgv, TestCodexParseAuthStatus (+3 more)

### Community 194 - ".make"
Cohesion: 0.10
Nodes (11): RuntimeError, Falha ao iniciar ou encerrar um terminal tmux., TerminalError, SessionState, Um refresh (ou resume) concorrente grava `concurrent` entre o `stop` do tmux e…, Tarefa 10: um refresh da TUI nao pode subir a revisao de cada sessao a cada…, Um `starting` pertence a um start em voo noutro processo: nem sonda nem grava.…, TestAttachMatrix (+3 more)

### Community 195 - ".commit_on"
Cohesion: 0.11
Nodes (4): I2: um worktree cujo sandbox nunca existiu (criado com `w`, nunca usado) ou foi…, TestExport, TestMerge, TestWorktreeWithoutSandbox

### Community 196 - "test_session_manager.py"
Cohesion: 0.08
Nodes (12): Nome tmux derivado so de um `SessionId` validado., terminal_name(), _FakeRemoteRun, FakeTerminal, ManagerCase, AgentKind, datetime, Path (+4 more)

### Community 197 - "codex.py"
Cohesion: 0.09
Nodes (22): LaunchCommand, Um comando pronto para execucao externa — nunca executado aqui., _canonical_uuid(), Path, `value` so passa se ja e um UUID na forma canonica (minusculas, com hifens),…, _aware_instant(), datetime, Path (+14 more)

### Community 198 - "TestLazyDiscoveryWithTheRealCodexDriver"
Cohesion: 0.17
Nodes (11): AgentAvailability, Resultado sanitizado de `probe()`. `resume_supported` e o unico valor que o…, Pedido de uma nova sessao. `cwd` e o checkout de EXECUCAO do sandbox…, StartSession, Cenarios da revisao, com o `CodexDriver` e o `SessionStore` reais., A e B no mesmo checkout; A conversa depois do inicio de B, B nunca conversa; A…, `NOW` tem .123456 s; o store guarda segundos inteiros. Um rollout 0,1 s antes…, S7: A ja tem id; dentro de A o usuario roda `/new` e abre outro thread do… (+3 more)

### Community 199 - "test_diagnostic_checks.py"
Cohesion: 0.15
Nodes (6): cli/asb/diagnostics — coleta (checks.py) e apresentacao (report.py) do…, tests/unit/test_diagnostic_checks.py — Tarefa 5, Passo 3: cobertura direta dos…, `healthy` e sempre True (recurso opcional); so a `remediation` muda com a…, TestCheckCliGuard, TestCheckDockerBroker, TestCheckPythonVersion

### Community 200 - ".services"
Cohesion: 0.13
Nodes (10): AttachResult, `argv` interativo que anexa ao terminal da sessao, ou `None` quando nao ha…, _Case, _forbidden(), `list` nao pode tocar workspace nenhum., `manager.attach` retoma nativamente (Tarefa 8): e assim que o CLI honra o…, TestSessionAttach, TestSessionList (+2 more)

### Community 201 - "_Case"
Cohesion: 0.09
Nodes (17): BranchInfo, _checkout(), Path, Le registro, workspaces, Git e sessoes e devolve um `Snapshot`. Nunca levanta…, Branch de `path` pelo `GitRepository` (§C): nunca monta argv de Git na mao.…, read_branch(), read_snapshot(), _with_error() (+9 more)

### Community 202 - "SessionEvidence"
Cohesion: 0.07
Nodes (22): ABC, AgentDriver, _first_line(), _is_real_dir(), _is_regular_file(), datetime, Path, RunFn (+14 more)

### Community 204 - "AntigravityDriver"
Cohesion: 0.05
Nodes (20): _agy_model_row(), _agy_models_output_valid(), AntigravityDriver, Path, Script remoto de UMA chamada real: `agy models`, sem prompt e sem…, `agy models` responde uma LISTA de identificadores, nunca a frase fixa que…, A linha e uma LINHA DE MODELO da lista do agy? O formato real (capturado no…, Continua falhando FECHADO; so reconhece o formato real. A guarda anterior… (+12 more)

### Community 205 - "aggregate_exit_code"
Cohesion: 0.20
Nodes (7): aggregate_exit_code(), Codigo de saida agregado do modo --json, replicando a acumulacao seletiva que…, Codigo agregado do modo --json: replica `infra_healthy` de `diagnose()` (achado…, Achado empirico preexistente (nao corrigido por esta Tarefa): `network_gate`…, Minor 8 (revisao final): as seis checagens web sao infraestrutura opcional,…, R26: um conjunto vazio de checks nunca reporta saudavel — vale so para esta…, TestAggregateExitCode

### Community 206 - "_info"
Cohesion: 0.16
Nodes (5): _info(), `interactive=False`: sem TTY (`-T` no lugar de `-tt`), nunca pede senha…, TestLifecyclePayloadContract, TestSshArgvContract, TestSshArgvNonInteractive

### Community 207 - "FakeRun"
Cohesion: 0.21
Nodes (7): _fail(), FakeRun, _ok(), CompletedProcess, Cada passo interrompe o comando e nomeia a correcao exata (Emenda D)., Substitui `subprocess.run` para `install_server`: nunca invoca uv, node, pnpm…, TestInstallServerPrerequisiteFailures

### Community 208 - "test_tui_acceptance.py"
Cohesion: 0.13
Nodes (19): ClaudeFake, CodexFake, completing_driver(), _git(), _Harmless, _init_repo(), _pane_pids(), Path (+11 more)

### Community 209 - "GitRepository"
Cohesion: 0.07
Nodes (31): _decode(), GitError, GitRepository, GitTimeout, CompletedProcess, Exception, Path, Git de UM caminho. `runner` e injetavel so para simular falhas que um… (+23 more)

### Community 210 - "TestSessionParser"
Cohesion: 0.15
Nodes (5): _load_cli_module(), _nested_choices(), ArgumentParser, TestSessionDispatch, TestSessionParser

### Community 211 - "ClaudeDriver"
Cohesion: 0.07
Nodes (22): ClaudeDriver, _completed(), CompletedProcess, Herdado de TestVerificacaoDeLogin: `--version` responde 0 com o agente…, O contrato exato do comando de login, verbatim do brief da A3., `claude /login` sai com 0 SEM logar (A1): um falso verde que manda o operador…, `--console` seleciona faturamento por API em vez da assinatura., O teste verbatim do brief: rede ruim nunca vira logout. As sete formas do brief… (+14 more)

### Community 212 - "TestTreeSuccess"
Cohesion: 0.15
Nodes (5): Common fixture: a real token, a logged-in client, and a settable…, TestTreeRegistryFailure, TestTreeRequiresSession, TestTreeSuccess, TreeTestCase

### Community 213 - "_Case"
Cohesion: 0.15
Nodes (5): _Case, Path, O laco de prova do caminho sem worktree passa por TODAS as refs., O `store.replace(... COMPLETED)` da TUI, sobre a lista falsa., TestSeveralExportRefs

### Community 214 - "App.tsx"
Cohesion: 0.18
Nodes (11): App(), AppShell(), jumpTo(), TopBar(), TopBarProps, readStored(), useFold(), UseFoldResult (+3 more)

### Community 215 - "4. Revisão após o piloto (2026-09-19)"
Cohesion: 0.13
Nodes (14): 1. Matriz de contratos, 2.1 Codex — raiz de estado, 2.2 Claude — slug do diretório de projeto, 2.3 Antigravity — ausência de estado local, 2.4 Limite desta tarefa, 2. Notas de caracterização, 3. Decisão consolidada, 4.1 Claude — id atribuído no lançamento (+6 more)

### Community 216 - "Baseline pré-decomposição de módulos — 2026-09-17"
Cohesion: 0.15
Nodes (12): 1. Tamanho medido (`wc -lw`), 2.1 `cli/asb/lifecycle.py`, 2.2 `cli/asb/auth.py`, 2.3 `cli/asb/doctor.py`, 2. Superfície de topo, por AST (`ast.parse`, corpo do módulo), 3.1 Consumidores de `lifecycle`, 3.2 Consumidores de `auth`, 3.3 Consumidores de `doctor` (+4 more)

### Community 218 - "test_supervisor_remove_units.py"
Cohesion: 0.21
Nodes (10): clean_env(), env_for(), Path, Unit tests for supervisor.remove_workspace_units., Ambiente minimo: config/drop-in e keyring sinteticos, nada do operador., Aplica `env` e remove seams herdados que mudariam as raizes., R6: um symlink de wants que sobra reabilita o target no proximo boot., R6: manifesto corrompido nunca e silenciado como se estivesse ausente. (+2 more)

### Community 219 - "ListedCheckout"
Cohesion: 0.12
Nodes (8): parse_worktrees(), Parser do formato `--porcelain -z`: campos terminados por NUL, registros…, Um registro de `git worktree list --porcelain -z`. `branch` e o nome curto (sem…, Worktree, ListedCheckout, Um worktree que o Git lista (`worktree`) e o vinculo do registro (`binding`,…, TestWorktreeList, TestWorktreeListing

### Community 220 - "Server Conventions"
Cohesion: 0.13
Nodes (14): 10. Sanitization: broader than "strip control characters", 11. `cli/` cannot import `server/`, 12. Adding a route, 13. Testing with `create_app` and fixtures, 1. The daemon must never import `curses`, 2. `SnapshotService` is built eagerly in `create_app`, 3. `SnapshotService`: worker thread, single-flight, no cache, 4. Secrets: eager fail-fast at start, lazy everywhere else (+6 more)

### Community 221 - "_info"
Cohesion: 0.26
Nodes (5): _info(), Path, O contrato de ponta a ponta: um probe real sobre `remote_run` nunca aborta, so…, TestRemoteRun, TestSessionServices

### Community 222 - "Design: Web interface for agent-sandbox — program and foundation (item 1)"
Cohesion: 0.13
Nodes (15): 10. Testability hooks, 11. Security, 12. Failure handling, 14. Agents and skills, 15. CI, 16. Documentation touched, 17. Acceptance criteria, 18. Risks and follow-ups (+7 more)

### Community 223 - "patch"
Cohesion: 0.24
Nodes (4): patch, TestCheckImageAndVolumes, TestCheckNetnsProducersThirdParty, TestCheckToolDrift

### Community 224 - "TestConnectDispatch"
Cohesion: 0.20
Nodes (4): _load_cli_module(), Guarda contra regressao: adicionar `connect` nao pode remover ou reescrever…, TestConnectDispatch, TestConnectParserRegistration

### Community 225 - "devDependencies"
Cohesion: 0.13
Nodes (15): eslint, @eslint/js, globals, openapi-typescript, typescript, @vitejs/plugin-react, vitest, devDependencies (+7 more)

### Community 226 - "Plan: Web interface foundation (item 1)"
Cohesion: 0.14
Nodes (14): Next steps, Overview, Plan: Web interface foundation (item 1), Task 10: Domain packs and asb-dev-stack skill, Task 11: CI, Playwright e2e, and piloted validation, Task 1: Monorepo skeleton and workspace setup, Task 2: Snapshot extraction from TUI controller, Task 3: Daemon app foundation (FastAPI, settings, models) (+6 more)

### Community 227 - "agent-sandbox"
Cohesion: 0.18
Nodes (11): agent-sandbox, Commands, Configuring a project, Getting started, If something's wrong, Orca integration, Project layout and where to go next, Requirements (+3 more)

### Community 228 - ".load"
Cohesion: 0.25
Nodes (5): _ensure_secret_file(), Path, Returns `(hex secret at path, was it just created)`, creating it (32 random…, Reads or creates both secret files. Raises `InsecureModeError` if either is…, TestTokenFileModeValidation

### Community 229 - "Adendo — 2026-09-07, 22:00–22:50 BRT"
Cohesion: 0.10
Nodes (18): A1. Correção de escopo: a topologia do piloto anterior não era fiel, A2. Achado bloqueante: namespace rootless sem uplink, A3. Antigravity: reclassificado, não era falha de autenticação, A4. Codex: login sob topologia fiel — PASS, A5. Claude: causa confirmada também por inspeção direta, A6. Correção de redação sobre a cobertura dos testes, A7. Situação por fornecedor, com as quatro separações exigidas, A8. Pendências que impedem fechar o gate (+10 more)

### Community 230 - "TestDoctor"
Cohesion: 0.14
Nodes (3): Sem o link o CLI so roda de dentro do checkout, e isso fica mudo., `doctor.py`'s laco de defasagem (Passo 13 de `diagnose()`) monta…, TestDoctor

### Community 231 - "ProjectTree.tsx"
Cohesion: 0.22
Nodes (12): ProjectRowProps, ProjectTree(), handleKeyDown(), ProjectTreeProps, renderRow(), SessionRow(), SessionRowProps, isFoldable() (+4 more)

### Community 233 - "TestServiceState"
Cohesion: 0.22
Nodes (3): `_service_state` tinha ZERO teste direto (achado da rodada final de revisao do…, Sem healthcheck: `podman inspect --format {{.State.Health.Status}}` devolve…, TestServiceState

### Community 234 - "prepare_workspace_harness"
Cohesion: 0.18
Nodes (6): prepare_workspace_harness(), Roda `lifecycle.prepare_workspace` DE VERDADE e devolve o `podman run` do…, I6: a credencial e compartilhada; a transcricao nao. Medido no podman 6.1 antes…, `volume-subpath` NAO cria o caminho de origem (A1): um subpath ausente aborta o…, Guarda do proprio teste acima: uma harness que nao chegasse a emitir o `podman…, TestSessionStateIsolation

### Community 235 - "scripts"
Cohesion: 0.15
Nodes (12): name, private, scripts, build, check:api, dev, gen:api, lint (+4 more)

### Community 236 - "check_web_health"
Cohesion: 0.23
Nodes (11): check_web_health(), default_health_check(), Mesma resolucao que a do daemon web (`port_from_env`, fora de cli/) —…, Uma unica sondagem de `GET /api/health`, stdlib apenas (`urllib`): nenhum…, server_health_url(), server_port(), _find_browser(), _open_url() (+3 more)

### Community 237 - "Web foundation — operator pilot checklist (NOT EXECUTED)"
Cohesion: 0.17
Nodes (11): 0. Prerequisites, 1. `install-server`, the unit, and health across a re-login (spec §17.3), 2. `asb-agent ui` vs. `asb-agent tui` (spec §17.4), 3. Session and origin enforcement (spec §17.5), 4. Concurrent refresh collapses to one read (spec §17.6), 5. Token never leaks (spec §17.7), 6. Guards, recipes and `doctor` unchanged without uv/Node (spec §17.2), 7. CI is green on the branch (spec §17.1) (+3 more)

### Community 238 - "common.sh"
Cohesion: 0.26
Nodes (7): asb_recipe_json(), asb_workspace_id(), common.sh script, create.sh script, destroy.sh script, resume.sh script, suspend.sh script

### Community 239 - "test_auth_verify.py"
Cohesion: 0.12
Nodes (11): Testes de cli/asb/auth.py — verificacao real e orcamento explicito (A4).…, Contexto local minimo; a chamada ao fornecedor continua sintetica., A protecao mais critica desta tarefa: se a chamada em si expirar (o caso mais…, O orcamento e gasto na TENTATIVA, nao no sucesso: nao ha retry escondido so…, Evidencia de sucesso exige resposta no formato solicitado, nao um grep de 'ok'.…, Guarda cross-cutting (orquestracao): cada estado que QUALQUER driver pode…, _SSHInfraCase, TestAgentsBehindProxyExitStatus (+3 more)

### Community 240 - "Acceptance report: Agent Sandbox TUI"
Cohesion: 0.29
Nodes (6): 1. Scope and method, 2. Automated scenarios, 3. Complete automated verification, 4. Human pilot (Task 13 Step 3), 5. Known limitations and deferred items, Acceptance report: Agent Sandbox TUI

### Community 241 - "_run_openapi"
Cohesion: 0.26
Nodes (5): CompletedProcess, Path, server/tests/test_openapi.py — Task 6: `asb-server openapi` byte-stability.…, _run_openapi(), TestOpenapiByteStability

### Community 243 - "Path"
Cohesion: 0.27
Nodes (3): Path, Espec 8.1 + Emenda D: ExecStart, Restart, RestartSec, WantedBy — escapados por…, TestRenderServerUnit

### Community 244 - "asb-seed-claude-state"
Cohesion: 0.60
Nodes (5): main(), Grava ao lado e troca por rename. Sem `replace`, usa link(2), que falha se o…, seed(), warn(), write_atomic()

### Community 245 - "TestLoginKeyringContract"
Cohesion: 0.23
Nodes (5): _ok(), Contrato herdado de `TestLoginKeyringIntegration`, que vivia em `test_auth.py`…, O cliente fala com o Secret Service pelo socket. A passphrase e do singleton;…, `PodmanError` na verificacao nao escapa mais do laco (I5): vira resultado…, TestLoginKeyringContract

### Community 246 - "test_uv_workspace.py"
Cohesion: 0.17
Nodes (6): tests/unit/test_uv_workspace.py — esqueleto do workspace uv (Tarefa 1). Nome…, `asb` nunca importa `asb_server` nem sabe que o daemon existe., cli/asb-agent roda direto do checkout: sem venv, sem PYTHONPATH., TestAsbAgentRunsWithoutVenv, TestImportAsb, TestNoImportCycle

### Community 248 - "e2e.spec.ts"
Cohesion: 0.20
Nodes (9): ASB_SERVER_BIN, Daemon, __dirname, FAILURE_FIXTURE, freePort(), HEALTHY_FIXTURE, REPO_ROOT, startDaemon() (+1 more)

### Community 249 - "IsolationError"
Cohesion: 0.12
Nodes (13): IsolationError, Exception, tests/integration/sandbox_fixture.py — isolated test fixture for systemd…, Raised when an operation attempts to access or mutate resources outside…, (is-enabled, is-active) da unit no manager, independente de arquivo local., Para e desabilita (persistente e runtime) consultando o estado antes de cada…, Nenhum processo supervisionado ficou para tras. Padrao: o container…, tests/integration/test_credential_writers.py — Empirical tests for credential… (+5 more)

### Community 250 - "GitResult"
Cohesion: 0.25
Nodes (5): GitResult, _printable(), A causa de uma falha: as linhas `fatal:`/`error:` do stderr primeiro, depois…, Rodada 1: o motivo de uma falha e a causa, nunca o progresso., TestFailureReason

### Community 251 - "test_doctor.py"
Cohesion: 0.25
Nodes (5): _load_cli_module(), Testes de cli/asb/doctor.py e pull/purge em cli/asb/lifecycle.py., Roda `pull("test-ws")` (ou `main`) com o Git simulado: `head` e a saida de…, O branch vem do checkout que o agente escreve: um HEAD destacado, uma opcao…, TestPull

### Community 252 - "TestNoDuplicateProbing"
Cohesion: 0.40
Nodes (3): Passo 4: cada sonda cara roda exatamente uma vez por `doctor()`., Roda nos DOIS modos: o probe duplicado que esta Tarefa removeu…, TestNoDuplicateProbing

### Community 257 - "TestUiBrowserSelection"
Cohesion: 0.18
Nodes (3): A Tarefa 7 pede que `--print-url` funcione sem daemon de pe: nem uma chamada de…, A URL impressa carrega o token SO depois de `#`; nunca antes, nunca numa query…, TestUiBrowserSelection

### Community 258 - "test_workspace_supervision.py"
Cohesion: 0.33
Nodes (4): tests/integration/test_workspace_supervision.py — Integration tests for managed…, End-to-end integration tests for systemd-managed workspace lifecycle., Proves complete managed lifecycle: up -> SSH -> sentinel -> suspend -> resume…, TestWorkspaceSupervision

### Community 261 - "/graphify"
Cohesion: 0.20
Nodes (9): For /graphify add and --watch, For /graphify query, For the commit hook and native AGENTS.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Usage (+1 more)

### Community 262 - "CommandPalette.tsx"
Cohesion: 0.27
Nodes (9): CommandPalette(), activate(), handleKeyDown(), CommandPaletteProps, Entry, JumpableRow, rowLabel(), DetailPanelProps (+1 more)

### Community 267 - "CLAUDE.md"
Cohesion: 0.22
Nodes (4): Available Subagents (`.claude/agents/`), Claude Code Configuration, Knowledge Graph (`graphify-out/`), Skills (`.claude/skills/`)

### Community 268 - "Web Domain Pack"
Cohesion: 0.22
Nodes (9): 1. What it is, 2. Stack, 3. Screen, 4. File layout, 5. Server state: TanStack Query, no cache beyond the query itself, 6. The command-palette principle, 7. Testing, Documentation Index (+1 more)

### Community 269 - "dependencies"
Cohesion: 0.22
Nodes (9): openapi-fetch, react, react-dom, @tanstack/react-query, dependencies, openapi-fetch, react, react-dom (+1 more)

### Community 270 - "Web Conventions"
Cohesion: 0.25
Nodes (7): 1. The label vocabulary is copied, not shared, with the TUI, 2. Row ordering is a front-end responsibility, 3. Sorting uses raw comparisons, not `localeCompare`, 4. Server state: `useTree` never intercepts errors, 5. The command-palette principle and reserved keys, 6. Testing with Testing Library and the fixture daemon, Web Conventions

### Community 271 - "test_session_lifecycle.py"
Cohesion: 0.36
Nodes (6): _attach_in_pty(), _git(), Path, tests/integration/test_session_lifecycle.py — sessao persistente real (Tarefa…, `execute` do `session attach` para teste: roda o argv num pty 80x24, espera…, TestSessionLifecycle

### Community 273 - "7. The daemon (`asb_server`)"
Cohesion: 0.29
Nodes (7): 7.1 Package layout, 7.2 API (item 1), 7.3 Contract (`models.py`), 7.4 Reading is slow and never blocks the loop, 7.5 Authentication, 7.6 Errors, 7. The daemon (`asb_server`)

### Community 275 - "TestInstallServerHappyPath"
Cohesion: 0.29
Nodes (3): InstallServerTestBase, A sonda de saude nunca bloqueia a instalacao: enable --now ja rodou; a unidade…, TestInstallServerHappyPath

### Community 276 - "7. Graphify"
Cohesion: 0.33
Nodes (6): 1. Fast Path Querying, 2. Semantic Update Timing, 3. Rebuild Pause During Plan Execution, 4. Two-Commit Workflow, 5. Linked Worktrees & Environment Setup, 7. Graphify

### Community 277 - "4. Agent Workflow & Operational Rules"
Cohesion: 0.33
Nodes (6): 1. Specification Before Implementation (Spec-Driven), 2. Context Hygiene & Progressive Disclosure, 3. Least Privilege & Role Separation, 4. Agent Workflow & Operational Rules, 4. Verification Before Assertions, 5. Human Gatekeeper

### Community 278 - "Server Domain Pack"
Cohesion: 0.33
Nodes (6): 1. What the daemon is, 2. Where it runs and how it's reached, 3. Package layout, 4. The API, Documentation Index, Server Domain Pack

### Community 279 - "9. The front end (`web/`)"
Cohesion: 0.33
Nodes (6): 9.1 Stack, 9.2 Screen, 9.3 Keyboard, 9.4 Components, 9.5 Development loop, 9. The front end (`web/`)

### Community 280 - "TestCredentialWritersFilesystem"
Cohesion: 0.33
Nodes (4): Filesystem-level tests for atomic replacement, symlinks, and O_NOFOLLOW., Proves atomic replace() replaces the symlink itself, leaving the stored target…, Proves opening a symlink with O_NOFOLLOW raises ELOOP (Errno 40) on Linux. This…, TestCredentialWritersFilesystem

### Community 281 - "test_install_server.py"
Cohesion: 0.40
Nodes (3): DoctorWebChecksTestBase, tests/unit/test_install_server.py — Tarefa 7 (`install-server`, `ui`,…, TestDoctorWebChecksNeverInstalled

### Community 282 - "schema.d.ts"
Cohesion: 0.33
Nodes (5): components, $defs, operations, paths, webhooks

### Community 283 - "Skill: asb-dev-stack"
Cohesion: 0.40
Nodes (5): After editing this skill, Canonical Instructions, Dev loop, Full check sequence (what CI runs), Skill: asb-dev-stack

### Community 284 - "Skill: asb-dev-stack"
Cohesion: 0.40
Nodes (5): After editing this skill, Canonical Instructions, Dev loop, Full check sequence (what CI runs), Skill: asb-dev-stack

### Community 285 - "Skill: asb-dev-stack"
Cohesion: 0.40
Nodes (5): After editing this skill, Canonical Instructions, Dev loop, Full check sequence (what CI runs), Skill: asb-dev-stack

### Community 286 - "Claim Verification"
Cohesion: 0.40
Nodes (5): Calibration, Claim Verification, Method, The Question, Worked Example

### Community 287 - "Test Shape"
Cohesion: 0.40
Nodes (5): Adjacent Checks, Test Shape, The Question, What to Report, Why: three defects that passed review

### Community 289 - ".test_evidence_never_carries_captured_provider_output"
Cohesion: 0.40
Nodes (3): `auth.py` monta evidencia com texto enlatado mais um codigo de retorno. O login…, Capturar a saida do login a traria para dentro do processo, de onde ela pode…, TestLoginNeverLeaksCredentials

### Community 290 - "13. Test strategy"
Cohesion: 0.50
Nodes (4): 13.1 Python, 13.2 Web, 13.3 Not automated, 13. Test strategy

### Community 291 - "8. Installation, unit, `ui`, `doctor`"
Cohesion: 0.50
Nodes (4): 8.1 `asb-agent install-server`, 8.2 `asb-agent ui`, 8.3 `doctor`, 8. Installation, unit, `ui`, `doctor`

### Community 292 - "Google Antigravity & Gemini CLI Configuration"
Cohesion: 0.50
Nodes (4): Available Subagents (`.agents/agents/`), Google Antigravity & Gemini CLI Configuration, Knowledge Graph (`graphify-out/`), Skills (`.agents/skills/`)

### Community 296 - "TestLoginPreservesResultsAcrossFailures"
Cohesion: 0.50
Nodes (3): I5: erro de infraestrutura de UM fornecedor nao apaga o resultado ja…, A evidencia continua sendo texto enlatado: o erro do podman nao e saida…, TestLoginPreservesResultsAcrossFailures

## Knowledge Gaps
- **890 isolated node(s):** `entrypoint.sh script`, `start-keyring.sh script`, `DBUS_SESSION_BUS_ADDRESS`, `common.sh script`, `shim.template.sh script` (+885 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **58 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `SandboxFixture` connect `SandboxFixture` to `interfaces/snapshot.py`, `test_workspace_supervision.py`, `IsolationError`, `Pilot`, `get_test_image`, `test_sandbox_fixture_guard.py`, `test_session_lifecycle.py`, `TestSupervisorPilot`, `TestForwarderIntegration`, `test_provider_auth.py`, `test_tui_acceptance.py`, `ProbeResult`, `TestTeardownCommandClasses`, `.teardown`, `integration/test_network_gate.py`, `test_entrypoint_concurrency.py`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Why does `GitRepository` connect `GitRepository` to `interfaces/snapshot.py`, `CheckoutId`, `CheckoutManager`, `_Case`, `.request`, `lifecycle.py`, `_Case`, `git`, `ListedCheckout`?**
  _High betweenness centrality (0.026) - this node is a cross-community bridge._
- **Why does `CodexDriver` connect `CodexDriver` to `Pilot`, `codex.py`, `TestLazyDiscoveryWithTheRealCodexDriver`, `test_agent_drivers.py`, `SessionEvidence`, `sessions.py`, `.terminal`, `asb/auth.py`, `_info`, `Path`, `.write`?**
  _High betweenness centrality (0.026) - this node is a cross-community bridge._
- **Are the 18 inferred relationships involving `SandboxFixture` (e.g. with `TestBindMountAtomicReplace` and `TestContainerPermissionsAndPaths`) actually correct?**
  _`SandboxFixture` has 18 INFERRED edges - model-reasoned connections that need verification._
- **Are the 31 inferred relationships involving `CodexDriver` (e.g. with `AuthResult` and `LaunchCommand`) actually correct?**
  _`CodexDriver` has 31 INFERRED edges - model-reasoned connections that need verification._
- **Are the 27 inferred relationships involving `CheckoutId` (e.g. with `CheckoutManager` and `CheckoutBinding`) actually correct?**
  _`CheckoutId` has 27 INFERRED edges - model-reasoned connections that need verification._
- **Are the 17 inferred relationships involving `ClaudeDriver` (e.g. with `AuthResult` and `LaunchCommand`) actually correct?**
  _`ClaudeDriver` has 17 INFERRED edges - model-reasoned connections that need verification._