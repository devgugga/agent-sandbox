# Agent Sandbox Module Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the responsibility and context size of `lifecycle.py`,
`auth.py`, and `doctor.py` after the TUI rollout while preserving every public
CLI, recipe, runtime, and diagnostic contract.

**Architecture:** Move cohesive behavior behind the domain interfaces already
introduced by the TUI plan. Keep compatibility functions only at real import
boundaries, migrate callers in the same task, and remove each wrapper as soon
as its last consumer moves. Treat this as behavior-preserving extraction, not a
second runtime redesign.

**Tech Stack:** Python >= 3.11 standard library, `unittest`, rootless Podman >=
6.1, user systemd, Git, OpenSSH, and the existing Graphify project adapter.

**Spec:**
[`docs/superpowers/specs/2026-09-17-agent-sandbox-tui-design.md`](../specs/2026-09-17-agent-sandbox-tui-design.md),
especially sections 5, 13, and 14 Stage 6.

## Global Constraints

- This plan starts only after
  [`2026-09-17-agent-sandbox-tui.md`](2026-09-17-agent-sandbox-tui.md) has a
  passing acceptance report and the operator approves the rollout.
- Extractions preserve output text, JSON schemas, exit codes, subprocess argv,
  readiness order, transaction ownership, systemd behavior, Podman topology,
  mounts, credentials, and Orca recipe behavior.
- No task combines code movement with a new user-facing capability.
- A compatibility re-export is allowed only when a named current consumer
  requires it. The task lists that consumer and removes the re-export when the
  consumer moves.
- Unit tests import `asb_test_isolation` first. No unit test touches a real
  Podman volume, systemd unit, credential, SSH endpoint, or tmux server.
- Before each commit, run the focused tests, the complete unit suite,
  `bash tests/test-recipe.sh`, and `git diff --check`.
- Use `commit-curator` for every commit. Do not push. Pause Graphify for the
  plan and update it once after the final review.
- Reviewer gates use `regression-sentinel` and `test-shape-auditor`; the final
  report uses `claim-verifier`.

## Target file responsibilities

| File | Sole responsibility |
|---|---|
| `agents/base.py` | Shared driver protocols and result types |
| `agents/codex.py` | Codex launch, resume, auth status, and verification rules |
| `agents/claude.py` | Claude launch, resume, auth status, and verification rules |
| `agents/antigravity.py` | Antigravity launch, resume capability, auth, and verification rules |
| `auth.py` | Provider selection, aggregate exit code, login/status/verify orchestration |
| `runtime/storage.py` | Credential, session, and tool-cache volume creation and mounts |
| `runtime/transaction.py` | Ownership ledger and rollback for one workspace creation |
| `runtime/sandbox.py` | Compose workspace preparation, supervision, and readiness services |
| `lifecycle.py` | Stable public command façade: build/up/down/suspend/resume/purge/pull |
| `diagnostics/checks.py` | Structured checks without rendering |
| `diagnostics/report.py` | Text and schema 1 JSON rendering |
| `doctor.py` | Compose checks, render once, and return the aggregate exit code |

The target is responsibility-based. Do not create pass-through files merely to
meet the table. A destination must own behavior and have tests through its
public interface before code moves into it.

---

### Task 1: Freeze observable contracts before extraction

**Files:**
- Create: `tests/unit/test_public_contracts.py`
- Create: `docs/validation/2026-09-17-module-decomposition-baseline.md`

**Interfaces:**
- No new production interface.
- Produces a sanitized baseline for CLI commands, JSON keys, exit codes,
  lifecycle output, provider classifications, and doctor ordering.

- [ ] **Step 1: Capture public CLI and JSON contracts in tests**

Load `cli/asb-agent` through `SourceFileLoader`, inject service fakes, and assert
the registered commands plus nested `auth` and `session` commands. Snapshot
keys as sets, not serialized dictionary order:

```python
self.assertEqual(set(connection_payload),
                 {"workspace", "port", "user", "project_root"})
self.assertEqual(set(auth_report),
                 {"schemaVersion", "checkedAt", "results"})
self.assertEqual(set(doctor_report),
                 {"schemaVersion", "checkedAt", "checks", "summary"})
```

Assert aggregate exit precedence: infrastructure/unknown `2`, account absence
`1`, healthy `0`, and interruption `130`.

- [ ] **Step 2: Record current module surfaces**

Use AST to list top-level functions/classes and `rg` to list imports from
`lifecycle`, `auth`, and `doctor`. Store names and consumers in the validation
document; do not store credentials, environment dumps, or raw provider output.

- [ ] **Step 3: Run and commit the baseline**

```bash
python3 -m unittest discover -s tests/unit -p 'test_public_contracts.py' -v
python3 -m unittest discover -s tests/unit -v
bash tests/test-recipe.sh
git diff --check
```

