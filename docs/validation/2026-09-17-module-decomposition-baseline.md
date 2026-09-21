# Baseline pré-decomposição de módulos — 2026-09-17

Tarefa 1 do plano `2026-09-17-agent-sandbox-module-decomposition`: nenhum
código de produção mudou aqui. Este documento registra a superfície e os
consumidores atuais de `cli/asb/lifecycle.py`, `cli/asb/auth.py` e
`cli/asb/doctor.py`, e o tamanho medido de cada um, para a Tarefa 6 comparar
"antes" contra "depois" da decomposição. Nomes e consumidores apenas — nenhuma
credencial, variável de ambiente ou saída bruta de fornecedor.

A rede de segurança comportamental (contratos de CLI, JSON, precedência de
código de saída, ordem dos checks do `doctor`) está em
`tests/unit/test_public_contracts.py`, não neste documento.

## 1. Tamanho medido (`wc -lw`)

| Módulo | Linhas | Palavras |
| :--- | ---: | ---: |
| `cli/asb/lifecycle.py` | 1231 | 5498 |
| `cli/asb/auth.py` | 1180 | 6058 |
| `cli/asb/doctor.py` | 683 | 2752 |
| **Σ (os três)** | **3094** | **14308** |

Medido em `refactor/module-decomposition`, antes de qualquer commit da
Tarefa 1 (a própria Tarefa 1 não adiciona linhas a estes três arquivos).

## 2. Superfície de topo, por AST (`ast.parse`, corpo do módulo)

### 2.1 `cli/asb/lifecycle.py`

**Funções (35):** `names`, `ensure_ssh_key`, `ensure_credentials_volume`,
`ensure_credential_dirs`, `_volume_mountpoint`, `_mkdir_private`,
`warn_about_legacy_credential_layout`, `credential_mount_args`,
`ensure_session_volume`, `session_mount_args`, `ensure_toolcache_volume`,
`build_proxy`, `build`, `_get_container_id`, `_origin_of`,
`_sweep_containers`, `start_services`, `start_forwarder`,
`discover_mise_dirs`, `_run_mise_installs`, `_current_revision`,
`ensure_runtime`, `prepare_workspace`, `up`, `_up`, `emit`, `down`,
`_require_workspace`, `suspend`, `resume`, `reload_allowlist`, `pull`,
`purge`, `login`, `list_workspaces`.

**Classes (1):** `WorkspaceTransaction`.

**Constantes (10):** `IMAGE`, `PROXY_IMAGE`, `PROXY_PORT`, `SSH_KEY`,
`CREDENTIALS_VOLUME`, `TOOLCACHE_VOLUME`, `CREDENTIAL_DIRS`,
`LEGACY_ROOT_CREDENTIAL_FILES`, `SESSION_STATE_DIRS`, `PRUNED_DIRS`.

Nota: `check_keyring_service` (chamado por `doctor.py`) não é definido aqui —
`lifecycle.py` o reexpõe a partir de `cli/asb/keyring.py`. A lista de
"superfícies atuais" do brief (item 4 do contexto da Tarefa 1) o cita junto
dos símbolos de `lifecycle.py`; fica registrado aqui que sua origem real é
`keyring.py`.

### 2.2 `cli/asb/auth.py`

**Funções (25):** `_now_iso`, `parse_claude_status`, `parse_codex_status`,
`check_status`, `_aggregate_exit_code`, `status`, `login_command`,
`_lock_path`, `operator_lock`, `_client_name`, `_client_run_args`,
`verify_fresh_client`, `_run_interactive_login`, `_report_login`, `login`,
`_verify_command`, `_contains_code`, `_agy_model_row`,
`_agy_models_output_valid`, `classify_verification`, `call_budget`,
`reset_call_budget`, `_spend_call`, `verify_client`, `verify`.

**Classes (2):** `AuthResult`, `LoginBusy`.

**Constantes (24):** `STATUS_COMMANDS`, `_INDIVIDUAL_PROVIDERS`,
`_PUBLIC_PROVIDERS`, `_RUNNING_CHECK_HOST_TIMEOUT`, `_EXEC_HOST_TIMEOUT`,
`_AUTHENTICATED_STATES`, `_ACCOUNT_MISSING_STATES`, `LOGIN_COMMANDS`,
`_LOGIN_ORDER`, `_SIGINT_EXIT`, `_VERIFY_PROMPT`,
`_VERIFY_EXPECTED_RESPONSE`, `_VERIFY_PROVIDER_TIMEOUT`,
`_VERIFY_EXEC_HOST_TIMEOUT`, `_NETWORK_MARKERS`, `_RATE_LIMIT_CODES`,
`_RATE_LIMIT_TEXT_MARKERS`, `_SERVICE_ERROR_CODES`,
`_SERVICE_ERROR_TEXT_MARKERS`, `_AUTH_EVIDENCE_MARKERS`,
`_AGY_MODEL_FAMILY`, `_AGY_MODEL_IDENTIFIER`, `_AGY_MODEL_NUMBER`,
`_CALL_BUDGET`.

