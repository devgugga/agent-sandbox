# Module decomposition — final validation — 2026-09-17

Task 6 of the plan `2026-09-17-agent-sandbox-module-decomposition`: the
cleanup task. This document is the "after" measurement, comparing against
`docs/validation/2026-09-17-module-decomposition-baseline.md` (the "before").
All sizes below are measured at this task's own HEAD (`wc -lw`), not copied
from any earlier report — Task 6 itself deletes code, so the numbers in
`deferred-items.md` §"Measured sizes" (taken at `54d9688`, before this task's
edits) are already stale by 16 lines in `lifecycle.py`.

## 1. Size: before → after

| Module | Lines (before) | Lines (after) | Words (after) |
| :--- | ---: | ---: | ---: |
| `cli/asb/lifecycle.py` | 1231 | **585** | 2743 |
| `cli/asb/auth.py` | 1180 | **787** | 3901 |
| `cli/asb/doctor.py` | 683 | **144** | 568 |
| **Σ (the three original modules)** | **3094** | **1516** | **7212** |

The three original modules went from 3094 lines combined (pre-Task-1
baseline) to 1516 (this task's HEAD) — a 51% reduction, not a claimed target
number invented in advance. `lifecycle.py` alone dropped a further 16 lines
in this task (601 → 585) from deleting two dead wrappers (§3).

### New domain modules created by Tasks 2–5 (measured at this task's HEAD)

| Module | Lines | Words |
| :--- | ---: | ---: |
| `cli/asb/agents/base.py` | 571 | 2926 |
| `cli/asb/agents/claude.py` | 149 | 692 |
| `cli/asb/agents/codex.py` | 318 | 1709 |
| `cli/asb/agents/antigravity.py` | 174 | 1046 |
| `cli/asb/runtime/storage.py` | 296 | 1768 |
| `cli/asb/runtime/transaction.py` | 89 | 384 |
| `cli/asb/runtime/workspace.py` | 734 | 2812 |
| `cli/asb/runtime/sandbox.py` | 398 | 1848 |
| `cli/asb/diagnostics/checks.py` | 629 | 2675 |
| `cli/asb/diagnostics/report.py` | 156 | 903 |

`runtime/sandbox.py` was not one of the three original modules and existed
before this plan; it is listed because Task 6's must-do item 3 (§4) touches
it. `checkouts/`, `projects/`, `sessions/`, `interfaces/` and `workspace.py`
are pre-existing packages this plan did not decompose and are out of scope
for this report.

## 2. Module map: responsibility, public surface, consumers, tests

### 2.1 `cli/asb/lifecycle.py` — CLI-facing workspace facade

**Responsibility:** owns `up`, `down`, `suspend`, `resume`,
`reload_allowlist`, `pull`, `purge`, `list_workspaces`, `build` — the
printing and exit-code policy for all of them — and delegates the heavy
lifting to the domain modules below.

**Public symbols (selected):** `names`, `ensure_ssh_key`, `build`,
`prepare_workspace` (thin, delegates to `WorkspaceRuntime().prepare(...)`),
`up`, `emit`, `down`, `suspend`, `resume`, `reload_allowlist`, `pull`,
`purge`, `list_workspaces`, `ensure_runtime`. Plus a stable re-export block
(§3) of names now owned by `keyring.py` and `runtime/storage.py`.

**Direct consumers:** `cli/asb-agent` (`lifecycle.build/up/down/suspend/
resume/reload_allowlist/pull/purge/list_workspaces`); `cli/asb/auth.py`
(`lifecycle.names`, `lifecycle.IMAGE`, `lifecycle.SSH_KEY`, keyring/storage
re-exports); `cli/asb/keyring.py`, `cli/asb/readiness.py`,
`cli/asb/runtime/connection.py`, `cli/asb/runtime/sandbox.py`,
`cli/asb/runtime/storage.py` (deferred import, for `names()`),
`cli/asb/doctor.py` (`check_keyring_service` re-export only).

**Focused tests:** `tests/unit/test_lifecycle.py`, `test_broker.py`,
`test_login_flow.py`, `tests/unit/test_public_contracts.py` (frozen
contracts), `tests/test-lifecycle.sh`, `tests/test-transaction.sh`,
`tests/test-reload-allowlist.sh`.

### 2.2 `cli/asb/auth.py` — provider account orchestration

**Responsibility:** the three auth questions (status, login, verify) —
locking, the ephemeral client's lifecycle, aggregate exit code and
sanitized rendering. Holds no provider-specific command construction
itself (moved to drivers in Task 2).

**Public symbols:** `driver_for`, `check_status`, `status`, `login`,
`operator_lock`, `LoginBusy`, `verify_fresh_client`, `verify_client`,
`verify`, `call_budget`, `reset_call_budget`, `AuthResult` (re-exported
from `agents/base.py` — `auth.py` constructs it throughout its own
functions, so this is a normal import, not a dead re-export; see §3).

**Direct consumers:** `cli/asb-agent` (`auth.login/status/verify`, three
named bindings); `cli/asb/lifecycle.py` (deferred import inside the old
`login()` wrapper — now gone, see §3, so this edge is removed);
`tests/unit/test_auth_status.py`, `test_auth_verify.py`,
`test_login_flow.py`; `tests/integration/test_provider_auth.py`,
`test_startup_auth.py`; `tests/test-auth.sh`.

**Focused tests:** `tests/unit/test_auth.py`, `test_auth_status.py`,
`test_auth_verify.py`, `test_login_flow.py`, `tests/test-auth.sh`,
`tests/test-keyring-service.sh`.

**Residual provider-specific branches (must-record item, §4).**

### 2.3 `cli/asb/doctor.py` — diagnostic composition only

**Responsibility:** calls `diagnose()` (collects `CheckResult`s from
`diagnostics/checks.py` in a fixed order, plus the one inline
`keyring_service` case, kept inline deliberately per ruling R8/R27),
renders once via `diagnostics/report.py`, returns the aggregate exit code.
Contains no check logic and no rendering logic of its own.

**Public symbols:** `diagnose`, `doctor`.

**Direct consumers:** `cli/asb-agent` (`from asb.doctor import doctor`);
`tests/unit/test_doctor.py`; `tests/test-doctor.sh`.

**Focused tests:** `tests/unit/test_doctor.py` (end-to-end `doctor()`
composition and rendering, distinct from the per-check unit tests below),
`tests/unit/test_diagnostic_checks.py`, `test_diagnostic_report.py`,
`tests/test-doctor.sh`.

### 2.4 `cli/asb/agents/base.py` + `{claude,codex,antigravity}.py` — provider drivers

**Responsibility:** `base.py` holds the shared `AuthResult` type, the
`AgentDriver` ABC (session commands `launch`/`resume`, the auth methods
`parse_auth_status`/`login_argv`/`verify_argv` — **now `@abstractmethod`,
Task 6 must-do item 1, §4** — and the shared
`classify_verification` pipeline), plus session-evidence capture. Each of
`claude.py`/`codex.py`/`antigravity.py` supplies only the fields and
methods specific to its provider.

**Public symbols:** `AgentDriver`, `AuthResult`, `LaunchCommand`,
`AgentAvailability`, `SessionEvidence`, `ResumeUnsupported`,
`ClaudeDriver`, `CodexDriver`, `AntigravityDriver`.

**Direct consumers:** `cli/asb/auth.py` (`DRIVERS` registry); `cli/asb/
interfaces/sessions.py`, `cli/asb/sessions/manager.py` (session commands);
`tests/unit/test_agent_drivers.py`, `test_auth_verify.py`,
`test_login_flow.py`; `tests/integration/test_session_lifecycle.py`,
`test_tui_acceptance.py` (test-only `AgentDriver` subclasses, fixed in
this task — see §4).

**Focused tests:** `tests/unit/test_agent_drivers.py` (188 tests),
`tests/unit/test_auth_verify.py`, `test_login_flow.py`.

### 2.5 `cli/asb/runtime/storage.py` — credential/session/toolcache volume ownership

**Responsibility:** the five volume entry points (`ensure_credentials_
volume`, `ensure_credential_dirs`, `credential_mount_args`, `ensure_
session_volume`, `session_mount_args`, `ensure_toolcache_volume`) plus
`RuntimeStorage`, the injectable boundary `lifecycle.prepare_workspace`
uses. `volume_mountpoint` (new in this task, §4 must-do item 3) is the
public accessor for the module's own private `_volume_mountpoint`.

**Direct consumers:** `cli/asb/lifecycle.py` (re-export block, §3),
`cli/asb/runtime/sandbox.py` (`volume_mountpoint`), `cli/asb/runtime/
workspace.py` (`RuntimeStorage`).

**Focused tests:** `tests/unit/test_runtime_storage.py`,
`test_login_flow.py` (session isolation), `test_runtime_connection.py`
(`TestSessionVolumeMountpoint`, exercises the new public accessor
end-to-end through `podman.out`).

### 2.6 `cli/asb/runtime/transaction.py` — creation-rollback ledger

**Responsibility:** `WorkspaceTransaction` — records every resource `up`
creates so a failed first creation can roll back exactly what it made.

**Direct consumers:** `cli/asb/lifecycle.py` (`up`), `cli/asb/runtime/
workspace.py` (`WorkspaceRuntime.prepare`), `cli/asb/runtime/storage.py`
(type-only import, `ensure_session_volume`).

**Focused tests:** `tests/unit/test_runtime_transaction.py`,
`tests/test-transaction.sh`.

### 2.7 `cli/asb/runtime/workspace.py` — workspace preparation and orchestration

**Responsibility:** `WorkspaceRuntime` — `prepare`, `start`, `suspend`,
`resume`, `remove_resources`; `build_proxy`, `start_services`,
`start_forwarder` at module level. The implementation `lifecycle.
prepare_workspace` used to hold directly, moved here in Task 4.

**Direct consumers:** `cli/asb/lifecycle.py` (facade calls), `cli/asb/
runtime/sandbox.py` (`layout_for` import), `cli/asb/projects/registry.py`.

**Focused tests:** `tests/unit/test_workspace_runtime.py`.

**Intentionally large (734 lines):** `_write_manifest` (13 positional
parameters) and `_create_agent_container` (12) are the seam where a future
edit could transpose two arguments (deferred item 14, no action — style,
not correctness). Not split further in this task: doing so would move
behavior, which is out of this task's mandate ("this task deletes, it does
not move behavior").

### 2.8 `cli/asb/diagnostics/checks.py` + `report.py` — diagnostic data and rendering

**Responsibility:** `checks.py` collects each `CheckResult` (data only,
never prints); `report.py` renders text/JSON and owns the exit-code
policy (`aggregate_exit_code`, `text_exit_code`).

**Direct consumers:** `cli/asb/doctor.py` (both), `cli/asb/diagnostics/
report.py` (imports `checks.CheckResult` for typing).

**Focused tests:** `tests/unit/test_diagnostic_checks.py`,
`test_diagnostic_report.py`.

**Intentionally large (`checks.py`, 629 lines):** houses 20 independent
`check_*` probes plus `collect_workspaces`; each probe is small and
focused, the file is large because there are many of them, per deferred
item 18 (no action — style, not correctness).

**Known defect, preserved deliberately (must-record item, §4):** `report.py`
carries both `aggregate_exit_code` and `text_exit_code` because `doctor
--json` and text-mode `doctor` disagree on the exit code when
`network_gate` fails.

## 3. The `lifecycle.py` re-export block: kept, not swept

`lifecycle.py` still imports and re-exports names it no longer defines
(`KEYRING_*`, `ensure_keyring_*`, `check_keyring_service`,
`CREDENTIALS_VOLUME`, `TOOLCACHE_VOLUME`, `CREDENTIAL_DIRS`,
`SESSION_STATE_DIRS`, `_volume_mountpoint`, `ensure_credentials_volume`,
`ensure_session_volume`, `credential_mount_args`, `session_mount_args`,
`ensure_toolcache_volume`, `WorkspaceTransaction`, `WorkspaceRuntime`,
`build_proxy`, `start_forwarder`, `start_services`). This is deferred
item 2 (must-act): the block's old comment called these reexports
"temporarios" (misleading — it invited a future sweep to delete them). Task
6 verified each of the four named consumers still reads at least one name
through `lifecycle.X` rather than the owning module directly:

- **`auth.py`** — `lifecycle.KEYRING_BUS`, `lifecycle.ensure_credentials_
  volume()`, `lifecycle.ensure_keyring_runtime_volume()`, `lifecycle.
  credential_mount_args(home)`, `lifecycle.ensure_keyring_service(...)`.
- **`keyring.py`** — `from .lifecycle import CREDENTIALS_VOLUME` and
  `from .lifecycle import IMAGE, ensure_credentials_volume` (both deferred
  imports, to avoid the `keyring.py` ⇄ `lifecycle.py` cycle).
- **`doctor.py`** — `from .lifecycle import check_keyring_service` (the one
  case `test_public_contracts.py` patches by that exact module path; Task 6
  did not move this call site, so the permitted `mock.patch` string
  exception in the task brief was not exercised).
- **`staging.py`** — imports nothing from `lifecycle` (doing so would close
  a cycle, since `lifecycle.py` imports `staging.py`), but duplicates
  `CREDENTIAL_DIRS`/`SESSION_STATE_DIRS` locally, and a parity test compares
  the local copy against `lifecycle.CREDENTIAL_DIRS`/`lifecycle.
  SESSION_STATE_DIRS` (the same names reexported here) to prevent drift.

The comment in `lifecycle.py` was rewritten (surgical wording fix only) to
name these four consumers instead of calling the block "temporarios", so a
future wrapper sweep does not delete them by mistake. No name in the block
was removed.

## 4. The three must-do deferred items — what Task 6 did

1. **`agents/base.py` — promoted `parse_auth_status`, `login_argv`,
   `verify_argv` to `@abstractmethod`.** All three real drivers (`Claude
   Driver`, `CodexDriver`, `AntigravityDriver`) already implemented all
   three since Task 2, so no production driver was affected. Two **test**
   driver subclasses were affected and fixed in this task:
   `HarmlessDriver` in `tests/integration/test_session_lifecycle.py` and
   `_Harmless`/`CodexFake`/`ClaudeFake`/`Completing` in `tests/integration/
   test_tui_acceptance.py` — neither implemented the three auth methods,
   so both became uninstantiable the moment the abstractmethod promotion
   landed (confirmed empirically, see the task report's red-before-green
   section). Both were fixed by adding explicit `NotImplementedError`
   stubs for the three methods (never called by session/TUI tests), the
   same shape the base class used to have as its default. The `provider:
   ClassVar[str]` annotation-only field mentioned as a "reinforcing
   symptom" in the deferred item was left untouched: the deferred item
   names one concrete action ("promote three stubs to `@abstractmethod`"),
   and `provider` is not one of the three; giving it a synthetic default
   would not express anything true about the type and was judged out of
   this item's scope.
2. **`lifecycle.py` re-export comment reworded** — see §3.
3. **`runtime/sandbox.py:99` no longer reaches into `storage.
   _volume_mountpoint`** (a private symbol of a sibling module). Added
   `storage.volume_mountpoint(vol)`, a public one-line wrapper around the
   existing private `_volume_mountpoint`, and repointed the one call site
   in `runtime/sandbox.py::session_volume_mountpoint`. No behavior change:
   same `podman volume inspect` call, same error handling.

## 5. Must-record items (honest, not fixed)

4. **Residual provider-specific branches remain in `auth.py`** after Task
   2: `verify_fresh_client` special-cases `provider == "agy"` to return
   `state="pending"` (no local status command exists for `agy` to check a
   fresh client against), and `login` prints an extra operator warning only
   `if name == "claude"` (the "Quick safety check" prompt). Both are
   pre-existing, outside the four-method driver-boundary scope Task 2
   migrated, and Task 6 makes no claim that `auth.py` has a fully clean
   provider boundary.
5. **Known pre-existing defect, deliberately preserved:** `doctor(as_
   json=True)` and `doctor()` (text) disagree on the exit code when the
   `network_gate` check fails. Measured against the pre-refactor code in
   Task 5: `gate_failed as_json=False: OLD=1 NEW=1`; `as_json=True: OLD=0
   NEW=0` — the divergence predates this plan and both encodings are
   preserved on purpose. This is why `diagnostics/report.py` carries both
   `aggregate_exit_code` (JSON path) and `text_exit_code` (text path)
   instead of one shared function. Fixing it is a behavior change and
   stays out of scope for this plan. Recorded in `docs/domains/sandbox/
   lifecycle.md` §8 as well, so an operator hitting it has somewhere to
   look.
6. **Commit `5a284ec`'s body carries a wrong subtest count** ("7 of 9 ...
   2 trivial"; the shipped suite has 10 cases and 3 would be trivial). The
   assertion itself is sound; only the count in that historical commit
   message is stale. Not rebased — `commit-conventions.md` §4 forbids a
   body claiming what the diff does not support, so it is recorded here
   per the deferred item's own instruction, rather than silently ignored.

## 6. Deferred coverage gaps and style items — untouched

Items 7–18 of `deferred-items.md` (coverage gaps in `diagnostics/checks.py`,
`runtime/workspace.py`, `diagnostics/report.py`, and the style/structure
items in `install.py`, `runtime/workspace.py`, `diagnostics/report.py`,
`diagnostics/checks.py`/`doctor.py`) were left exactly as found. None was
introduced by this plan; all were relocated pre-existing gaps its own
tasks' review rounds deferred by ruling. Task 6's brief instructs
"[t]riage at the final review, do not fix blind" for the coverage gaps and
"no action required" for the style items — this report does not reopen
either list.

## 7. Verification

Full command-by-command output, including tracebacks and red-before-green
proofs, is in `task-6-report.md` in this plan's `.superpowers/sdd/` folder.
Summary:

- `PYTHONPATH=cli python3 -m unittest discover -s tests/unit -v`: **1479
  tests, OK** (down from the 1481-test baseline at `54d9688` — 2 tests
  removed with the deleted `lifecycle.login` wrapper, §8).
- `PYTHONPATH=cli python3 -m unittest discover -s tests/integration -v`:
  Ran 53 tests, **FAILED (errors=3, skipped=1)**. The 3 errors
  (`test_session_lifecycle.py::test_start_list_attach_detach_and_stop_a_
  real_session`, and both methods of `test_tui_acceptance.py::
  TestTuiAcceptance`) are a pre-existing `AgentDriver.launch()` signature
  mismatch in two integration test doubles, confirmed byte-identical at
  the pre-Task-6 commit `54d9688` and unrelated to any file this task
  modifies (`cli/asb/sessions/manager.py`, `checkouts/`, `projects/` are
  all untouched). The 1 skip is the pre-existing, intentional
  `ASB_LIVE_AUTH=1`-gated live-provider test. Not fixed — out of this
  task's scope; see `task-6-report.md` §7/§10 for the full traceback
  evidence.
- `for test in tests/test-*.sh; do bash "$test"; done`: 13 of 16 suites
  fully green; all 5 suites the controller gave an expected baseline for
  (`test-recipe.sh` 39/0, `test-lifecycle.sh` 7/0, `test-transaction.sh`
  13/0, `test-doctor.sh` 15/0, `test-toolcache.sh` 22/0) match exactly.
  The 3 suites with failures (`test-agents-behind-proxy.sh` 9/1,
  `test-broker.sh` 9/1, `test-keyring-service.sh` 39/5) each have a
  pre-existing, unrelated root cause confirmed against `54d9688` (CLI
  version drift, Docker-socket environment behavior, and a shell test's
  Python one-liner missing `PYTHONPATH=cli` respectively) — full evidence
  in `task-6-report.md` §7.
- `/usr/bin/git diff --check`: clean, no output.

None of the three pre-existing failure categories above touches
`lifecycle.py`, `auth.py`, `doctor.py`, or any file in this task's diff;
each was confirmed unrelated by diffing the failing code path against
commit `54d9688` before this task began.

## 8. Tests removed in this task

`tests/unit/test_login_flow.py::TestLifecycleLoginReexport` (2 tests) was
deleted along with the `lifecycle.login()` wrapper it existed solely to
test (`test_lifecycle_login_delegates_to_auth_login`,
`test_lifecycle_no_longer_carries_the_dead_login_checks`). Both asserted
facts about the now-deleted wrapper itself (that it delegated to
`auth.login`, and that a historical dead table stayed removed); neither
covered a distinct caller path, failure branch, ownership rule or
user-visible contract that survives the wrapper's deletion — the CLI's
`login` subcommand calls `auth.login` directly (`cli/asb-agent` imports
`from asb.auth import login as auth_login`), and that path is already
covered by `tests/unit/test_login_flow.py`'s other login tests and
`tests/unit/test_cli_dispatch.py::test_login_is_registered_without_a_
workspace_argument`. No coverage was lost.

Two direct-call sites of the deleted `lifecycle._up()` alias were
repointed to `lifecycle.up()` (the function `_up` merely forwarded to) in
`tests/unit/test_broker.py` (2 call sites) and `tests/unit/test_lifecycle.py`
(1 import + 1 call site); these are not test deletions, since `_up` and
`up` are the same code path and the tests' assertions are unchanged.