Use `commit-curator` with title:

```text
✅ freeze public module contracts: decomposition baseline
```

---

### Task 2: Move provider-specific auth rules into agent drivers

**Files:**
- Modify: `cli/asb/agents/base.py`
- Modify: `cli/asb/agents/codex.py`
- Modify: `cli/asb/agents/claude.py`
- Modify: `cli/asb/agents/antigravity.py`
- Modify: `cli/asb/auth.py`
- Modify tests: `tests/unit/test_auth.py`
- Modify tests: `tests/unit/test_auth_status.py`
- Modify tests: `tests/unit/test_auth_verify.py`
- Modify tests: `tests/unit/test_login_flow.py`
- Modify tests: `tests/unit/test_agent_drivers.py`

**Interfaces:**
- Adds to `AgentDriver`: `parse_auth_status(completed) -> AuthResult`,
  `login_argv() -> tuple[str, ...]`, `verify_argv() -> tuple[str, ...]`, and
  `classify_verification(completed, network_state) -> AuthResult`.
- `auth.py` retains public `login`, `status`, `verify`, `AuthResult`, aggregate
  exit-code rules, sanitized rendering, operator locking, and client lifecycle.

- [ ] **Step 1: Move tests to the owning driver before moving code**

For each provider, place authenticated, unauthenticated, malformed, missing
binary, timeout, provider error, and network-unreachable cases in
`test_agent_drivers.py`. Keep orchestration tests in auth test files.

Example ownership boundary:

```python
result = ClaudeDriver().parse_auth_status(
    CompletedProcess(("claude",), 1, '{"loggedIn":false}', ""))
self.assertEqual(result.state, "unauthenticated")

with mock.patch.object(driver, "parse_auth_status") as parse:
    auth.check_status(driver, client="asb-test-client")
parse.assert_called_once()
```

- [ ] **Step 2: Confirm tests still pass before moving implementation**

The new driver tests initially import the existing parser functions explicitly.
Run them green to prove they characterize current behavior:

```bash
python3 -m unittest discover -s tests/unit -p 'test_agent_drivers.py' -v
python3 -m unittest discover -s tests/unit -p 'test_auth*.py' -v
```

- [ ] **Step 3: Move one provider at a time**

Move Claude, run focused tests, commit; move Codex, run focused tests, commit;
move Antigravity, run focused tests, commit. Each move changes `auth.py` to
dispatch through a driver map:

```python
DRIVERS: dict[str, AgentDriver] = {
    "claude": ClaudeDriver(),
    "codex": CodexDriver(),
    "agy": AntigravityDriver(),
}


def driver_for(provider: str) -> AgentDriver:
    try:
        return DRIVERS[provider]
    except KeyError as error:
        raise ValueError(f"unknown provider: {provider}") from error
```

Do not change raw commands or classifications while relocating them.

- [ ] **Step 4: Remove parser re-exports after consumer search is empty**

```bash
rg -n 'parse_(claude|codex|agy)_status|classify_verification|login_command' \
  cli tests
```

Delete an old symbol only after every result points to the owning driver or a
deliberate public orchestration function.

- [ ] **Step 5: Verify and commit each provider extraction**

For each of the three commits, run:

```bash
python3 -m unittest discover -s tests/unit -p 'test_agent_drivers.py' -v
python3 -m unittest discover -s tests/unit -p 'test_auth*.py' -v
python3 -m unittest discover -s tests/unit -p 'test_login_flow.py' -v
python3 -m unittest discover -s tests/unit -v
git diff --check
```

Use these curated titles:

```text
♻️ move Claude auth rules into its driver: provider boundary
♻️ move Codex auth rules into its driver: provider boundary
♻️ move Antigravity auth rules into its driver: provider boundary
```

---

### Task 3: Extract runtime storage ownership from lifecycle

**Files:**
- Create: `cli/asb/runtime/storage.py`
- Modify: `cli/asb/lifecycle.py`
- Create: `tests/unit/test_runtime_storage.py`
- Modify tests: `tests/unit/test_lifecycle.py`
- Modify tests: `tests/unit/test_login_flow.py`

**Interfaces:**
- Produces `RuntimeStorage` with `ensure_credentials()`, `credential_mounts()`,
  `ensure_sessions(workspace, transaction)`, `session_mounts()`, and
  `ensure_toolcache()`.
- Constants describing provider credential/session subdirectories move with
  the behavior.
- `lifecycle.py` receives one `RuntimeStorage` dependency in preparation paths.

- [ ] **Step 1: Copy behavior tests to the new interface**

