# Graph Report - agent-sandbox  (2026-09-07)

## Corpus Check
- 136 files · ~146,055 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1580 nodes · 2388 edges · 118 communities (91 shown, 27 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 71 edges (avg confidence: 0.81)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `f8c4f528`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- PodmanError
- Path
- assert.sh
- load_profile
- build_staging
- TestRender
- patch
- permitted
- What You Must Do When Invoked
- AGENTS.md
- What You Must Do When Invoked
- ProjectDetectionTest
- common.sh
- sync-skills.mjs
- TestPodmanRestart
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
- out
- Singleton Secret Service Implementation Plan
- File Structure
- Recuperação do uplink rootless do Podman
- Configuration Reference (`.agent-sandbox.toml`)
- sandbox/README.md
- Integração project-scoped do Graphify no agent-sandbox
- Git Commit Conventions
- start-keyring.sh
- Global Constraints
- test_lifecycle.py
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
- entrypoint.sh
- ProbeResult
- supervisor.py
- Redesenho de inicialização e autenticação
- CLAUDE.md
- Google Antigravity & Gemini CLI Configuration
- TestForwarderProcessLifecycle
- Contratos de Autenticação por Fornecedor e Protocolo de Validação
- test_credential_writers.py
- ._validate_resource_name
- TestSupervisorPilot
- 3. Resultados dos Ensaios Empíricos
- TestForwarderIntegration
- WorkspaceTransaction
- .is_container_running
- Secret Service singleton para credenciais dos agentes
- integration/__init__.py
- SandboxFixture
- 2. Fatos verificados empiricamente
- run
- .teardown
- TestCredentialWritersFilesystem
- 6. Acesso a Docker
- auth.py
- render
- test_workspace_supervision.py
- TestWorkspaceOperations
- 16. Portabilidade e reinstalação
- 4. Topologia e ciclo de vida
- 5. Sistema de arquivos
- 7. Credenciais, configuração e integração dos agentes
- 9. Fronteiras de segurança
- 1. Por que reconstruir
- Known Regressions — Sandbox Domain
- forwarder.sh
- normalize_domains
- Profile
- TestManagedLifecycleCommands
- review/README.md
- TestRuntimeOf
- start_forwarder
- Claim Verification
- TestToolDrift
- TestAllowlistBaseCobreOsAgentes
- TestLifecycleHostApi
- TestReloadAllowlist
- claim-verifier/agent.md
- regression-sentinel/agent.md
- test-shape-auditor/agent.md

## God Nodes (most connected - your core abstractions)
1. `SandboxFixture` - 61 edges
2. `load_profile()` - 37 edges
3. `Profile` - 32 edges
4. `run()` - 30 edges
5. `prepare_workspace()` - 27 edges
6. `Layout` - 25 edges
7. `PodmanError` - 23 edges
8. `exists()` - 23 edges
9. `TestDoctorSecretService` - 23 edges
10. `layout_for()` - 22 edges

## Surprising Connections (you probably didn't know these)
- `TestPull` --uses--> `PodmanError`  [INFERRED]
  tests/unit/test_doctor.py → cli/asb/podman.py
- `TestPurge` --uses--> `PodmanError`  [INFERRED]
  tests/unit/test_doctor.py → cli/asb/podman.py
- `TestPodmanRun` --uses--> `PodmanError`  [INFERRED]
  tests/unit/test_podman.py → cli/asb/podman.py
- `TestLifecycleHostApi` --uses--> `Profile`  [INFERRED]
  tests/unit/test_broker.py → cli/asb/profile.py
- `TestStartForwarder` --uses--> `Profile`  [INFERRED]
  tests/unit/test_lifecycle.py → cli/asb/profile.py

## Import Cycles
- None detected.

## Communities (118 total, 27 thin omitted)

### Community 0 - "PodmanError"
Cohesion: 0.17
Nodes (9): ensure_rootless_netns(), PodmanError, Exception, require_binary(), patch, Testes de cli/asb/podman.py — invólucro fino sobre o binário podman., TestEnsureRootlessNetns, TestPodmanBinary (+1 more)

### Community 1 - "Path"
Cohesion: 0.09
Nodes (21): _git(), prepare_clone(), Exception, Path, cli/asb/workspace.py — identidade do workspace, layout em disco e clone. Duas…, Identidade do workspace, sempre reproduzivel a partir das entradas. O Orca…, Cria o checkout do workspace, se ainda nao existir. Clone e nao worktree: uma…, _sanitize() (+13 more)

### Community 2 - "assert.sh"
Cohesion: 0.06
Nodes (35): assert_contains(), assert_eq(), assert_fails(), assert_not_contains(), report(), require(), assert.sh script, wait_for() (+27 more)

### Community 3 - "load_profile"
Cohesion: 0.10
Nodes (24): _choice(), load_profile(), _ports(), ProfileError, _publish_ports(), Exception, Path, cli/asb/profile.py — le .agent-sandbox.toml e devolve um perfil validado. O… (+16 more)

### Community 4 - "build_staging"
Cohesion: 0.10
Nodes (29): _allowed_destination_roots(), _allowed_symlink_roots(), build_staging(), copy_file(), denied(), filter_claude_settings(), filter_codex_config(), _key() (+21 more)

### Community 5 - "TestRender"
Cohesion: 0.23
Nodes (6): a_file(), Path, Testes de cli/asb/squid.py — geracao do squid.conf., Um squid.conf sem dominio algum sobe e nega tudo: o sandbox fica sem egresso e…, Com mode = nested o agente puxa imagens pelo proxy; sem os registries a falha…, TestRender

### Community 6 - "patch"
Cohesion: 0.07
Nodes (7): patch, Sem o link o CLI so roda de dentro do checkout, e isso fica mudo., TestCheckWorkspaceEgress, TestDoctor, TestDoctorSecretService, TestPull, TestPurge

### Community 7 - "permitted"
Cohesion: 0.10
Nodes (11): Handler, main(), permitted(), relay(), Server, Testa cli/asb/install.py broker()., Testa a função permitted(method, target) do broker., Testa a rejeição no nível de protocolo HTTP no Handler. (+3 more)

### Community 8 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 9 - "AGENTS.md"
Cohesion: 0.21
Nodes (5): Role, Documents, Git Domain Pack, Available Domain Packs, Domain Packs

### Community 10 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native AGENTS.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 12 - "common.sh"
Cohesion: 0.27
Nodes (7): asb_recipe_json(), asb_workspace_id(), common.sh script, create.sh script, destroy.sh script, resume.sh script, suspend.sh script

### Community 13 - "sync-skills.mjs"
Cohesion: 0.17
Nodes (8): BANNER_LINES, CHECK, __dirname, MIRRORS, PRUNE, ROOT, skills, VENDOR

### Community 14 - "TestPodmanRestart"
Cohesion: 0.09
Nodes (6): Testes de cli/asb/install.py — instaladores do host., O CLI precisa rodar de qualquer diretorio, nao so do checkout. Ele ja funciona…, Modo de falha da §16.1: a pasta muda de lugar e o link fica orfao., TestInstallGuards, TestInstallRuntime, TestPodmanRestart

### Community 15 - "Graphify Knowledge Graph Architecture"
Cohesion: 0.15
Nodes (11): 1. Architectural Role & Principles, 2. Baseline & Prerequisites, 3. Setup & Verification, 4. Domain-Specific Ingestion (`.graphify/project.py`), 5. Security Guardrails & Exclusions, 6. Query Cheatsheet, 7. Semantic Update Protocol & Two-Commit Workflow, 8. Linked Worktrees & Headless Environments (+3 more)

### Community 16 - "Design: agent-sandbox v2"
Cohesion: 0.17
Nodes (12): 10. Documentação, 11. Superfície do CLI, 12. Testes, 13. O que é removido, 14. Riscos, 15. Modos de falha que não podem voltar, 17. Anexo — esquema completo de `.agent-sandbox.toml`, 3. Decisões (+4 more)

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

### Community 24 - "lifecycle.py"
Cohesion: 0.12
Nodes (34): install_runtime(), Instala o runtime versionado em ~/.local/lib/agent-sandbox/runtime/<revisao>/.…, build_proxy(), _current_revision(), emit(), ensure_ssh_key(), _get_container_id(), list_workspaces() (+26 more)

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
Cohesion: 0.10
Nodes (21): 10. Orca Recipe Selector Invisibility, 11. Squid Configuration File Permissions, 12. Missing `--userns=keep-id` on Agent Container, 13. Sibling Worktree Path Collision at Filesystem Root, 14. Claude Code Hanging on Non-Interactive Stdin, 15. Node Header Fetch Failure during Native Module Build, 16. Service Containers Failing under `keep-id` without `--user 0`, 17. Toolchain Installation Failure during Workspace Startup (`up`) (+13 more)

### Community 39 - "TestKeyringServiceLifecycle"
Cohesion: 0.06
Nodes (10): Path, Testes de autenticação e volume de credenciais em cli/asb/lifecycle.py., Espelha a estrutura real de Mounts retornada por podman inspect., A verificacao do login tem de EXERCITAR autenticacao. `asb-agy --version`…, TestAuthLifecycle, TestCheckKeyringService, TestKeyringServiceLifecycle, TestLoginKeyringIntegration (+2 more)

### Community 44 - "TestCheckStatus"
Cohesion: 0.04
Nodes (7): Testes de cli/asb/auth.py — separacao de status de conta, rede e…, Exemplos verbatim do brief da tarefa A2., TestAuthResult, TestCheckStatus, TestParseClaudeStatus, TestParseCodexStatus, TestStatusCommand

### Community 48 - "out"
Cohesion: 0.11
Nodes (23): check_legacy_agent_container(), check_workspace_egress(), diagnose(), doctor(), _host_version(), _image_version(), _line(), Any (+15 more)

### Community 49 - "Singleton Secret Service Implementation Plan"
Cohesion: 0.18
Nodes (8): Global Constraints, Singleton Secret Service Implementation Plan, Task 1: Criar um teste de regressão isolado para o Secret Service, Task 2: Transformar `start-keyring.sh` em serviço singleton, Task 3: Adicionar o ciclo de vida do serviço global, Task 4: Tornar o entrypoint exclusivamente cliente do Secret Service, Task 5: Validar login real no mesmo serviço e diagnosticar falhas, Task 6: Atualizar o SSoT e executar a verificação completa

### Community 50 - "File Structure"
Cohesion: 0.12
Nodes (16): agent-sandbox Implementation Plan, File Structure, Global Constraints, Self-Review, Task 0: Helper de asserção, Task 10: Domain pack e extensão aos demais projetos, Task 11: Tornar o sandbox o único caminho, Task 1: Imagem base com host keys estáveis (+8 more)

### Community 51 - "Recuperação do uplink rootless do Podman"
Cohesion: 0.13
Nodes (13): Global Constraints, Rootless Uplink Recovery Implementation Plan, Task 1: Encapsular a inicialização do namespace rootless, Task 2: Aplicar o helper em `up` e `resume`, Task 3: Preparar o uplink antes da restauração no login, Task 4: Documentar e verificar a correção de rede, Contexto, Critérios de aceitação (+5 more)

### Community 52 - "Configuration Reference (`.agent-sandbox.toml`)"
Cohesion: 0.14
Nodes (13): 1. Schema Reference, 2. Toolchain Provisioning & Shared Cache (`asb-toolcache`), 3. Agent Context Tools (`rtk`, `graphify`), 3. Worked Examples, Changes from v1 Schema, Configuration Reference (`.agent-sandbox.toml`), Example 1: `hexmed` (Host Services & Filtered Docker Inspection), Example 2: `BlackICE` (Nested Container Runtime) (+5 more)

### Community 53 - "sandbox/README.md"
Cohesion: 0.20
Nodes (8): 1. System Topology, 2. CLI Commands, 3. Where Files Live, 4. What to Do on Failure, Container Roles, Documentation Index, Filesystem Layout, Sandbox Domain Pack

### Community 54 - "Integração project-scoped do Graphify no agent-sandbox"
Cohesion: 0.18
Nodes (10): 1. Objetivo e Contexto, 2.1 Baseline e Tooling Local, 2.2 Adaptador de Domínio (`.graphify/project.py`), 2.3 Governança de Agentes e SSoT, 2.4 Integração de Skills e Git, 2. Decisões Arquiteturais, 3. Arquitetura de Arquivos, 4. Estratégia de Testes e Validação (+2 more)

### Community 55 - "Git Commit Conventions"
Cohesion: 0.25
Nodes (8): 1. Authority and Branching Rules, 2. Safe Scope Selection (Surgical Changes), 3. Prerequisites & Empirical Verification, 4. Commit Message Format, 5. Attribution, Commit Body (Mandatory), Git Commit Conventions, Gitmoji Selection

### Community 57 - "Global Constraints"
Cohesion: 0.22
Nodes (8): Global Constraints, Graphify Project Integration Implementation Plan, Plan Self-Review, Task 1: Setup script, ignore rules, and gitattributes, Task 2: Custom domain adapter and automated unit tests, Task 3: Install project-scoped skills and verify synchronization, Task 4: Agent governance, documentation, and commit conventions, Task 5: Generate initial knowledge graph and verify query acceptance

### Community 58 - "test_lifecycle.py"
Cohesion: 0.12
Nodes (16): discover_mise_dirs(), down(), purge(), Le o backend de runtime gravado no manifesto do workspace. Manifesto AUSENTE e…, Encontra todos os diretorios que contem mise.toml, podando pastas irrelevantes., Remove unidades do systemd (se gerenciado), containers e redes. NAO remove…, Para o workspace. Em runtime gerenciado (systemd): Desabilita e para o target…, Remove tambem os ARQUIVOS do workspace. Irreversivel, logo explicito. (+8 more)

### Community 59 - "2. Explicit Declarations: What Is NOT Protected"
Cohesion: 0.15
Nodes (12): 1. Non-Negotiable Invariants, 2. Explicit Declarations: What Is NOT Protected, 3. Network & DNS Boundary, 4. Credential Isolation & The Singleton Secret Service, DNS Tunneling Prevention, Exfiltration to an allowed domain is possible, `host_api = "read"` grants passwordless Docker reading to uid 1000, `mode = "nested"` gives the agent a full container runtime inside the boundary (+4 more)

### Community 60 - "Orca Reboot Persistence Implementation Plan"
Cohesion: 0.29
Nodes (6): Orca Reboot Persistence Implementation Plan, Task 1: readiness de rede e proxy, Task 2: criação transacional e imagem autenticada obrigatória, Task 3: estado completo do Antigravity, Task 4: autenticação verificável e diagnóstico, Task 5: integração Orca e documentação

### Community 61 - "Design: persistência profissional do sandbox no Orca"
Cohesion: 0.33
Nodes (5): Critérios de aceitação, Decisões, Design: persistência profissional do sandbox no Orca, Limites deliberados, Problema confirmado

### Community 62 - "exists"
Cohesion: 0.19
Nodes (19): check_keyring_service(), ensure_keyring_data_volume(), ensure_keyring_pass(), ensure_keyring_runtime_volume(), ensure_keyring_service(), _inspect_keyring_container(), _keyring_mount_contract_issue(), Path (+11 more)

### Community 70 - "ProbeResult"
Cohesion: 0.08
Nodes (29): probe_host(), probe_keyring(), probe_proxy(), probe_ssh(), probe_workspace(), ProbeResult, Path, cli/asb/readiness.py — sondas tipadas de prontidão observacional. Implementa… (+21 more)

### Community 71 - "supervisor.py"
Cohesion: 0.09
Nodes (27): broker(), guards(), _link(), podman_restart(), Path, cli/asb/install.py — o que o sandbox instala no host. Regra da §16: tudo aqui e…, Habilita a unidade que o proprio podman ja instala. `podman start --all…, Symlink para o checkout, nunca copia: uma copia envelhece em silencio e o… (+19 more)

### Community 72 - "Redesenho de inicialização e autenticação"
Cohesion: 0.05
Nodes (38): A1 — Caracterizar o login real antes de escolher a correção, A2 — Separar status de conta, rede e infraestrutura, A3 — Login seletivo, persistência comprovada e versões, A4 — Verificação real e orçamento explícito, Autenticação por fornecedor — Implementation Plan, Global Constraints, Saída desta frente, Estrutura de arquivos (+30 more)

### Community 73 - "CLAUDE.md"
Cohesion: 0.22
Nodes (4): Available Subagents (`.claude/agents/`), Claude Code Configuration, Knowledge Graph (`graphify-out/`), Skills (`.claude/skills/`)

### Community 74 - "Google Antigravity & Gemini CLI Configuration"
Cohesion: 0.50
Nodes (4): Available Subagents (`.agents/agents/`), Google Antigravity & Gemini CLI Configuration, Knowledge Graph (`graphify-out/`), Skills (`.agents/skills/`)

### Community 75 - "TestForwarderProcessLifecycle"
Cohesion: 0.14
Nodes (6): Popen, tests/unit/test_forwarder_script.py — Unit tests for image/forwarder.sh…, Tests input validation of image/forwarder.sh., Tests process supervision semantics: fail-fast on child death and SIGTERM…, TestForwarderProcessLifecycle, TestForwarderScriptValidation

### Community 76 - "Contratos de Autenticação por Fornecedor e Protocolo de Validação"
Cohesion: 0.07
Nodes (26): 1. Sumário Executivo, 2. Matriz de Contratos por Fornecedor, 3.1 Claude Code: Análise Forense do Binário e a Divergência do Libsecret, 3.2 OpenAI Codex: Análise de Armazenamento e Configuração Efetiva, 3.3 Google Antigravity: Análise de D-Bus, Secret Service e Sessão SSH, 3. Análise Detalhada dos Binários e Divergências Históricas, 4.1 Falha de Symlink sob `replace()` Atômico, 4.2 Rejeição de Symlinks por `O_NOFOLLOW` (+18 more)

### Community 77 - "test_credential_writers.py"
Cohesion: 0.14
Nodes (12): get_test_image(), tests/integration/test_credential_writers.py — Empirical tests for credential…, Container-level validation using SandboxFixture under uid 1000., Proves uid 1000 can create, chmod 0600, write, and read credential files., Exercises absent destination, empty 0-byte file, malformed JSON, and broken…, Simulates the entrypoint.sh symlink layout inside the container as uid 1000.…, Proves Claude Code CLI (2.1.263) status handling under 0-byte, corrupt, broken,…, Returns local agent-sandbox image if available, else alpine fallback. (+4 more)

### Community 78 - "._validate_resource_name"
Cohesion: 0.13
Nodes (6): Sets up dedicated isolated paths, keys, launcher, and volumes., Creates the synthetic persistent container., Renders the systemd unit content for the pilot., Installs and reloads the unit in user systemd., Sets up and starts the forwarder container with the declared ports., Waits until the forwarder has an active LISTEN socket on port.

### Community 79 - "TestSupervisorPilot"
Cohesion: 0.10
Nodes (13): IsolationError, Exception, tests/integration/sandbox_fixture.py — isolated test fixture for systemd…, Raised when an operation attempts to access or mutate resources outside…, tests/integration/test_supervisor_pilot.py — Empirical supervision pilot test.…, Proves runtime launcher helper seamlessly attaches to an already running…, Proves literal unit behavior: podman start --attach on running container…, Proves SandboxFixture refuses foreign resources, production names, and external… (+5 more)

### Community 80 - "3. Resultados dos Ensaios Empíricos"
Cohesion: 0.15
Nodes (12): 1. Objetivo e Escopo, 2. Artefatos Desenvolvidos, 3.1. Recuperação após Falha e Preservação de Identidade, 3.2. Saída Limpa Inesperada (Código 0), 3.3. Falha em `ExecStartPost` e Limpeza por `ExecStopPost`, 3.4. Reconexão a Container em Execução, 3.5. Proteção de Isolamento, 3. Resultados dos Ensaios Empíricos (+4 more)

### Community 81 - "TestForwarderIntegration"
Cohesion: 0.12
Nodes (9): tests/integration/test_forwarder.py — Integration tests for port forwarder…, Proves initial bind errors or invalid port arguments fail immediately., Empirical integration tests for asb-forwarder and unprivileged low ports., Proves undeclared ports remain closed and forwarder is not a general proxy., Proves killing one listener causes forwarder failure, supervisor restart, and…, Proves the proxy image explicitly contains bash and the forwarder executable., Proves the old un-supervised script masks child process failure., Proves forwarder handles SIGTERM cleanly and exits status 0. (+1 more)

### Community 83 - ".is_container_running"
Cohesion: 0.33
Nodes (3): Checks if container is currently in status 'running'., Waits until the unit is active and container is running., Verifies that no running container or orphan processes remain.

### Community 84 - "Secret Service singleton para credenciais dos agentes"
Cohesion: 0.22
Nodes (9): Ciclo de vida, Compatibilidade e migração, Contexto, Critérios de aceitação, Decisão de arquitetura, Fora de escopo, Objetivo, Secret Service singleton para credenciais dos agentes (+1 more)

### Community 86 - "SandboxFixture"
Cohesion: 0.08
Nodes (13): Starts the supervised systemd unit., Stops the supervised systemd unit., Simulates container failure by sending SIGKILL., Stops container cleanly (exit 0) to test unexpected zero-exit., Isolated sandbox fixture context manager for integration tests., Returns the container ID and host port mapping as (cid, port)., Writes a sentinel file inside the container., Checks if the sentinel file exists inside the container. (+5 more)

### Community 87 - "2. Fatos verificados empiricamente"
Cohesion: 0.25
Nodes (8): 2. Fatos verificados empiricamente, F1 — Rede `--internal` isola sem nftables e **persiste através de restart**, F2 — Proxy dual-homed funciona e é alcançável por nome, F3 — Publicação de porta funciona em rede interna, e a porta é estável, F4 — `podman-restart.service` já existe como unidade de usuário, F5 — O socket do Docker é inalcançável pelo usuário, F6 — Podman rootless aninhado funciona sem privilégio, F7 — O Orca cria a worktree como irmã do `projectRoot`

### Community 88 - "run"
Cohesion: 0.17
Nodes (7): build(), ensure_toolcache_volume(), Constroi a imagem base espelhando o usuario do host. id -un e $HOME entram como…, CompletedProcess, `timeout`, quando informado, limita o lado do HOST (subprocess.run) e levanta…, run(), TestPodmanRun

### Community 89 - ".teardown"
Cohesion: 0.15
Nodes (7): BaseException, CompletedProcess, Path, Runs a command inside the container via podman exec., Executes the ASB CLI within the isolated environment., Cleans up all registered resources strictly., TracebackType

### Community 90 - "TestCredentialWritersFilesystem"
Cohesion: 0.33
Nodes (4): Filesystem-level tests for atomic replacement, symlinks, and O_NOFOLLOW., Proves atomic replace() replaces the symlink itself, leaving the stored target…, Proves opening a symlink with O_NOFOLLOW raises ELOOP (Errno 40) on Linux. This…, TestCredentialWritersFilesystem

### Community 91 - "6. Acesso a Docker"
Cohesion: 0.40
Nodes (5): 6.1 `host_ports` — alcançar serviços do host, 6.2 `mode = "nested"` — containers dentro do sandbox, 6.3 `host_api = "read"` — socket filtrado, só leitura, 6.4 O que não será construído, 6. Acesso a Docker

### Community 92 - "auth.py"
Cohesion: 0.20
Nodes (16): ArgumentParser, build_parser(), main(), _aggregate_exit_code(), AuthResult, check_status(), _now_iso(), parse_claude_status() (+8 more)

### Community 93 - "render"
Cohesion: 0.36
Nodes (6): Exception, Path, cli/asb/squid.py — junta a allowlist base com o perfil e emite squid.conf. A…, read_base(), render(), SquidError

### Community 94 - "test_workspace_supervision.py"
Cohesion: 0.33
Nodes (4): tests/integration/test_workspace_supervision.py — Integration tests for managed…, End-to-end integration tests for systemd-managed workspace lifecycle., Proves complete managed lifecycle: up -> SSH -> sentinel -> suspend -> resume…, TestWorkspaceSupervision

### Community 95 - "TestWorkspaceOperations"
Cohesion: 0.09
Nodes (5): Unit tests for cli/asb/supervisor.py — systemd supervision and unit generation., I1: `remove_workspace_units` removia unidades por glob `asb-{ws}-*.service`,…, Sem manifesto legivel, nao ha como saber quais nomes de servico pertencem a…, TestContainerUnitAndRender, TestWorkspaceOperations

### Community 96 - "16. Portabilidade e reinstalação"
Cohesion: 0.50
Nodes (4): 16.1 Regras, 16.2 Dependências, e o que acontece sem cada uma, 16.3 Máquina nova, do zero, 16. Portabilidade e reinstalação

### Community 97 - "4. Topologia e ciclo de vida"
Cohesion: 0.50
Nodes (4): 4.1 Topologia, 4.2 Ciclo de vida, 4.3 Identidade do workspace, 4. Topologia e ciclo de vida

### Community 98 - "5. Sistema de arquivos"
Cohesion: 0.50
Nodes (4): 5.1 Layout, 5.2 O estado do workspace fica FORA da pasta montada, 5.3 Como o trabalho retorna, 5. Sistema de arquivos

### Community 99 - "7. Credenciais, configuração e integração dos agentes"
Cohesion: 0.50
Nodes (4): 7.1 Credenciais em volume, 7.2 Configuração por staging montado, 7.3 Integração dos três agentes, 7. Credenciais, configuração e integração dos agentes

### Community 100 - "9. Fronteiras de segurança"
Cohesion: 0.50
Nodes (4): 9.1 Invariantes inegociáveis, 9.2 O que isto não protege, 9.3 DNS, 9. Fronteiras de segurança

### Community 101 - "1. Por que reconstruir"
Cohesion: 0.67
Nodes (3): 1.1 Os problemas relatados, 1.2 A causa raiz, 1. Por que reconstruir

### Community 102 - "Known Regressions — Sandbox Domain"
Cohesion: 0.20
Nodes (10): Known Regressions — Sandbox Domain, R1 — Prefix matching without a delimiter, R2 — Credential storage behind a symlink or a single-file bind mount, R3 — Treating a provider CLI's exit 0 as proof the action happened, R4 — Substring matching a status code, R5 — Hardcoded identity default in a probe, R6 — Collapsing "absent" and "unreadable" into a default branch, R7 — Dead mocks hiding a deleted call site (+2 more)

### Community 104 - "normalize_domains"
Cohesion: 0.33
Nodes (4): normalize_domains(), Squid aborta com 'FATAL: Bungled' quando .github.com e api.github.com aparecem…, notgithub.com termina em 'github.com' como texto, mas nao e subdominio de…, TestNormalize

### Community 105 - "Profile"
Cohesion: 0.20
Nodes (7): Profile, Layout, C1 regression: `manifest_containers["forwarder"]` referenciava `fwd_name`, uma…, I4: `up` resolvia a porta SSH duas vezes (uma para o gate de prontidao, outra…, I5: `WorkspaceTransaction.rollback` engolia qualquer excecao ao remover…, TestLifecycleOrdering, TestTransactionalRollback

### Community 106 - "TestManagedLifecycleCommands"
Cohesion: 0.18
Nodes (4): S1: suspend deve verificar que os containers pararam de fato, e retornar codigo…, I2: `down` de workspace legacy nao pode chamar remove_workspace_units.…, `down` e a saida de emergencia de um workspace quebrado: um runtime.json…, TestManagedLifecycleCommands

### Community 107 - "review/README.md"
Cohesion: 0.22
Nodes (6): Review Domain Pack, Adjacent Checks, Test Shape, The Question, What to Report, Why: three defects that passed review

### Community 108 - "TestRuntimeOf"
Cohesion: 0.29
Nodes (3): I3: `_runtime_of` deve distinguir manifesto AUSENTE (legacy, ok) de manifesto…, Um manifesto ilegivel NAO pode virar 'legacy' em silencio: isso faria `resume`…, TestRuntimeOf

### Community 109 - "start_forwarder"
Cohesion: 0.47
Nodes (3): Encaminha SO as portas declaradas para o host., start_forwarder(), TestStartForwarder

### Community 110 - "Claim Verification"
Cohesion: 0.33
Nodes (5): Calibration, Claim Verification, Method, The Question, Worked Example

### Community 112 - "TestAllowlistBaseCobreOsAgentes"
Cohesion: 0.50
Nodes (3): Semantica do dstdomain do Squid: '.x.com' casa x.com e subdominios., A imagem instala claude, codex e agy. Se a base nao alcanca a API de um deles,…, TestAllowlistBaseCobreOsAgentes

## Knowledge Gaps
- **448 isolated node(s):** `start-keyring.sh script`, `DBUS_SESSION_BUS_ADDRESS`, `common.sh script`, `shim.template.sh script`, `__dirname` (+443 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **27 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `SandboxFixture` connect `SandboxFixture` to `ProbeResult`, `test_credential_writers.py`, `._validate_resource_name`, `TestSupervisorPilot`, `TestForwarderIntegration`, `.is_container_running`, `.teardown`, `test_workspace_supervision.py`?**
  _High betweenness centrality (0.065) - this node is a cross-community bridge._
- **Why does `Profile` connect `Profile` to `load_profile`, `TestRender`, `start_forwarder`, `TestLifecycleHostApi`, `lifecycle.py`, `test_lifecycle.py`, `render`?**
  _High betweenness centrality (0.029) - this node is a cross-community bridge._
- **Why does `load_profile()` connect `load_profile` to `out`, `lifecycle.py`, `Profile`?**
  _High betweenness centrality (0.017) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `SandboxFixture` (e.g. with `TestBindMountAtomicReplace` and `TestContainerPermissionsAndPaths`) actually correct?**
  _`SandboxFixture` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `Profile` (e.g. with `start_forwarder()` and `start_services()`) actually correct?**
  _`Profile` has 10 INFERRED edges - model-reasoned connections that need verification._
- **What connects `start-keyring.sh script`, `DBUS_SESSION_BUS_ADDRESS`, `common.sh script` to the rest of the system?**
  _448 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Path` be split into smaller, more focused modules?**
  _Cohesion score 0.09230769230769231 - nodes in this community are weakly interconnected._