Nota sobre `_PUBLIC_PROVIDERS`: inclui `"all"`; `"agy"` não tem entrada em
`STATUS_COMMANDS` (só `claude` e `codex` têm comando de status local
comprovado) — `check_status("agy")` devolve sempre `state="unknown"` sem
tocar podman (ver achado empírico em
`tests/unit/test_public_contracts.py::TestAuthJsonContract::test_status_all_never_reaches_zero_or_one_today`).

### 2.3 `cli/asb/doctor.py`

**Funções (12):** `_line`, `_host_version`, `_image_version`, `tool_drift`,
`check_workspace_egress`, `check_legacy_agent_container`, `_service_state`,
`check_project_dropin_absent`, `check_network_gate`,
`third_party_netns_producers`, `diagnose`, `doctor`.

**Classes:** nenhuma.

**Constantes (1):** `CONTEXT_TOOLS`.

## 3. Consumidores (linhas de import, `rg` sobre `cli/` e `tests/`)

Buscado com `rg -n '^\s*(from|import)\s.*\b<módulo>\b'`, incluindo imports
adiados (indentados, dentro de função) — vários dos três módulos importam uns
aos outros só dentro de funções para evitar ciclo no carregamento.

### 3.1 Consumidores de `lifecycle`

| Consumidor | Forma do import |
| :--- | :--- |
| `cli/asb-agent` | `from asb import install, lifecycle` (nível de módulo) |
| `cli/asb/auth.py` | `from . import keyring, lifecycle, podman, readiness` (nível de módulo) |
| `cli/asb/doctor.py` | `from .lifecycle import (CREDENTIALS_VOLUME, TOOLCACHE_VOLUME, IMAGE, check_keyring_service, names)` (nível de módulo) |
| `cli/asb/keyring.py` | `from .lifecycle import CREDENTIALS_VOLUME` / `from .lifecycle import IMAGE, ensure_credentials_volume` (**adiado**, dentro de função — evita ciclo com `lifecycle` importando `keyring`) |
| `cli/asb/readiness.py` | `from .lifecycle import SSH_KEY` / `from .lifecycle import check_keyring_service` / `from .lifecycle import names` (**adiado**, três pontos distintos) |
| `cli/asb/runtime/connection.py` | `from .. import lifecycle, podman` (**adiado**, dentro de `resolve_connection`) |
| `cli/asb/runtime/sandbox.py` | `from .. import lifecycle` (**adiado**, quatro pontos distintos — mesmo padrão de `resolve_connection`) |
| `tests/unit/test_lifecycle.py` | nível de módulo e por-teste, `cli.asb.lifecycle` (import direto do pacote `cli`, não via `sys.path` de `cli/`) |
| `tests/unit/test_auth.py`, `test_broker.py`, `test_doctor.py`, `test_login_flow.py` | `from asb import lifecycle` (nível de módulo ou por-teste) |
| `tests/unit/test_staging.py` | `from asb.lifecycle import CREDENTIAL_DIRS, SESSION_STATE_DIRS` (por-teste) |
| `tests/integration/test_session_lifecycle.py`, `test_startup_auth.py`, `test_tui_acceptance.py`, `test_worktree_finish.py` | `from asb import lifecycle` (nível de módulo) |
| `tests/test-lifecycle.sh`, `tests/test-keyring-service.sh` | shell, fora do escopo AST |

### 3.2 Consumidores de `auth`

| Consumidor | Forma do import |
| :--- | :--- |
| `cli/asb-agent` | `from asb.auth import login as auth_login / status as auth_status / verify as auth_verify` (nível de módulo, três bindings nomeados) |
| `cli/asb/lifecycle.py` | `from . import auth` (**adiado**, dentro de `login()` — o ciclo inverso de `auth.py` importar `lifecycle` no nível de módulo) |
| `tests/unit/test_auth_status.py`, `test_login_flow.py` | `from asb import auth` |
| `tests/unit/test_auth_verify.py` | `from asb import auth, readiness` / `from asb.auth import AuthResult` |
| `tests/integration/test_provider_auth.py` | `from asb import auth` |
| `tests/integration/test_startup_auth.py` | `from asb import auth, keyring, lifecycle, readiness` |
| `tests/test-auth.sh` | shell, fora do escopo AST |