Cover existing/missing volumes, directory modes, invalid mountpoints,
credential subdirectories, session subdirectories, transaction ownership,
legacy-layout warning, and exact mount argument ordering. All Podman and host
mountpoint access is mocked.

- [ ] **Step 2: Confirm tests characterize current behavior**

Initially instantiate a thin `RuntimeStorage` that delegates to existing
lifecycle functions. Run the new tests green, then inspect the diff to confirm
the tests assert outputs and ownership rather than only mock calls.

- [ ] **Step 3: Move implementation and update all consumers in one commit**

Move functions and constants without rewriting them. Keep temporary imports in
`lifecycle.py` only for current external test consumers, then migrate those
tests to `RuntimeStorage` and remove the imports before commit.

- [ ] **Step 4: Verify lifecycle and authentication paths**

```bash
python3 -m unittest discover -s tests/unit -p 'test_runtime_storage.py' -v
python3 -m unittest discover -s tests/unit -p 'test_lifecycle.py' -v
python3 -m unittest discover -s tests/unit -p 'test_login_flow.py' -v
python3 -m unittest discover -s tests/unit -v
bash tests/test-recipe.sh
git diff --check
```

- [ ] **Step 5: Commit the extraction**

Use `commit-curator` with title:

```text
♻️ extract workspace volume ownership: runtime storage
```

---

### Task 4: Extract transaction and sandbox orchestration

**Files:**
- Create: `cli/asb/runtime/transaction.py`
- Modify: `cli/asb/runtime/sandbox.py`
- Modify: `cli/asb/lifecycle.py`
- Create: `tests/unit/test_runtime_transaction.py`
- Create: `tests/unit/test_sandbox_runtime.py`
- Modify tests: `tests/unit/test_lifecycle.py`

**Interfaces:**
- Produces `WorkspaceTransaction` with the exact ownership ledger currently in
  lifecycle and idempotent `rollback()`.
- Produces `SandboxRuntime.prepare()`, `start()`, `suspend()`, `resume()`, and
  `remove_resources()`.
- `lifecycle.up/down/suspend/resume` remain public functions and compose the
  runtime with existing user-facing printing and exit-code policy.

- [ ] **Step 1: Move rollback tests to the transaction boundary**

Cover owned/unowned networks, containers, volumes, files, and systemd units;
partial rollback failures; reverse cleanup order; and repeated rollback. Assert
that pre-existing resources are never passed to a delete operation.

- [ ] **Step 2: Add runtime orchestration tests through injected services**

Represent collaborators with narrow protocols for Podman, supervisor,
readiness, storage, and connection. Test event order:

```python
self.assertEqual(events, [
    "host-ready", "prepare-clone", "create-network", "create-proxy",
    "create-agent", "write-manifest", "install-units", "start-target",
    "proxy-ready", "mise-install", "ports-ready", "ssh-ready",
])
```

Add a failure at every side-effecting event and assert rollback includes only
earlier resources owned by that transaction.

- [ ] **Step 3: Move `WorkspaceTransaction` without changing it**

Run transaction and lifecycle tests after the pure move. Commit this move
separately before changing orchestration.

- [ ] **Step 4: Move preparation in vertical slices**

Move network/proxy creation, agent creation, manifest writing, and supervision
as four individually tested slices. After each slice, run focused tests and
inspect subprocess argv. Do not change readiness timeouts or order.

- [ ] **Step 5: Leave lifecycle as a real façade**

The final `up()` remains responsible for the CLI contract: initialize the
transaction, call the runtime, print errors to stderr, emit connection JSON on
success, and roll back owned resources on exceptional failure. It must not
contain Podman argument construction after extraction.

- [ ] **Step 6: Verify and curate commits**

```bash
python3 -m unittest discover -s tests/unit -p 'test_runtime_transaction.py' -v
python3 -m unittest discover -s tests/unit -p 'test_sandbox_runtime.py' -v
python3 -m unittest discover -s tests/unit -p 'test_lifecycle.py' -v
python3 -m unittest discover -s tests/unit -v
bash tests/test-lifecycle.sh
bash tests/test-transaction.sh
bash tests/test-recipe.sh
git diff --check
```

Use `commit-curator` for the pure transaction move and each runtime slice, with
titles in this form:

```text
♻️ extract workspace rollback ledger: runtime transaction
♻️ extract sandbox resource preparation: runtime orchestration
```

---

### Task 5: Separate diagnostic checks from rendering

**Files:**
- Create: `cli/asb/diagnostics/__init__.py`
- Create: `cli/asb/diagnostics/checks.py`
- Create: `cli/asb/diagnostics/report.py`
- Modify: `cli/asb/doctor.py`
- Create: `tests/unit/test_diagnostic_checks.py`
- Create: `tests/unit/test_diagnostic_report.py`
- Modify tests: `tests/unit/test_doctor.py`

