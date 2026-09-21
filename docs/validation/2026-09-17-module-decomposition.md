# Module decomposition — final validation — 2026-09-17

Task 6 of the plan `2026-09-17-agent-sandbox-module-decomposition`: the
cleanup task. This document is the "after" measurement, comparing against
`docs/validation/2026-09-17-module-decomposition-baseline.md` (the "before").
All sizes below are measured at this task's own HEAD (`wc -lw`), not copied
from any earlier report — Task 6 itself deletes code, so the numbers in
`deferred-items.md` §"Measured sizes" (taken at `54d9688`, before this task's
edits) are already stale by 16 lines in `lifecycle.py`.

## 1. Size: before → after

Re-measured at the end of the fix wave that followed the whole-branch
review (this task made further deletions and additions after the first
pass — see §3 for the code-size-relevant changes — so these numbers
supersede the first pass's).

| Module | Lines (before) | Lines (after) | Words (after) |
| :--- | ---: | ---: | ---: |
| `cli/asb/lifecycle.py` | 1231 | **599** | 2900 |
| `cli/asb/auth.py` | 1180 | **787** | 3901 |
| `cli/asb/doctor.py` | 683 | **144** | 568 |
| **Σ (the three original modules)** | **3094** | **1530** | **7369** |

The three original modules went from 3094 lines combined (pre-Task-1
baseline) to 1530 (this task's final HEAD) — a 51% reduction, not a
claimed target number invented in advance. `lifecycle.py` itself moved
601 → 585 → 599 lines across this task's two passes: the first pass net
-16 (two dead wrappers deleted); this fix wave net +14 despite deleting
twelve more dead re-exports and their explanatory comment lines, because
it added a new public `origin_of()` accessor (§3, ~9 lines) and a
substantially longer, re-derived explanatory comment for the re-export
block (§3) — a large net addition of documentation and one new function
outweighing a larger deletion, not a regression against the "delete, not
move behavior" mandate: no behavior moved, the net line count is honest
about the doc-comment cost of getting the re-export inventory right.

### New/touched domain modules (measured at this task's final HEAD)

| Module | Lines | Words |
| :--- | ---: | ---: |
| `cli/asb/agents/base.py` | 571 | 2926 |
| `cli/asb/agents/claude.py` | 149 | 692 |
| `cli/asb/agents/codex.py` | 318 | 1709 |
| `cli/asb/agents/antigravity.py` | 174 | 1046 |
| `cli/asb/runtime/storage.py` | 296 | 1768 |
| `cli/asb/runtime/transaction.py` | 89 | 384 |
| `cli/asb/runtime/workspace.py` | 745 | 2913 |
| `cli/asb/runtime/sandbox.py` | 398 | 1848 |
| `cli/asb/diagnostics/checks.py` | 630 | 2678 |
| `cli/asb/diagnostics/report.py` | 156 | 903 |
| `cli/asb/staging.py` | 249 | 1071 |

`runtime/workspace.py` grew from 734 to 745 lines (import + docstring
changes, §3: `from .. import keyring` and the explanation of why);
`diagnostics/checks.py` grew from 629 to 630 (one import line moved to a
new line, §3). `runtime/sandbox.py` and `staging.py` were not among the
three original modules and existed before this plan; they are listed
because this fix wave's items 3 and 5 touch them (a public `origin_of`
consumer and a corrected docstring, respectively — neither module's own
size changed meaningfully: `sandbox.py` is still 398 lines, unchanged by
the one-line `_origin_of` → `origin_of` call-site edit).
`checkouts/`, `projects/`, `sessions/`, `interfaces/` and `workspace.py`
(the pre-existing top-level one, distinct from `runtime/workspace.py`)
are pre-existing packages this plan did not decompose and are out of
scope for this report.

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

**Intentionally large (745 lines):** `_write_manifest` (13 positional
parameters) and `_create_agent_container` (12) are the seam where a future
edit could transpose two arguments (deferred item 14, no action — style,
not correctness). Not split further in this task: doing so would move
behavior, which is out of this task's mandate ("this task deletes, it does
not move behavior").

### 2.8 `cli/asb/diagnostics/checks.py` + `report.py` — diagnostic data and rendering

**Responsibility:** `checks.py` collects each `CheckResult` (data only,
never prints); `report.py` renders text/JSON. The exit-code policy is
**split, not owned by `report.py` alone** (final review finding, corrected
here): `report.py` decides the TEXT exit code (`text_exit_code`) and
supplies `aggregate_exit_code`, but the JSON exit code itself is decided
in `doctor.py`'s `doctor()` (`return 0 if diag["healthy"] else 1`,
`doctor.py:141`) and `diagnose()`'s `infra_healthy` computation
(`doctor.py:92`, which ANDs `report.aggregate_exit_code(check_results) ==
0` with every workspace's `healthy` flag) — see deferred item 16 (no
action; it is the exact split this report documents, not a defect this
plan introduces).