Ciclo `lifecycle.py` ⇄ `auth.py`: `auth.py` importa `lifecycle` no nível de
módulo (`from . import keyring, lifecycle, podman, readiness`);
`lifecycle.py` importa `auth` só dentro de `login()`. Qualquer Tarefa que mova
metade de um lado sem mover o outro precisa preservar essa assimetria
(import adiado no lado que fecharia o ciclo) ou vai quebrar o carregamento.

### 3.3 Consumidores de `doctor`

| Consumidor | Forma do import |
| :--- | :--- |
| `cli/asb-agent` | `from asb.doctor import doctor` (nível de módulo) |
| `tests/unit/test_doctor.py` | `from asb import doctor as doc_mod` |
| `tests/test-doctor.sh` | shell, fora do escopo AST |

`doctor.py` não é importado por `lifecycle.py` nem por `auth.py` — é
consumidor puro de ambos (via `from . import install, podman` e via
`from .lifecycle import (...)`), nunca consumido de volta. Das três é a
que tem menos dependentes a preservar.

## 4. Contratos observáveis congelados (resumo; ver o teste para o valor exato)

- **Comandos de topo registrados** (`cli/asb-agent build_parser()`): `up`,
  `down`, `suspend`, `resume`, `reload-allowlist`, `pull`, `connect`,
  `purge`, `build`, `login`, `auth`, `doctor`, `list`, `install-guards`,
  `install-broker`, `project`, `session`, `tui` (18 comandos).
- **Subcomandos aninhados**: `auth` → `status`, `verify`; `project` → `add`;
  `session` → `list`, `start`, `attach`, `stop`, `resume`.
- **`ConnectionInfo.lifecycle_payload`** (a linha que `lifecycle.emit()`
  imprime para o Orca): chaves `{workspace, port, user, project_root}`.
- **`auth status --json`**: chaves
  `{schemaVersion, workspace, checkedAt, results}`.
- **`auth verify --json`**: chaves
  `{schemaVersion, workspace, checkedAt, callBudget, results}`.
- **`doctor --json`**: chaves
  `{schemaVersion, healthy, infrastructure, providers}`, com
  `infrastructure.checks` nesta ORDEM (quando `podman` é detectado):
  `podman_installed`, `podman_version`, `python_version`, `git_installed`,
  `image`, `credentials_volume`, `toolcache_volume`, `keyring_service`,
  `project_dropin_absent`, `network_gate`, `netns_producers_third_party`,
  `guard_claude`, `guard_codex`, `guard_agy`, `cli_guard`, `docker_broker`,
  seguidos por até dois `drift_<tool>` opcionais (`rtk`, `graphify` — só se
  o host tiver a ferramenta) e pela lista de `workspaces`.
- **Precedência de código de saída agregado** (`_aggregate_exit_code` em
  `auth.py`, e o `except` genérico de `main()` em `cli/asb-agent`):
  infraestrutura/desconhecido → `2`; conta ausente → `1`; saudável → `0`;
  interrupção (`KeyboardInterrupt`) → `130`, com `2 > 1 > 0` de precedência
  quando resultados de múltiplos fornecedores se misturam.
- **`doctor()` não usa `2` por conta própria**: devolve `0 if healthy else 1`
  sempre; `2` só aparece se uma exceção não tratada escapar de `diagnose()`
  até o `except` genérico de `main()`.

Cada um destes é uma asserção em
`tests/unit/test_public_contracts.py` — este documento resume, o teste é a
fonte de verdade executável.

## 5. Divergências do brief encontradas (achado, não requisito)

O brief da Tarefa 1 (Passo 1) dá como exemplo ilustrativo
`set(auth_report) == {"schemaVersion", "checkedAt", "results"}` e
`set(doctor_report) == {"schemaVersion", "checkedAt", "checks", "summary"}`.
O código real, hoje, produz chaves diferentes em ambos (seção 4 acima). Os
testes em `test_public_contracts.py` congelam o comportamento REAL — essa é
a instrução do próprio brief para o caso de exit codes (§6 do briefing da
Tarefa 1: "se o código discordar desses números, reporte como preocupação em
vez de mudar código de produção"), aplicada aqui à mesma lógica para chaves
JSON. Nenhum código de produção foi alterado para tentar fazer a realidade
bater com o exemplo do brief.