**Interfaces:**
- Produces frozen `CheckResult(name, state, evidence, remediation, details)`.
- Produces one function per current check in `checks.py`; each returns data and
  does not print.
- Produces `render_text(results) -> str`, `render_json(results) -> str`, and
  `aggregate_exit_code(results) -> int` in `report.py`.
- `doctor(root, as_json)` discovers inputs, runs checks in current order,
  renders once, and returns the aggregate code.

- [ ] **Step 1: Characterize check order and report schemas**

Move existing doctor expectations into report tests. Assert exact check names
and ordering, JSON key sets, exit precedence, multiline remediation rendering,
Unicode handling, and an empty check set as infrastructure failure rather than
healthy output.

- [ ] **Step 2: Extract rendering first**

Build `CheckResult` values directly in tests and move only formatting plus
aggregate exit policy. Keep check collection in `doctor.py` until all report
tests pass.

- [ ] **Step 3: Extract checks one group at a time**

Move host tools, Podman/runtime, workspace readiness, authentication, and
version checks as separate groups. Each check receives dependencies or a
runner; no check imports the TUI or writes stdout.

- [ ] **Step 4: Prove text/JSON parity and no duplicate probing**

Call doctor once with counting fakes and assert each expensive probe runs once,
then both renderers receive the same immutable results in separate tests.

- [ ] **Step 5: Verify and commit**

```bash
python3 -m unittest discover -s tests/unit -p 'test_diagnostic_*.py' -v
python3 -m unittest discover -s tests/unit -p 'test_doctor.py' -v
python3 -m unittest discover -s tests/unit -v
bash tests/test-doctor.sh
git diff --check
```

Use `commit-curator` with title:

```text
♻️ separate diagnostic checks and rendering: doctor
```

---

### Task 6: Remove obsolete compatibility surfaces

**Files:**
- Modify: `cli/asb/lifecycle.py`
- Modify: `cli/asb/auth.py`
- Modify: `cli/asb/doctor.py`
- Modify tests: affected `tests/unit/test_*.py`
- Update: `docs/domains/sandbox/lifecycle.md`
- Update: `docs/domains/sandbox/authentication.md`
- Create: `docs/validation/2026-09-17-module-decomposition.md`

**Interfaces:**
- No new interface.
- Retains only symbols used by `cli/asb-agent`, recipes, runtime helpers, or a
  documented public module contract.

- [ ] **Step 1: Build a live consumer inventory**

```bash
rg -n 'asb\.lifecycle|from .*lifecycle import|asb\.auth|from .*auth import|asb\.doctor|from .*doctor import' \
  cli recipes tests docs
```

Classify every result as production consumer, contract test, documentation, or
obsolete implementation-shaped test. Record the classification in the
validation report.

- [ ] **Step 2: Delete wrappers with no production consumer**

For each candidate, first change tests to enter the owning public interface,
run those tests green, then delete the wrapper and rerun. Keep no forwarding
function solely because an old test imports it.

- [ ] **Step 3: Replace duplicate implementation tests**

Remove tests that assert the same private command construction at both the old
and new boundary. Preserve behavior tests that cover a distinct caller path,
failure branch, ownership rule, or user-visible contract.

- [ ] **Step 4: Run complete verification and reviews**

```bash
python3 -m unittest discover -s tests/unit -v
python3 -m unittest discover -s tests/integration -v
for test in tests/test-*.sh; do bash "$test"; done
git diff --check
```

Run `regression-sentinel` and `test-shape-auditor` against the full plan diff.
Run `claim-verifier` against the validation report. Fix findings before the
final commit.

- [ ] **Step 5: Record the final module map**

The validation report lists each target module, its public symbols, direct
consumers, focused tests, and measured line/word counts before and after. It
must state any responsibility that intentionally remains in a large file and
name the real consumer that requires it.

- [ ] **Step 6: Commit cleanup and documentation**

Use `commit-curator` with title:

```text
♻️ remove obsolete module wrappers: domain boundaries
```

- [ ] **Step 7: Synchronize Graphify once**

```bash
graphify update .
git diff --check
```

Commit strictly `graphify-out/**` with title `🕸️ sync knowledge graph`, then
resume the Graphify hook.

---

## Completion evidence

The decomposition is complete when all public contract tests and existing
suites pass, the three original modules delegate to cohesive domain modules,
no compatibility wrapper lacks a production consumer, and the validation
report demonstrates reduced line and word counts without claiming a target
that the diff did not achieve.

Rollback consists of reverting the latest extraction commit. Because this plan
does not alter registry schemas, container topology, credentials, worktrees, or
provider session volumes, rollback does not require migration or cleanup of
operator data.
