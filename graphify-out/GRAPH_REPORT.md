# Graph Report - agent-sandbox  (2026-09-17)

## Corpus Check
- 159 files · ~209,516 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2555 nodes · 3956 edges · 186 communities (147 shown, 39 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 127 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `859665a1`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- run
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
- ProjectDetectionTest
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
- lifecycle.py
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
- classify_verification
- Global Constraints
- discover_mise_dirs
- 2. Explicit Declarations: What Is NOT Protected
- Orca Reboot Persistence Implementation Plan
- Design: persistência profissional do sandbox no Orca
- exists
- Skill: Agent Authoring
- Skill: Commit Curator
- Skill: Agent Authoring
- Skill: Commit Curator
- Skill: Agent Authoring
- Skill: Commit Curator
- AuthResult
- patch
- install.py
- Redesenho de inicialização e autenticação
- Claude Code Configuration
- Google Antigravity & Gemini CLI Configuration
- TestForwarderProcessLifecycle
- Contratos de Autenticação por Fornecedor e Protocolo de Validação
- test_credential_writers.py
- collect_boot_evidence.py
- TestSupervisorPilot
- 3. Resultados dos Ensaios Empíricos
- TestForwarderIntegration
- ensure_session_volume
- IsolationError
- Secret Service singleton para credenciais dos agentes
- integration/__init__.py
- SandboxFixture
- TestCliParserDispatchParity
- TestTeardownCommandClasses
- Path
- Adendo — 2026-09-07, 22:00–22:50 BRT
- TestCliExitCodes
- auth.py
- test_cli_dispatch.py
- test_entrypoint_concurrency.py
- TestNetworkGateUnits
- 7. Graphify
- 4. Agent Workflow & Operational Rules
- suspend
- TestToolDrift
- TestSingleRuntimeResume
- TestRevisionFallbackIsPerCheckout
- Known Regressions — Sandbox Domain
- forwarder.sh
- ProbeResult
- test_lifecycle.py
- TestManagedLifecycleCommands
- Test Shape
- unit/test_network_gate.py
- test_sandbox_fixture_guard.py
- Claim Verification
- TestClassifyVerification
- TestCredentialDirectoryMounts
- test_provider_auth.py
- TestLifecycleLoginReexport
- claim-verifier/agent.md
- regression-sentinel/agent.md
- test-shape-auditor/agent.md
- readiness.py
- _ok
- Global Constraints
- probe_ssh
- supervisor.py
- TestAggregateExitCodeDeniesByDefault
- TestAllowlistBaseCobreOsAgentes
- TestProbeSshIdentityAtCallSites
- Emenda A — runtime único systemd e espera única por rede
- asb_test_isolation.py
- render
- test_supervisor_remove_units.py
- Piloto real de inicialização e autenticação — T2
- 6.2. Boot 1 — REPROVADO, e o teste estava contaminado
- TestLoginKeyringContract
- test_auth_verify.py
- TestVerifyCommand
- TestLoginCommandTable
- TestAgyRealModelListFormat
- _healthy_probe
- TestVerifyClientCallBudget
- TestVerifyClientCommands
- TestUnitSuiteIsolation
- TestLegacyCredentialLayoutWarning
- TestEntrypointCredentialLayout
- normalize_domains
- TestLiveAuthDoubleOptIn
- TestDoctor
- TestVerifyFreshClient
- _SSHInfraCase
- test_doctor.py
- Recuperação do uplink rootless do Podman
- 5. Estado de autenticação medido
- TestEmendaAChecks
- TestSingleRuntimeCli
- prepare_workspace
- TestPurgeAfterDown
- Supervisão da inicialização — Implementation Plan
- asb/__init__.py
- TestKeyringRole
- TestVerifyClientAgy
- network_gate.py
- wait_until
- Workspace Lifecycle & Supervision
- Inicialização e autenticação — Implementation Plan
- TestCheckWorkspaceEgress
- TestEntrypointNeverDestroysSharedDirectories
- TestHostPortsProbe
- Profile
- TestSingleRuntimeUp
- .is_container_running
- LoginBusy
- Autenticação por fornecedor — Implementation Plan
- 6.4. Boot 2 — APROVADO sem comando corretivo
- 6.6. Boot 3 — configuração real: REPROVADO, e com falha silenciosa
- 6.3. Boot 2 preparado — teste discriminante com o drop-in desativado
- 6.8. Troca para o runtime único (Emenda A, Task 13)
- 8. Fases pendentes e janelas
- TestDownKeepsWorkspaceData
- test_keyring_readiness.py
- 6.11. Boot A3 (um ativo, outro suspenso, runtime único): APROVADO
- 6.5. Orca: excluído e depois REINTEGRADO por decisão do operador
- 6.9. Boot A1 (normal, runtime único): APROVADO, com um defeito de partida
- Provider Authentication
- TestPurge
- 6.7. Validação pelo Orca BLOQUEADA por defeito do Orca
- git/README.md

## God Nodes (most connected - your core abstractions)
1. `SandboxFixture` - 93 edges
2. `load_profile()` - 38 edges
3. `ProbeResult` - 36 edges
4. `AuthResult` - 34 edges
5. `Profile` - 34 edges
6. `run()` - 31 edges
7. `prepare_workspace()` - 30 edges
8. `PodmanError` - 30 edges
9. `Layout` - 29 edges
10. `build_staging()` - 27 edges

## Surprising Connections (you probably didn't know these)
- `TestVerifyCommand` --uses--> `AuthResult`  [INFERRED]
  tests/unit/test_auth_verify.py → cli/asb/auth.py
- `TestAggregateExitCodeDeniesByDefault` --uses--> `AuthResult`  [INFERRED]
  tests/unit/test_login_flow.py → cli/asb/auth.py
- `TestLoginKeyringContract` --uses--> `AuthResult`  [INFERRED]
  tests/unit/test_login_flow.py → cli/asb/auth.py
- `TestVerifyFreshClient` --uses--> `AuthResult`  [INFERRED]
  tests/unit/test_login_flow.py → cli/asb/auth.py
- `TestDoctorServiceBlockNeverSwallows` --uses--> `PodmanError`  [INFERRED]
  tests/unit/test_doctor.py → cli/asb/podman.py

## Import Cycles
- None detected.

## Communities (186 total, 39 thin omitted)

### Community 0 - "run"
Cohesion: 0.12
Nodes (16): _inspect_keyring_container(), Retorna o schema e os mounts reais do singleton, indexados por destino., _volume_mountpoint(), json_out(), out(), PodmanError, Any, CompletedProcess (+8 more)

### Community 1 - "layout_for"
Cohesion: 0.10
Nodes (23): _git(), layout_for(), prepare_clone(), Exception, Path, cli/asb/workspace.py — identidade do workspace, layout em disco e clone. Duas…, Identidade do workspace, sempre reproduzivel a partir das entradas. O Orca…, Onde tudo mora. `home` e o mesmo caminho no host e no container (D4). (+15 more)

### Community 2 - "assert.sh"
Cohesion: 0.06
Nodes (38): assert_contains(), assert_eq(), assert_fails(), assert_not_contains(), report(), require(), assert.sh script, wait_for() (+30 more)

### Community 3 - "load_profile"
Cohesion: 0.10
Nodes (24): _choice(), load_profile(), _ports(), ProfileError, _publish_ports(), Exception, Path, cli/asb/profile.py — le .agent-sandbox.toml e devolve um perfil validado. O… (+16 more)

### Community 4 - "build_staging"
Cohesion: 0.07
Nodes (38): _allowed_destination_roots(), _allowed_symlink_roots(), build_staging(), copy_file(), denied(), filter_claude_settings(), filter_codex_config(), _key() (+30 more)

### Community 5 - "Pilot"
Cohesion: 0.06
Nodes (18): AssertionError, Pilot, pilot_cli(), CompletedProcess, Path, Process-local seams; host HOME and Podman storage stay unchanged., Connect I1 resource ownership to lifecycle names and on-disk state., Defensive unit contract for WorkspaceTransaction(is_existing=True). Production… (+10 more)

### Community 7 - "permitted"
Cohesion: 0.10
Nodes (11): Handler, main(), permitted(), relay(), Server, Testa cli/asb/install.py broker()., Testa a função permitted(method, target) do broker., Testa a rejeição no nível de protocolo HTTP no Handler. (+3 more)

### Community 8 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 9 - "AGENTS.md"
Cohesion: 0.19
Nodes (3): Role, Available Domain Packs, Domain Packs

### Community 10 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native AGENTS.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 12 - "common.sh"
Cohesion: 0.14
Nodes (10): entrypoint.sh script, DBUS_SESSION_BUS_ADDRESS, start-keyring.sh script, asb_recipe_json(), asb_workspace_id(), common.sh script, create.sh script, destroy.sh script (+2 more)

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

### Community 24 - "lifecycle.py"
Cohesion: 0.09
Nodes (43): build(), _current_revision(), down(), emit(), ensure_runtime(), ensure_ssh_key(), list_workspaces(), login() (+35 more)

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
Cohesion: 0.04
Nodes (7): Testes de cli/asb/auth.py — separacao de status de conta, rede e…, Exemplos verbatim do brief da tarefa A2., TestAuthResult, TestCheckStatus, TestParseClaudeStatus, TestParseCodexStatus, TestStatusCommand

### Community 48 - "doctor.py"
Cohesion: 0.09
Nodes (29): ArgumentParser, build_parser(), main(), check_legacy_agent_container(), check_network_gate(), check_project_dropin_absent(), check_workspace_egress(), diagnose() (+21 more)

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
Nodes (13): 1. Schema Reference, 2. Toolchain Provisioning & Shared Cache (`asb-toolcache`), 3. Agent Context Tools (`rtk`, `graphify`), 3. Worked Examples, Changes from v1 Schema, Configuration Reference (`.agent-sandbox.toml`), Example 1: `hexmed` (Host Services & Filtered Docker Inspection), Example 2: `BlackICE` (Nested Container Runtime) (+5 more)

### Community 53 - "Sandbox Domain Pack"
Cohesion: 0.25
Nodes (8): 1. System Topology, 2. CLI Commands, 3. Where Files Live, 4. What to Do on Failure, Container Roles, Documentation Index, Filesystem Layout, Sandbox Domain Pack

### Community 54 - "Integração project-scoped do Graphify no agent-sandbox"
Cohesion: 0.18
Nodes (10): 1. Objetivo e Contexto, 2.1 Baseline e Tooling Local, 2.2 Adaptador de Domínio (`.graphify/project.py`), 2.3 Governança de Agentes e SSoT, 2.4 Integração de Skills e Git, 2. Decisões Arquiteturais, 3. Arquitetura de Arquivos, 4. Estratégia de Testes e Validação (+2 more)

### Community 55 - "Git Commit Conventions"
Cohesion: 0.25
Nodes (8): 1. Authority and Branching Rules, 2. Safe Scope Selection (Surgical Changes), 3. Prerequisites & Empirical Verification, 4. Commit Message Format, 5. Attribution, Commit Body (Mandatory), Git Commit Conventions, Gitmoji Selection

### Community 56 - "classify_verification"
Cohesion: 0.25
Nodes (8): _agy_model_row(), _agy_models_output_valid(), classify_verification(), _contains_code(), Casa um CODIGO NUMERICO delimitado (nao digito antes nem depois). R4 do…, A linha e uma LINHA DE MODELO da lista do agy? O formato real (capturado no…, Continua falhando FECHADO; so reconhece o formato real. A guarda anterior…, Classifica o RESULTADO de uma chamada real (ou a decisao de nao faze-la). Pura:…

### Community 57 - "Global Constraints"
Cohesion: 0.22
Nodes (8): Global Constraints, Graphify Project Integration Implementation Plan, Plan Self-Review, Task 1: Setup script, ignore rules, and gitattributes, Task 2: Custom domain adapter and automated unit tests, Task 3: Install project-scoped skills and verify synchronization, Task 4: Agent governance, documentation, and commit conventions, Task 5: Generate initial knowledge graph and verify query acceptance

### Community 58 - "discover_mise_dirs"
Cohesion: 0.39
Nodes (3): discover_mise_dirs(), Encontra todos os diretorios que contem mise.toml, podando pastas irrelevantes., TestDiscoverMiseDirs

### Community 59 - "2. Explicit Declarations: What Is NOT Protected"
Cohesion: 0.17
Nodes (12): 1. Non-Negotiable Invariants, 2. Explicit Declarations: What Is NOT Protected, 3. Network & DNS Boundary, 4. Credential Isolation & The Singleton Secret Service, DNS Tunneling Prevention, Exfiltration to an allowed domain is possible, `host_api = "read"` grants passwordless Docker reading to uid 1000, `mode = "nested"` gives the agent a full container runtime inside the boundary (+4 more)

### Community 60 - "Orca Reboot Persistence Implementation Plan"
Cohesion: 0.29
Nodes (6): Orca Reboot Persistence Implementation Plan, Task 1: readiness de rede e proxy, Task 2: criação transacional e imagem autenticada obrigatória, Task 3: estado completo do Antigravity, Task 4: autenticação verificável e diagnóstico, Task 5: integração Orca e documentação

### Community 61 - "Design: persistência profissional do sandbox no Orca"
Cohesion: 0.33
Nodes (5): Critérios de aceitação, Decisões, Design: persistência profissional do sandbox no Orca, Limites deliberados, Problema confirmado

### Community 62 - "exists"
Cohesion: 0.15
Nodes (19): check_keyring_service(), ensure_keyring_data_volume(), ensure_keyring_pass(), ensure_keyring_runtime_volume(), ensure_keyring_service(), _keyring_mount_contract_issue(), Path, cli/asb/keyring.py — singleton de Secret Service (asb-keyring). Extraido de… (+11 more)

### Community 69 - "AuthResult"
Cohesion: 0.07
Nodes (23): AuthResult, login_harness(), _ok(), Testes do fluxo de login seletivo, persistencia e fixacao de versoes (A3).…, I5: erro de infraestrutura de UM fornecedor nao apaga o resultado ja…, A evidencia continua sendo texto enlatado: o erro do podman nao e saida…, Caso do brief: o login interativo termina bem, mas o cliente NOVO diz deslogado…, A4 ainda nao esta integrado: sem `verify_client`, o resultado do agy e… (+15 more)

### Community 70 - "patch"
Cohesion: 0.21
Nodes (8): probe_host(), probe_proxy(), Checa CONNECT através do proxy até o destino declarado., Checa rota, TCP e TLS do host até o destino de controle declarado., patch, M1: o casamento de status virou substring nua ("403" in output), e a saida…, TestProbeHost, TestProbeProxy

### Community 71 - "install.py"
Cohesion: 0.12
Nodes (28): broker(), check_project_dropin(), get_dropin_path(), guards(), install_runtime(), _is_project_dropin(), _link(), _manifest_of() (+20 more)

### Community 72 - "Redesenho de inicialização e autenticação"
Cohesion: 0.14
Nodes (14): 1. Objetivo e limites, 2. Evidência e incertezas, 3. Alternativas e decisão proposta, 4. Contratos globais, 5.1 Sondas e limites, 5.2 Forwarder e criação transacional, 5. Inicialização: responsabilidades e estado, 6.1 Persistência e concorrência: gate obrigatório (+6 more)

### Community 73 - "Claude Code Configuration"
Cohesion: 0.50
Nodes (4): Available Subagents (`.claude/agents/`), Claude Code Configuration, Knowledge Graph (`graphify-out/`), Skills (`.claude/skills/`)

### Community 74 - "Google Antigravity & Gemini CLI Configuration"
Cohesion: 0.50
Nodes (4): Available Subagents (`.agents/agents/`), Google Antigravity & Gemini CLI Configuration, Knowledge Graph (`graphify-out/`), Skills (`.agents/skills/`)

### Community 75 - "TestForwarderProcessLifecycle"
Cohesion: 0.14
Nodes (6): Popen, tests/unit/test_forwarder_script.py — Unit tests for image/forwarder.sh…, Tests input validation of image/forwarder.sh., Tests process supervision semantics: fail-fast on child death and SIGTERM…, TestForwarderProcessLifecycle, TestForwarderScriptValidation

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
Cohesion: 0.11
Nodes (10): tests/integration/test_supervisor_pilot.py — Empirical supervision pilot test.…, Proves runtime launcher helper seamlessly attaches to an already running…, Proves literal unit behavior: podman start --attach on running container…, Proves SandboxFixture refuses foreign resources, production names, and external…, Proves readiness probes distinguish proxy inaccessible from CONNECT denied and…, Empirical integration test suite for systemd rootless supervision., Proves systemd Type=exec restarts container on failure, preserving identity and…, Proves systemd Restart=always restarts container even when exiting cleanly… (+2 more)

### Community 80 - "3. Resultados dos Ensaios Empíricos"
Cohesion: 0.15
Nodes (12): 1. Objetivo e Escopo, 2. Artefatos Desenvolvidos, 3.1. Recuperação após Falha e Preservação de Identidade, 3.2. Saída Limpa Inesperada (Código 0), 3.3. Falha em `ExecStartPost` e Limpeza por `ExecStopPost`, 3.4. Reconexão a Container em Execução, 3.5. Proteção de Isolamento, 3. Resultados dos Ensaios Empíricos (+4 more)

### Community 81 - "TestForwarderIntegration"
Cohesion: 0.12
Nodes (9): tests/integration/test_forwarder.py — Integration tests for port forwarder…, Proves initial bind errors or invalid port arguments fail immediately., Empirical integration tests for asb-forwarder and unprivileged low ports., Proves undeclared ports remain closed and forwarder is not a general proxy., Proves killing one listener causes forwarder failure, supervisor restart, and…, Proves the proxy image explicitly contains bash and the forwarder executable., Proves the old un-supervised script masks child process failure., Proves forwarder handles SIGTERM cleanly and exits status 0. (+1 more)

### Community 82 - "ensure_session_volume"
Cohesion: 0.25
Nodes (8): credential_mount_args(), ensure_credential_dirs(), ensure_session_volume(), _mkdir_private(), Cria, no host, um diretorio por fornecedor dentro do volume. Pelo host porque…, `mkdir -m 700` de cada subpath, com erro TRADUZIDO. Um volume cujo `_data`…, Argumentos de mount das credenciais, para o agente e para os clientes efemeros…, Volume de estado de sessao DESTE workspace. Um por workspace, sempre. Separado…

### Community 83 - "IsolationError"
Cohesion: 0.12
Nodes (13): BaseException, IsolationError, Exception, Raised when an operation attempts to access or mutate resources outside…, (is-enabled, is-active) da unit no manager, independente de arquivo local., Para e desabilita (persistente e runtime) consultando o estado antes de cada…, Nenhum processo supervisionado ficou para tras. Padrao: o container…, Remove todo recurso registrado e PROVA a ausencia; qualquer falha levanta… (+5 more)

### Community 84 - "Secret Service singleton para credenciais dos agentes"
Cohesion: 0.22
Nodes (9): Ciclo de vida, Compatibilidade e migração, Contexto, Critérios de aceitação, Decisão de arquitetura, Fora de escopo, Objetivo, Secret Service singleton para credenciais dos agentes (+1 more)

### Community 86 - "SandboxFixture"
Cohesion: 0.06
Nodes (19): Sets up dedicated isolated paths, keys, launcher, and volumes., Creates the synthetic persistent container., Renders the systemd unit content for the pilot., Installs and reloads the unit in user systemd., Isolated sandbox fixture context manager for integration tests., Stops the supervised systemd unit., Simulates container failure by sending SIGKILL., Stops container cleanly (exit 0) to test unexpected zero-exit. (+11 more)

### Community 87 - "TestCliParserDispatchParity"
Cohesion: 0.29
Nodes (3): `lifecycle.login(ROOT)` nao recebe workspace: registrar `login` via o helper…, Guarda do proprio teste: uma varredura que nao achasse nada passaria vazia nos…, TestCliParserDispatchParity

### Community 88 - "TestTeardownCommandClasses"
Cohesion: 0.09
Nodes (7): _FixtureCase, `down` remove o arquivo, mas o manager guarda o service 'failed' (is-active…, Exaustao do laco de `_quiesce_unit`: rc=0 em todo `stop`, estado imovel. O laco…, `sentinel_exists` so traduz rc 0/1; qualquer outro e falha de consulta.…, Falha do `podman ps` na propria rede de seguranca nao pode passar por 'nada…, TestAssertNoOrphans, TestTeardownCommandClasses

### Community 89 - "Path"
Cohesion: 0.17
Nodes (6): CompletedProcess, Path, Runs a command inside a container via podman exec. `container` defaults to the…, Sobe (ou reaproveita) um cliente PROPRIO da fixture, montando SOMENTE as…, Executes the ASB CLI within the isolated environment., Onde units registradas podem morar: runtime do manager e config do usuario.

### Community 90 - "Adendo — 2026-09-07, 22:00–22:50 BRT"
Cohesion: 0.10
Nodes (18): A1. Correção de escopo: a topologia do piloto anterior não era fiel, A2. Achado bloqueante: namespace rootless sem uplink, A3. Antigravity: reclassificado, não era falha de autenticação, A4. Codex: login sob topologia fiel — PASS, A5. Claude: causa confirmada também por inspeção direta, A6. Correção de redação sobre a cobertura dos testes, A7. Situação por fornecedor, com as quatro separações exigidas, A8. Pendências que impedem fechar o gate (+10 more)

### Community 91 - "TestCliExitCodes"
Cohesion: 0.43
Nodes (3): I5: `PodmanError` e INFRAESTRUTURA, e infraestrutura vale 2. O CLI inteiro usa…, Guarda do proprio teste: um `main()` que sempre devolvesse 2 passaria no…, TestCliExitCodes

### Community 92 - "auth.py"
Cohesion: 0.09
Nodes (40): _aggregate_exit_code(), call_budget(), check_status(), _client_name(), _client_run_args(), _lock_path(), login(), login_command() (+32 more)

### Community 93 - "test_cli_dispatch.py"
Cohesion: 0.24
Nodes (7): _dispatched_commands(), _load_cli_module(), ArgumentParser, Unit tests for cli/asb-agent — paridade entre parser e despacho. B#1: a Tarefa…, Carrega cli/asb-agent, que nao tem sufixo .py e por isso escapa do import…, Coleta os literais comparados contra `args.command`. Restrito ao atributo…, _registered_commands()

### Community 94 - "test_entrypoint_concurrency.py"
Cohesion: 0.25
Nodes (4): Starts the supervised systemd unit., skipUnless, tests/integration/test_entrypoint_concurrency.py — agentes que partem juntos.…, TestEntrypointConcurrentStart

### Community 95 - "TestNetworkGateUnits"
Cohesion: 0.06
Nodes (9): Unit tests for cli/asb/supervisor.py — systemd supervision and unit generation., I1: `remove_workspace_units` removia unidades por glob `asb-{ws}-*.service`,…, Sem manifesto legivel, nao ha como saber quais nomes de servico pertencem a…, Emenda A §3/§4: toda unidade de container espera a conectividade real., Emenda A §5: o keyring e uma unidade systemd com sonda de prontidao., TestContainerUnitAndRender, TestKeyringUnit, TestNetworkGateUnits (+1 more)

### Community 96 - "7. Graphify"
Cohesion: 0.33
Nodes (6): 1. Fast Path Querying, 2. Semantic Update Timing, 3. Rebuild Pause During Plan Execution, 4. Two-Commit Workflow, 5. Linked Worktrees & Environment Setup, 7. Graphify

### Community 97 - "4. Agent Workflow & Operational Rules"
Cohesion: 0.33
Nodes (6): 1. Specification Before Implementation (Spec-Driven), 2. Context Hygiene & Progressive Disclosure, 3. Least Privilege & Role Separation, 4. Agent Workflow & Operational Rules, 4. Verification Before Assertions, 5. Human Gatekeeper

### Community 98 - "suspend"
Cohesion: 0.33
Nodes (3): Para o workspace: desabilita e para o target systemd e verifica que todos os…, suspend(), TestKeyringPreservation

### Community 100 - "TestSingleRuntimeResume"
Cohesion: 0.36
Nodes (3): Emenda A: `resume` verifica o host, garante o keyring, sobe o target e nunca…, R6: manifesto corrompido em resume levanta PodmanError em vez de silenciar., TestSingleRuntimeResume

### Community 101 - "TestRevisionFallbackIsPerCheckout"
Cohesion: 0.27
Nodes (4): `dev` era compartilhado: dois checkouts sem git escreviam por cima do mesmo…, `up` reescreve `asb-network.service`, que TODO workspace `Requires=`, fora do…, TestRevisionFallbackIsPerCheckout, TestSharedNetworkGateSurvivesRollback

### Community 102 - "Known Regressions — Sandbox Domain"
Cohesion: 0.14
Nodes (14): Known Regressions — Sandbox Domain, R10 — Initializing the rootless network namespace before real connectivity, R11 — Driving a systemd-supervised container with Podman directly, R12 — PID-derived names for temporary paths on a shared volume, R13 — A test that pins the defect's own output, R1 — Prefix matching without a delimiter, R2 — Credential storage behind a symlink or a single-file bind mount, R3 — Treating a provider CLI's exit 0 as proof the action happened (+6 more)

### Community 104 - "ProbeResult"
Cohesion: 0.17
Nodes (9): probe_workspace(), ProbeResult, Executa o conjunto de probes de prontidão para o workspace informado., A#2: `resume` so publica conexao depois do gate de prontidao; falha de…, Executa o callback UMA vez: exercita o `check_ws` real sem gastar os 30s de…, TestResumeReadinessGate, TestProbeResult, TestProbeWorkspace (+1 more)

### Community 105 - "test_lifecycle.py"
Cohesion: 0.11
Nodes (11): Layout, C1 regression: `manifest_containers["forwarder"]` referenciava `fwd_name`, uma…, I4: `up` resolvia a porta SSH duas vezes (uma para o gate de prontidao, outra…, I5: `WorkspaceTransaction.rollback` engolia qualquer excecao ao remover…, A politica de egresso e do operador, nunca do agente. `layout.project_root`…, `credential_mount_args` toca o disco (resolve o mountpoint do volume e cria os…, TestLifecycleOrdering, TestNoRuntimeSelection (+3 more)

### Community 106 - "TestManagedLifecycleCommands"
Cohesion: 0.14
Nodes (6): Achado da revisao final: `systemctl` falhando (hook sem barramento do usuario,…, S1: suspend deve verificar que os containers pararam de fato, e retornar codigo…, B#4: `remove_workspace_units` termina em `daemon-reload` com check=True. Numa…, Mesmo contrato para `FileNotFoundError`: host sem `systemctl` no PATH tambem…, `down` e a saida de emergencia: um runtime.json corrompido que faz…, TestManagedLifecycleCommands

### Community 107 - "Test Shape"
Cohesion: 0.40
Nodes (5): Adjacent Checks, Test Shape, The Question, What to Report, Why: three defects that passed review

### Community 108 - "unit/test_network_gate.py"
Cohesion: 0.14
Nodes (8): _FakeClock, Unit tests for cli/asb/network_gate.py — espera unica por conectividade real…, Cada leitura avanca `step` segundos., _result(), TestGateNeverSpawnsProcesses, TestGateTarget, TestRuntimeShipsNetworkGate, TestWaitForNetwork

### Community 109 - "test_sandbox_fixture_guard.py"
Cohesion: 0.31
Nodes (6): _podman_names(), skipUnless, Integration test for tests/integration/sandbox_fixture.py — guarda do setup.…, O volume de sessao e criado por `lifecycle`, nao pela fixture. Por nao estar…, TestSandboxFixtureEnterGuard, TestSessionVolumeTeardown

### Community 110 - "Claim Verification"
Cohesion: 0.22
Nodes (6): Calibration, Claim Verification, Method, The Question, Worked Example, Review Domain Pack

### Community 111 - "TestClassifyVerification"
Cohesion: 0.07
Nodes (10): 403 puro tambem e a assinatura de uma negativa de ACL do proxy. So a evidencia…, Mesmo espirito do R4 (docs/domains/sandbox/known-regressions.md), mas em texto:…, R4 do catalogo de regressoes (docs/domains/sandbox/known- regressions.md):…, Guarda do proprio guarda: a delimitacao nao pode se tornar tao estrita a ponto…, A evidencia e sempre texto enlatado (categoria), nunca o `output` interpolado…, Guarda contra estado inventado: cada estado que classify_verification pode…, O teste verbatim do brief: rede ruim nunca vira logout., O texto capturado da CHAMADA (nao a pre-checagem) tambem pode denunciar timeout… (+2 more)

### Community 112 - "TestCredentialDirectoryMounts"
Cohesion: 0.08
Nodes (12): prepare_workspace_harness(), Roda `lifecycle.prepare_workspace` DE VERDADE e devolve o `podman run` do…, I6: a credencial e compartilhada; a transcricao nao. Medido no podman 6.1 antes…, `volume-subpath` NAO cria o caminho de origem (A1): um subpath ausente aborta o…, A1 provou: `rename` sobre symlink corta o vinculo com o volume, e sobre arquivo…, `ensure_credential_dirs` toca um caminho REAL (o mountpoint que o podman…, A causa confirmada: `: > "$stored"` deixava um arquivo de 0 bytes que nunca…, M10: um volume cujo `_data` nao aceita escrita — o estado que o piloto real… (+4 more)

### Community 113 - "test_provider_auth.py"
Cohesion: 0.13
Nodes (12): get_test_image(), _live_auth_enabled(), _live_auth_file_selected(), skipUnless, tests/integration/test_provider_auth.py — verificacao real e piloto (A4). Duas…, Guarda de isolamento: os volumes NOMEADOS nos mounts sao SOMENTE os desta…, Chamadas REAIS via `auth.verify_client()`. So rodam com `ASB_LIVE_AUTH=1` E…, Returns the local agent-sandbox image name if available, else ''. (+4 more)

### Community 118 - "readiness.py"
Cohesion: 0.11
Nodes (13): probe_host_ports(), cli/asb/readiness.py — sondas tipadas de prontidão observacional. Implementa…, Prova que cada porta de `[docker] host_ports` tem listener no agente. O…, socket, Unit tests for cli/asb/readiness.py and cli/asb/runtime_check.py., Emenda A: nenhuma orientacao pode mandar rodar `podman unshare --rootless-…, A remediacao vai para o stderr do operador e para o journal. Interpolar saida…, R11: orientacao que dirige container supervisionado por fora do systemd. O… (+5 more)

### Community 119 - "_ok"
Cohesion: 0.25
Nodes (4): _gate_then(), _ok(), Resultados do gate SSH observacional e da unica chamada real., TestVerifyClientFormatNormalization

### Community 120 - "Global Constraints"
Cohesion: 0.12
Nodes (17): Global Constraints, Runtime único systemd — Implementation Plan, Task 10: Teste de integração da espera com systemd real, Task 11: Testes em shell no runtime único, Task 12: Verificação completa antes da máquina real, Task 13: Troca na máquina real (janela do operador), Task 14: Boots reais (janelas do operador, spec §7.2), Task 15: Fechamento (+9 more)

### Community 121 - "probe_ssh"
Cohesion: 0.23
Nodes (8): probe_keyring(), probe_ssh(), Path, Executa 'true' via SSH com chave e porta informadas. `user` omitido resolve…, Checa saúde do Secret Service / keyring singleton., main(), cli/asb/runtime_check.py — entry point para sondas de prontidão do systemd.…, TestProbeSSH

### Community 122 - "supervisor.py"
Cohesion: 0.10
Nodes (35): _atomic_write_text(), ContainerUnit, escape_systemd_arg(), install_keyring_unit(), install_workspace(), keyring_container_name(), keyring_unit_name(), network_unit_name() (+27 more)

### Community 123 - "TestAggregateExitCodeDeniesByDefault"
Cohesion: 0.18
Nodes (6): C1: o agregado nega por padrao. A versao anterior testava os estados RUINS e…, A regressao propriamente dita: um estado que ninguem previu., O caminho exato do achado: quando a A4 alimentar `pending` no `auth status`, um…, Nao ter perguntado a ninguem nao e prova de nada., Duas copias da regra foi como `pending` ficou certo num caminho e valendo 0 no…, TestAggregateExitCodeDeniesByDefault

### Community 124 - "TestAllowlistBaseCobreOsAgentes"
Cohesion: 0.50
Nodes (3): Semantica do dstdomain do Squid: '.x.com' casa x.com e subdominios., A imagem instala claude, codex e agy. Se a base nao alcanca a API de um deles,…, TestAllowlistBaseCobreOsAgentes

### Community 126 - "Emenda A — runtime único systemd e espera única por rede"
Cohesion: 0.14
Nodes (14): 10. Evidência, 1. Motivo, 2. Decisões do operador, 3. Arquitetura, 4. A espera por rede, 5. Keyring e troca, 6. O que sai e o que muda, 7.1. Testes automatizados (+6 more)

### Community 127 - "asb_test_isolation.py"
Cohesion: 0.29
Nodes (5): _mount_volume_source(), named_volumes(), Isolamento IMPOSTO da suite unitaria: nenhum teste fala de volume real. Nao e…, Nome do volume citado num `--mount type=volume,src=...`., Volumes que esta linha de comando do podman nomeia.

### Community 128 - "render"
Cohesion: 0.17
Nodes (12): Exception, Path, cli/asb/squid.py — junta a allowlist base com o perfil e emite squid.conf. A…, read_base(), render(), SquidError, a_file(), Path (+4 more)

### Community 129 - "test_supervisor_remove_units.py"
Cohesion: 0.21
Nodes (10): clean_env(), env_for(), Path, Unit tests for supervisor.remove_workspace_units., Ambiente minimo: config/drop-in e keyring sinteticos, nada do operador., Aplica `env` e remove seams herdados que mudariam as raizes., R6: um symlink de wants que sobra reabilita o target no proximo boot., R6: manifesto corrompido nunca e silenciado como se estivesse ausente. (+2 more)

### Community 130 - "Piloto real de inicialização e autenticação — T2"
Cohesion: 0.15
Nodes (13): 1.1. A imagem foi reconstruída antes do piloto, 1. Ambiente e versões, 2. Inventário de coexistência (spec §7), 3. Workspace-piloto, 4. Coletor de evidência, 6.10. Boot A2 (rede atrasada, runtime único): APROVADO, 6.12. Retomada do suspenso (critério 2), 6.1. Fase (c) preparada — aguardando janela de reboot (+5 more)

### Community 131 - "6.2. Boot 1 — REPROVADO, e o teste estava contaminado"
Cohesion: 0.15
Nodes (13): 6.2. Boot 1 — REPROVADO, e o teste estava contaminado, A ferramenta tinha avisado, Causa-raiz: o drop-in do próprio projeto cria o namespace em todo boot, Diagnóstico, Duas medições descartadas por serem inválidas, Estado preparado depois do boot 1, Linha do tempo medida, O papel do workspace legacy (+5 more)

### Community 132 - "TestLoginKeyringContract"
Cohesion: 0.23
Nodes (5): Contrato herdado de `TestLoginKeyringIntegration`, que vivia em `test_auth.py`…, O cliente fala com o Secret Service pelo socket. A passphrase e do singleton;…, `PodmanError` na verificacao nao escapa mais do laco (I5): vira resultado…, Herdado de `TestVerificacaoDeLogin`: `--version` responde 0 com o agente…, TestLoginKeyringContract

### Community 133 - "test_auth_verify.py"
Cohesion: 0.32
Nodes (3): Testes de cli/asb/auth.py — verificacao real e orcamento explicito (A4).…, TestAgentsBehindProxyExitStatus, TestCodexRemoteScript

### Community 134 - "TestVerifyCommand"
Cohesion: 0.18
Nodes (4): `verify` nunca muta estado: nenhuma chamada a login()/operator_lock., O teste de log exigido pelo brief: fixtures com token, bearer e codigo OAuth…, `verify(ws, provider, json_output=...)`: mesmo schema de relatorio de…, TestVerifyCommand

### Community 135 - "TestLoginCommandTable"
Cohesion: 0.18
Nodes (5): O contrato exato dos comandos de login, verbatim do brief da A3., `claude /login` sai com 0 SEM logar (A1): um falso verde que manda o operador…, `--console` seleciona faturamento por API em vez da assinatura., `--version` responde 0 com o agente deslogado., TestLoginCommandTable

### Community 138 - "TestVerifyClientCallBudget"
Cohesion: 0.18
Nodes (3): Uma chamada por fornecedor por `verify_client`, sem retry, e sempre observavel…, TestVerifyClientCallBudget, _unreachable_probe()

### Community 140 - "TestUnitSuiteIsolation"
Cohesion: 0.20
Nodes (4): Guarda do proprio guarda: um invólucro que recusasse tudo faria os testes acima…, A costura exata que contaminou o volume de producao, agora com o guarda no…, C2: o isolamento da suite e IMPOSTO, nao pedido em docstring. O que aconteceu…, TestUnitSuiteIsolation

### Community 141 - "TestLegacyCredentialLayoutWarning"
Cohesion: 0.29
Nodes (4): I3: o layout de raiz e detectado e ANUNCIADO. Nada e apagado., A politica de migracao nao e desta funcao, e apagar credencial nunca e…, Um `claude/auth.json` DENTRO do subdiretorio e o layout novo: nao pode ser…, TestLegacyCredentialLayoutWarning

### Community 142 - "TestEntrypointCredentialLayout"
Cohesion: 0.20
Nodes (4): A causa confirmada em A1 vive nestas linhas do entrypoint., Guarda do proprio teste: os assertos acima varrem so o codigo, e passariam num…, A copia acontece ao lado e so entra no lugar pronta. O contrato completo —…, TestEntrypointCredentialLayout

### Community 143 - "normalize_domains"
Cohesion: 0.33
Nodes (4): normalize_domains(), Squid aborta com 'FATAL: Bungled' quando .github.com e api.github.com aparecem…, notgithub.com termina em 'github.com' como texto, mas nao e subdominio de…, TestNormalize

### Community 146 - "TestVerifyFreshClient"
Cohesion: 0.25
Nodes (3): O `try` comeca ANTES do `podman run`: um Ctrl-C ou uma falha entre a criacao e…, `agy -p ping` bloqueia 60s quando deslogado (A1). Enquanto A4 nao entrega…, TestVerifyFreshClient

### Community 147 - "_SSHInfraCase"
Cohesion: 0.18
Nodes (7): Contexto local minimo; a chamada ao fornecedor continua sintetica., A protecao mais critica desta tarefa: se a chamada em si expirar (o caso mais…, O orcamento e gasto na TENTATIVA, nao no sucesso: nao ha retry escondido so…, Evidencia de sucesso exige resposta no formato solicitado, nao um grep de 'ok'.…, _SSHInfraCase, TestVerifyClientFormatEvidence, TestVerifyClientTimeoutNeverBecomesLogout

### Community 148 - "test_doctor.py"
Cohesion: 0.28
Nodes (3): Testes de cli/asb/doctor.py e pull/purge em cli/asb/lifecycle.py., TestDoctorServiceBlockNeverSwallows, TestPull

### Community 149 - "Recuperação do uplink rootless do Podman"
Cohesion: 0.29
Nodes (7): Contexto, Critérios de aceitação, Decisão de arquitetura, Fora de escopo, Invariantes, Objetivo, Recuperação do uplink rootless do Podman

### Community 150 - "5. Estado de autenticação medido"
Cohesion: 0.20
Nodes (10): 5.1. Antes do login humano (imagem já reconstruída), 5.2. Depois do login humano (2026-09-16T17:59Z), 5.3.1. Correção da guarda (autorizada pelo operador) e resultado real, 5.3.2. Cliente novo e dois workspaces simultâneos, 5.3. Antigravity: evidência direta contradiz o classificador, 5.4. ACHADO DE SEGURANÇA: credencial viva exposta na raiz do volume, 5.5. CORREÇÃO: `codex-auth.json` é a credencial VIVA do Codex, 5.6. Opção A executada — symlink eliminado (+2 more)

### Community 151 - "TestEmendaAChecks"
Cohesion: 0.17
Nodes (3): Emenda A: o doctor aponta o drop-in legado, a espera de rede e produtores…, Toda unidade de workspace tem Requires=asb-network.service: com a espera em…, TestEmendaAChecks

### Community 153 - "prepare_workspace"
Cohesion: 0.15
Nodes (8): build_proxy(), ensure_toolcache_volume(), _get_container_id(), prepare_workspace(), Rastreia recursos criados durante a transacao de up para rollback estrito por…, Prepara clone, redes, containers e manifesto sem restauracao global., start_services(), WorkspaceTransaction

### Community 155 - "Supervisão da inicialização — Implementation Plan"
Cohesion: 0.22
Nodes (9): Global Constraints, I1 — Provar supervisão e criar fixture isolada, I2 — Diagnóstico tipado e prontidão observacional, I3 — Instalação versionada e uma única supervisão, I4 — Forwarder com falha visível e portas baixas, I5 — Integrar ciclo de vida, prontidão e rollback de criação, I6 — Adoção e rollback sem recriação dos workspaces, Saída desta frente (+1 more)

### Community 156 - "asb/__init__.py"
Cohesion: 0.09
Nodes (14): tests/integration/sandbox_fixture.py — isolated test fixture for systemd…, _free_port(), _is_active(), skipUnless, Integracao real: a espera por rede segura unidades dependentes (Emenda A §7.1).…, TestNetworkGateHoldsDependents, _wait_for(), tests/integration/test_workspace_supervision.py — Integration tests for managed… (+6 more)

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
Cohesion: 0.33
Nodes (6): 1. Ownership: systemd starts, Podman creates, 2. Commands and State Transitions, 3. Recovery by Category, Boot order, Units (`~/.config/systemd/user/`), Workspace Lifecycle & Supervision

### Community 163 - "Inicialização e autenticação — Implementation Plan"
Cohesion: 0.25
Nodes (8): Estrutura de arquivos, Global Constraints, Inicialização e autenticação — Implementation Plan, Investimento e critério de interrupção, Ordem e pontos de decisão, T1 — Integrar as frentes e provar o fluxo Orca, T2 — Piloto real, reboot e retorno, T3 — Aceitar operação e atualizar documentação

### Community 165 - "TestEntrypointNeverDestroysSharedDirectories"
Cohesion: 0.29
Nodes (3): I6, segunda metade: com `~/.claude` compartilhado, todo `up` apagava e recriava…, O limite fica escrito: `mv` sobre diretorio nao e `renameat2(RENAME_EXCHANGE)`,…, TestEntrypointNeverDestroysSharedDirectories

### Community 167 - "Profile"
Cohesion: 0.33
Nodes (6): Encaminha SO as portas declaradas para o host., start_forwarder(), Profile, Testa o comportamento de host_api em cli/asb/lifecycle.py., TestLifecycleHostApi, TestStartForwarder

### Community 168 - "TestSingleRuntimeUp"
Cohesion: 0.31
Nodes (3): Emenda A: `up` tem runtime unico, remove o drop-in, verifica o host e nunca…, `host_ports` e pos-condicao prometida ao projeto: sem sonda, o `up` imprimia a…, TestSingleRuntimeUp

### Community 170 - "LoginBusy"
Cohesion: 0.50
Nodes (3): LoginBusy, Exception, Ja existe uma sessao de login deste fornecedor nesta maquina.

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

## Knowledge Gaps
- **573 isolated node(s):** `entrypoint.sh script`, `start-keyring.sh script`, `DBUS_SESSION_BUS_ADDRESS`, `common.sh script`, `shim.template.sh script` (+568 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **39 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `SandboxFixture` connect `SandboxFixture` to `Pilot`, `.is_container_running`, `test_credential_writers.py`, `test_sandbox_fixture_guard.py`, `TestSupervisorPilot`, `TestForwarderIntegration`, `test_provider_auth.py`, `IsolationError`, `TestTeardownCommandClasses`, `Path`, `asb/__init__.py`, `test_entrypoint_concurrency.py`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Why does `load_profile()` connect `load_profile` to `doctor.py`, `lifecycle.py`, `prepare_workspace`, `Profile`?**
  _High betweenness centrality (0.017) - this node is a cross-community bridge._
- **Are the 14 inferred relationships involving `SandboxFixture` (e.g. with `TestBindMountAtomicReplace` and `TestContainerPermissionsAndPaths`) actually correct?**
  _`SandboxFixture` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `ProbeResult` (e.g. with `wait_for_network()` and `TestResumeReadinessGate`) actually correct?**
  _`ProbeResult` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `AuthResult` (e.g. with `TestVerifyCommand` and `TestAggregateExitCodeDeniesByDefault`) actually correct?**
  _`AuthResult` has 9 INFERRED edges - model-reasoned connections that need verification._
- **What connects `entrypoint.sh script`, `start-keyring.sh script`, `DBUS_SESSION_BUS_ADDRESS` to the rest of the system?**
  _573 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `run` be split into smaller, more focused modules?**
  _Cohesion score 0.12433862433862433 - nodes in this community are weakly interconnected._