**Direct consumers:** `cli/asb/doctor.py` (both), `cli/asb/diagnostics/
report.py` (imports `checks.CheckResult` for typing).

**Focused tests:** `tests/unit/test_diagnostic_checks.py`,
`test_diagnostic_report.py`.

**Intentionally large (`checks.py`, 630 lines):** houses 20 independent
`check_*` probes plus `collect_workspaces`; each probe is small and
focused, the file is large because there are many of them, per deferred
item 18 (no action — style, not correctness).

**Known defect, preserved deliberately (must-record item, §4):** `report.py`
carries both `aggregate_exit_code` and `text_exit_code` because `doctor
--json` and text-mode `doctor` disagree on the exit code when
`network_gate` fails.

## 3. The `lifecycle.py` re-export block: re-derived, not trusted on inheritance

**Correction to this report's own first draft.** The original version of
this section (written during the first Task 6 pass) named four "production
consumers" of the re-export block, one of which — `staging.py` — was
wrong, and it omitted three real consumers a subsequent whole-branch review
found by re-deriving the inventory from scratch instead of trusting the
inherited four-name list. This section is corrected in place, per the same
review's finding: "the plan forbids claiming a target the diff did not
achieve — the honest report is the deliverable."

**What changed in this fix wave, repo-wide search before every deletion
(not the reviewer's list taken on trust):**

- **Ten re-exports deleted** as genuinely dead (zero production consumer,
  zero test consumer via `lifecycle.X`): `LEGACY_ROOT_CREDENTIAL_FILES`,
  `_inspect_keyring_container`, `_keyring_mount_contract_issue`,
  `_mkdir_private`, `_volume_mountpoint`, `build_proxy`, `start_services`,
  `ensure_toolcache_volume`, `warn_about_legacy_credential_layout`, and
  `start_forwarder` — the last one had a real test consumer
  (`tests/unit/test_lifecycle.py::TestStartForwarder`, 3 tests) that this
  task's own re-verification found and repointed to
  `cli.asb.runtime.workspace` (the owning module) before deleting the
  re-export, per Brief Step 2's "first change tests to enter the owning
  public interface, run those tests green, then delete the wrapper".
- **Two more re-exports removed as a consequence of this wave's other
  fixes, not from the reviewer's original list:** `TOOLCACHE_VOLUME`
  (orphaned once `diagnostics/checks.py` was repointed below to import
  `CREDENTIALS_VOLUME`/`TOOLCACHE_VOLUME` from `runtime.storage` directly)
  and `CREDENTIAL_DIRS`/`SESSION_STATE_DIRS` (below — `staging.py`'s
  parity test and two `test_login_flow.py` tests were the only remaining
  readers, both repointed to `runtime.storage`, the owning module).
- **`staging.py` was never a real consumer** — it references
  `lifecycle.CREDENTIAL_DIRS`/`SESSION_STATE_DIRS` only in a docstring
  comment and deliberately duplicates the values locally (to avoid a real
  import cycle: `lifecycle.py` → `runtime/workspace.py` → `staging.py` →
  `lifecycle.py`, since `staging.py` is imported by `runtime/workspace.py`,
  not the other way around). The actual reader was
  `tests/unit/test_staging.py::test_the_refused_destinations_match_every_
  mount_point`, a parity test, now repointed to import `CREDENTIAL_DIRS`/
  `SESSION_STATE_DIRS` from `asb.runtime.storage` (the owning module)
  instead of `asb.lifecycle`. Verified empirically that `staging.py`
  importing `runtime.storage` directly would **not** itself close a cycle
  (`runtime/storage.py` imports neither `staging.py` nor anything that
  leads back to it) — `staging.py`'s own duplication strategy was left
  unchanged regardless, since restructuring it was out of this task's
  scope; only the stale comment reference and the test's import were
  corrected.
- **Two more re-exports (`KEYRING_BUS`, `ensure_keyring_runtime_volume`,
  `ensure_keyring_service`) had their reach from `runtime/workspace.py`
  removed**, per the review's item 5: that module now does
  `from .. import keyring` at module level (verified no cycle: `keyring.py`
  imports nothing from `runtime/`) and calls `keyring.ensure_keyring_
  service(...)` etc. directly, instead of reaching through
  `lifecycle.ensure_keyring_service(...)`. This required repointing 19
  `mock.patch(...)` call sites across `tests/unit/test_lifecycle.py`,
  `tests/unit/test_broker.py`, `tests/unit/test_workspace_runtime.py` and
  `tests/unit/test_login_flow.py`, plus one integration test
  (`tests/integration/test_startup_auth.py`, which called
  `lifecycle.ensure_keyring_service` directly in its own pilot-setup code,
  not just via `mock.patch`) — each repoint verified green, and the
  pattern red-proven once (§4 item 1 below) by reverting a single patch
  target and confirming the resulting failure is loud (a real `TypeError`/
  `PodmanError` from the un-mocked real function executing), never a
  silent pass.
- **`diagnostics/checks.py`'s reach for `CREDENTIALS_VOLUME`/
  `TOOLCACHE_VOLUME` was removed the same way**: `from ..lifecycle import
  CREDENTIALS_VOLUME, TOOLCACHE_VOLUME, IMAGE, names` became `from
  ..lifecycle import IMAGE, names` plus a new `from ..runtime.storage
  import CREDENTIALS_VOLUME, TOOLCACHE_VOLUME` (module level; no cycle,
  `runtime/storage.py` imports nothing from `diagnostics/`). No test
  mocked these two constants by name (they are read once and passed
  straight into `podman.exists("volume", ...)` calls that tests mock
  instead), so no repoint was needed there — verified by a value-swap red
  proof instead (temporarily renamed `CREDENTIALS_VOLUME`'s value in
  `runtime/storage.py` and confirmed `diagnostics.checks.CREDENTIALS_
  VOLUME` picked up the live value, proving the import is live, not a
  stale cached copy).
- **`cli/asb/runtime/sandbox.py:298`'s reach into `lifecycle._origin_of`**
  (a private symbol of a sibling module — the same shape as the
  `storage._volume_mountpoint` case Task 6's first pass fixed) now goes
  through a new public `lifecycle.origin_of(ws, home)`, a one-line wrapper
  around the existing private `_origin_of`. `lifecycle.py`'s own internal
  callers (`down`, `pull`, `purge`) still call the private `_origin_of`
  directly and are unaffected; only the cross-module reach moved.

**What remains in the re-export block, and why, re-derived by symbol —
every name below was checked by a fresh repo-wide search after all the
deletions above, not inherited from any earlier list:**

| Name(s) | Production consumer | How reached |
| :--- | :--- | :--- |
| `KEYRING_BUS`, `ensure_keyring_runtime_volume`, `ensure_keyring_service`, `credential_mount_args` | `auth.py` | attribute access, `lifecycle.X` |
| `check_keyring_service` | `doctor.py` **and** `readiness.py` | both `from .lifecycle import check_keyring_service` (readiness.py's import is deferred, inside `probe_workspace`) |
| `CREDENTIALS_VOLUME`, `ensure_credentials_volume` | `auth.py` **and** `keyring.py` | `auth.py` by attribute access; `keyring.py` by deferred `from .lifecycle import ...` (avoids the `keyring.py` ⇄ `lifecycle.py` cycle) |
| `CONFIG`, `RuntimeStorage`, `WorkspaceTransaction`, `WorkspaceRuntime` | `lifecycle.py` itself | used directly in `lifecycle.py`'s own body (`SSH_KEY`/`ensure_ssh_key`, `prepare_workspace`'s type hint, `up()`, and the `up`/`down`/`suspend`/`resume` facade methods respectively) — not re-exports for outside consumers, though nothing stops one |

**`readiness.py` as a `check_keyring_service` consumer, and `diagnostics/
checks.py`/`runtime/workspace.py` as consumers of the block at all, are the
three items the whole-branch review found that the first pass of this
report never named** — `readiness.py` remains a genuine consumer today;
the other two are no longer consumers of the *re-export block* at all,
because this fix wave repointed them to their owning modules (bullets
above) rather than merely documenting the gap.

**Ship-as-is, named honestly (not fixed — see §8 "Residual test-only
re-export bindings" for the full ruling):** `KEYRING_CONTAINER`, `KEYRING_DATA_
VOLUME`, `KEYRING_PASS`, `KEYRING_RUNTIME_VOLUME`, `KEYRING_SCHEMA`,
`ensure_keyring_data_volume`, `ensure_keyring_pass`, `ensure_credential_
dirs`, `ensure_session_volume`, `session_mount_args` — zero production
consumer each, kept alive only by `mock.patch("asb.lifecycle.X", ...)`
strings in `test_auth.py`/`test_lifecycle.py`/`test_login_flow.py`.

The comment block in `lifecycle.py` (immediately above `IMAGE = ...`) was
rewritten to match this table, not the four-name list from the first pass.

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

**A whole-branch review of this three-item pass found six further gaps**
(a narrowed test guard, ten dead re-exports the first pass missed because
it inherited a partial inventory instead of re-deriving one, a false
"`staging.py` is a consumer" claim in three places, a coverage gap in
`_service_state` this task's own deferral had understated, and two more
private-symbol/wrong-owner import reaches of the same shape as item 3
above). That fix wave is documented in place, by topic, rather than as a
second numbered list: the test-guard fix is §6; the re-export
re-derivation, the `staging.py` correction and the two import-owner fixes
are all in §3; the `_service_state` reversal is §7; the honest residual
of what was deliberately *not* fixed is §8.

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

## 6. Test guards widened: two hardcoded module lists had narrowed silently

**Most important finding of the whole-branch review, per the review
itself.** `tests/unit/test_readiness.py::TestNoRootlessNetnsAdvice::
test_diagnostic_modules_never_recommend_the_rootless_netns_unshare` greps
a hardcoded tuple of module filenames (`readiness.py`, `doctor.py`,
`runtime_check.py`, `lifecycle.py`) for the string `--rootless-netns` — a
regression guard against reintroducing advice the R10 pilot disproved.
This task's Task 5 moved essentially all the advice-bearing diagnostic
logic out of `doctor.py` into `diagnostics/checks.py`/`diagnostics/
report.py`, and `test_readiness.py` was never touched by any task in this
plan (not among the branch's changed files before this fix wave): the
guard kept passing while scanning modules that no longer carry the risk,
so its coverage of the module that now does was zero. Fixed: extended the
tuple to also scan `diagnostics/checks.py`, `diagnostics/report.py`,
`runtime/workspace.py` and `runtime/storage.py` (the four modules Task 4/5
moved risk-bearing logic into), keeping the original four. Verified the
tuple's nested-path entries resolve correctly under `cli / name` (pathlib
joins `"diagnostics/checks.py"` as a multi-segment relative path without
special-casing). Red-proven: inserted `--rootless-netns` into
`diagnostics/checks.py`, confirmed the guard failed naming that exact
module (`AssertionError: '--rootless-netns' unexpectedly found in ...`),
removed it, confirmed green again.

**A second instance of the identical shape, found by "look once for the
same shape elsewhere" as instructed, in the same file:**
`TestNoDirectPodmanLifecycleAdvice::test_diagnostic_modules_never_tell_
the_operator_to_drive_podman` walks the AST of a hardcoded five-module
tuple (`keyring.py`, `doctor.py`, `readiness.py`, `auth.py`,
`lifecycle.py`) for string literals containing `"podman restart"` or
`"podman start "` — guarding against remediation text that would drive a
systemd-supervised container directly instead of through its unit. Same
narrowing risk, same fix: extended to the same four additional modules,
kept the original five. Red-proven the same way (inserted a matching
literal into `diagnostics/checks.py` via an f-string constant segment,
confirmed the guard named the module and the exact forbidden phrase,
removed it, confirmed green). No third instance of this shape (a test
hardcoding a list of module filenames to scan) was found anywhere else in
`tests/unit/` or `tests/integration/` after a repo-wide search for the
pattern — these two, both in `test_readiness.py`, were the only ones.

## 7. Deferred coverage gaps and style items

**Item 7 reversed, fixed in this round — the triage authority overruled the
original deferral.** `deferred-items.md` item 7 (`diagnostics/checks.py`
520/522, `_service_state`'s `"missing"`/`"stopped"` returns) was originally
deferred "triage at the final review, do not fix blind." The whole-branch
final review triaged it and found the gap worse than recorded: **no test
entered `_service_state` at all** (not merely its missing/stopped
branches — every existing caller reaches it only through
`collect_workspaces`, and every one of those mocks `podman.exists`/
`podman.running` to a constant `True`, so `_service_state` itself, all
five of its branches, had zero direct coverage). Global Constraint #1
("preserve exit codes") makes this the branch that flips `svc_healthy`,
which flips `ws_healthy`, `infra_healthy`, and both aggregate exit codes.
Fixed: `tests/unit/test_diagnostic_checks.py::TestServiceState`, six
tests, one per branch (`missing`, `stopped`, `healthy`, `unhealthy`,
`starting`, no-healthcheck/`process_running`), each asserting the full
`(healthy, state, remediation)` triple. Red-proven for the two branches
the review named explicitly (`missing`, `stopped`): flipped each return's
`healthy` bit to `True` in turn, confirmed the corresponding test fails
with the exact tuple mismatch, restored. See `task-6-report.md` for the
full red-proof transcripts.

Items 8–18 of `deferred-items.md` (the remaining coverage gaps in
`diagnostics/checks.py`, `runtime/workspace.py`, `diagnostics/report.py`,
and the style/structure items in `install.py`, `runtime/workspace.py`,
`diagnostics/report.py`, `diagnostics/checks.py`/`doctor.py`) were left
exactly as found — the final review did not reopen these, only item 7.
None was introduced by this plan; all are relocated pre-existing gaps
earlier tasks' review rounds deferred by ruling.

## 8. Residual test-only re-export bindings — honest, not repointed

Beyond the ten dead re-exports this task deletes (§3) and the two the
review's item 5 fixes deleted as a byproduct, roughly ten more re-exported
names in `lifecycle.py` have **zero production consumer** and are kept
alive **only** by `mock.patch("asb.lifecycle.X", ...)` strings in
`test_auth.py`, `test_lifecycle.py` and `test_login_flow.py`:
`KEYRING_CONTAINER`, `KEYRING_DATA_VOLUME`, `KEYRING_PASS`,
`KEYRING_RUNTIME_VOLUME`, `KEYRING_SCHEMA`, `ensure_credential_dirs`,
`ensure_keyring_data_volume`, `ensure_keyring_pass`, `ensure_session_
volume`, `session_mount_args`.

**These are not repointed, by explicit ruling of the whole-branch review:**
repointing `mock.patch` targets across three test files is real churn
against the surgical-changes constraint (AGENTS.md §3), and each repoint
carries the same R21 silent-patch hazard demonstrated in §3/§4 above —
multiplied by roughly ten more call sites with no compatibility-wrapper
deletion to justify the churn (unlike `start_forwarder`, `CREDENTIAL_DIRS`/
`SESSION_STATE_DIRS`, and the `keyring.*` reaches in §3, which were
repointed because a real re-export was being *deleted* or a real
cross-module private-symbol reach was being closed).

**The plan's completion criterion — "no compatibility wrapper lacks a
production consumer" — is therefore met for production consumers, and
explicitly NOT met for these ten test-only bindings.** This report does
not redefine "production consumer" to include a `mock.patch` string in
order to claim the criterion is satisfied in full; the honest state is
recorded here instead, by name, per the review's own instruction.

## 9. Verification

Full command-by-command output, including tracebacks and red-before-green
proofs, is in `task-6-report.md` in this plan's `.superpowers/sdd/` folder.
Summary:

- `PYTHONPATH=cli python3 -m unittest discover -s tests/unit -v`: **1485
  tests, OK** (baseline at `54d9688`: 1481; -2 for the deleted
  `lifecycle.login` wrapper's dedicated tests, §10; +6 for the new
  `TestServiceState` class, §7).
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

## 10. Tests removed in this task

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
