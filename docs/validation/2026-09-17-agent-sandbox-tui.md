# Acceptance report: Agent Sandbox TUI

- **Plan:** `docs/superpowers/plans/2026-09-17-agent-sandbox-tui.md`, Task 13
- **Spec:** `docs/superpowers/specs/2026-09-17-agent-sandbox-tui-design.md`
- **Branch:** `feat/agent-sandbox-tui` (base `ec420ac`); automated evidence
  collected on 2026-09-18 at `2f9e924`
- **Host:** Linux 7.2.5, Podman 6.1.1 (rootless), Python 3.14.7, Git 2.55.0;
  image `localhost/agent-sandbox:latest` = `594065ee99fe` (includes tmux)
- **Status:** automated acceptance recorded below; the human pilot (§4) is
  **pending**.
- **Sanitization:** no credential, prompt, provider output or transcript was
  produced or recorded. Every agent in the automated scenarios is a harmless
  fake command (`sh -lc 'printf …; exec sleep 600'`); no provider binary ran
  and no provider API was contacted (`ASB_LIVE_AUTH` unset). Workspace names
  are shown by shape (`asb-test-<label>-<uid>-…`), never by the random value.

---

## 1. Scope and method

Step 1 of Task 13 adds `tests/integration/test_tui_acceptance.py`. It uses
only temporary Git repositories under a `SandboxFixture` temporary root and
`asb-test-` runtime resources, and it drives the same boundaries the TUI
uses: `TuiController` and `handle_key` (the curses key map), the session
service layer of `asb-agent session …`, and `CheckoutManager`. The registry
and session store live under the fixture root, never under
`~/.local/state/agent-sandbox/`. The only writes outside the fixture root
are the ones `asb-agent up` itself makes (`~/asb-agent/<name>/` and
`~/.local/state/agent-sandbox/<ws>/origin`), which `purge` removes and the
test asserts absent.

Two real workspaces are created per run:

- **W1 (primary checkout):** `project add`, then `session start`. Session
  scenarios need one live tmux server; all six share it.
- **W2 (worktree):** `CheckoutManager.create`, then
  `SandboxRuntime.ensure`. Label, refusal, conflict, external merge,
  active-session and cleanup scenarios need a live sandbox clone, because
  finish and cleanup read and purge it.

What the automated test does **not** prove: the real curses terminal
(`def_prog_mode`/`endwin` around an attach, drawing, resizing). The test
calls `handle_key` on a `TuiController`; attach runs in a real pty through
the injected `run_child`. The real terminal is observation 2 of the pilot.

---

## 2. Automated scenarios

Command for every scenario (one run covers all of them):

```bash
python3 -m unittest tests.integration.test_tui_acceptance -v
```

Result: `Ran 2 tests in 32.883s`, `OK`, exit status 0. Repeated twice more
before the full suite: `32.893s OK` and `32.798s OK`, exit status 0 each;
a fourth run inside the full integration suite is in §3.

| # | Scenario | Expected | Actual | Exit |
| :--- | :--- | :--- | :--- | :--- |
| 1 | Two sessions of different agents in one checkout (W1) | `session start` for `codex` and `claude` both print `<id> running`; `session list --json` holds both with the same `checkoutId`, distinct `terminalId` `asb-<id>`; two distinct pane PIDs; both probe ALIVE | as expected | 0 |
| 2 | TUI close with live tmux (W1) | refresh shows `codex  detached  accept-codex` and `claude  detached  accept-claude`; `q` sets `running=False`; no stored revision changes; both panes still ALIVE with the same pane PID | as expected | 0 |
| 3 | Reattachment (W1) | a new `TuiController`, Enter on the codex row: one child `ssh … tmux attach-session`, screen shows `codex-ready`, `C-b d` detaches, message `detached`; same pane PID; ALIVE | as expected | 0 |
| 4 | Uncertain liveness (W1) | `tmux split-window` adds a second pane: probe UNKNOWN; refresh shows `claude  recovery_required`; codex stays `detached`; Enter shows `session is recovery_required; nothing to attach`; `session attach` exits 2; no child and no `execute` call; after `kill-pane` the refresh shows `detached` with the original pane PID | as expected | 0 |
| 5 | Voluntary completion (W1) | a command that waits on a flag file starts `running`; after `touch <flag>` the pane is DEAD with exit status 0; refresh shows `antigravity  completed  accept-done`; `session attach` exits 2 without launching; the pane stays DEAD (never relaunched) | as expected | 0 |
| 6 | Stop and purge (W1) | `session stop` prints `<id> completed` for both live sessions, probes DEAD; `asb-agent purge --workspace <ws> --yes` exits 0; agent container and `~/.local/state/agent-sandbox/<ws>` absent | as expected | 0 |
| 7 | Branch label refresh (W2) | primary row `[primary]  main (host)  absent`; worktree row `[worktree]  topic  ready`; after `git switch -c agent-label` inside the sandbox, refresh shows `agent-label`; after switching back, `topic` | as expected | 0 |
| 8 | Primary-checkout refusal (W2) | `finish` → `blocked` "the primary checkout is never finished"; `cleanup` → `blocked` "the primary checkout is never cleaned up"; TUI `f` on the primary row opens no prompt and shows "the primary checkout is never finished"; `main` unchanged, primary clean | as expected | 0 |
| 9 | Dirty-worktree refusal (W2) | an untracked file in the worktree: `finish` (cleanup on) and `cleanup` both `blocked` "uncommitted changes"; no `refs/asb` ref written; worktree, branch, binding and sandbox present | as expected | 0 |
| 10 | Merge conflict preservation (W2) | agent and operator commit the same file differently; `finish` (cleanup and branch deletion on) → `conflict` naming `shared.txt`; `MERGE_HEAD` and unmerged index entries present; worktree, `topic` branch, binding and sandbox preserved | as expected | 0 |
| 11 | External merge (W2) | after `merge --abort` and resetting the operator commit: `asb-agent pull --workspace <ws>` exits 0, `git merge refs/asb/<ws>/topic` in the primary; the agent commit is an ancestor of `main`; refresh labels the row `merged / cleanup available` | as expected | 0 |
| 12 | Active session blocks cleanup (W2) | a live harmless session on the worktree: `cleanup` → `blocked` "active session <id>"; everything preserved; `session stop` then succeeds | as expected | 0 |
| 13 | Cleanup from the TUI (W2) | `f` on the labelled row opens `clean up? y clean up …`; `y` gives `cleanup: cleaned`; agent container gone, `sandbox_absent` true, worktree path gone, binding gone, `topic` kept (deletion defaults to no), agent commit still in `main`, row gone | as expected | 0 |

**Cleanup evidence.** Each run ends with the `SandboxFixture` teardown, which
kills every registered tmux session, stops and disables every registered
unit and proves it unknown to the manager, removes every registered
container, volume and network and proves each absent, removes the temporary
root, and fails the test on any leftover. After the three standalone runs:

```text
$ podman ps -a --filter name=asb-test-
CONTAINER ID  IMAGE       COMMAND     CREATED     STATUS      PORTS       NAMES
$ podman volume ls --filter name=asb-test-
DRIVER      VOLUME NAME
$ podman network ls --filter name=asb-test-
NETWORK ID  NAME        DRIVER
```

---

## 3. Complete automated verification

Run on 2026-09-18 at `2f9e924` (the acceptance test commit), in the order
the brief lists, with `ASB_LIVE_AUTH` unset.

| Command | Result | Exit |
| :--- | :--- | :--- |
| `python3 -m unittest discover -s tests/unit -v` | `Ran 1177 tests in 11.011s`, `OK`, 0 skipped | 0 |
| `python3 -m unittest discover -s tests/integration -v` | `Ran 53 tests in 604.481s`, `OK (skipped=1)`; both acceptance tests `ok` | 0 |
| `for test in tests/test-*.sh; do bash "$test"; done` | 16 scripts: 15 pass, `tests/test-broker.sh` fails 1 of 10 checks (below) | 1 for `test-broker.sh`, 0 for the rest |
| `git diff --check` | no output | 0 |

The one integration skip is
`test_provider_auth.TestLiveProviderVerification.test_verify_client_makes_exactly_one_call_per_provider`:
it makes a real provider call and runs only when `test_provider_auth.py` is
selected explicitly with `ASB_LIVE_AUTH=1`. It is not a TUI scenario, and a
skip is not evidence that it passes.

Each script ran on its own, with its exit status and log captured
separately (a `timeout 1800` guard was added; none hit it):

| Script | Checks passed / failed | Exit |
| :--- | :--- | :--- |
| `test-agents-behind-proxy.sh` | 9 / 0 | 0 |
| `test-auth.sh` | 32 / 0 | 0 |
| `test-broker.sh` | 9 / 1 | 1 |
| `test-doctor.sh` | 16 / 0 | 0 |
| `test-guard.sh` | 13 / 0 | 0 |
| `test-image.sh` | 28 / 0 | 0 |
| `test-keyring-service.sh` | 44 / 0 | 0 |
| `test-lifecycle.sh` | 7 / 0 | 0 |
| `test-nested.sh` | 8 / 0 | 0 |
| `test-network.sh` | 13 / 0 | 0 |
| `test-provision.sh` | 5 / 0 | 0 |
| `test-recipe.sh` | 39 / 0 | 0 |
| `test-reload-allowlist.sh` | 8 / 0 | 0 |
| `test-services.sh` | 9 / 0 | 0 |
| `test-toolcache.sh` | 22 / 0 | 0 |
| `test-transaction.sh` | 13 / 0 | 0 |

**`tests/test-broker.sh` failure (not caused by this branch).** The failing
check:

```text
  FALHOU: version e permitido
    nao encontrou [200] em: HTTP/1.1 499 status code 499
```

The script tests the Docker broker installed on the host
(`/run/asb-docker/docker.sock`, a service installed with sudo), not code
loaded from the checkout. `git diff --name-only ec420ac HEAD` touches no
broker, Docker or install file. The same script run from a throwaway
worktree of the base `ec420ac` gives the same failure (`passou: 9
falhou: 1`, same 499 line, exit 1); that worktree was removed afterwards.

**Post-run resource check** (after the full integration suite and every
script):

```text
$ podman ps -a --filter name=asb-test-
CONTAINER ID  IMAGE       COMMAND     CREATED     STATUS      PORTS       NAMES
$ podman volume ls --filter name=asb-test-
DRIVER      VOLUME NAME
$ podman network ls --filter name=asb-test-
NETWORK ID  NAME        DRIVER
```

---

## 4. Human pilot (Task 13 Step 3)

On one disposable workspace, without credentials or transcripts. Stop on the
first unexpected runtime, auth, network, mount or readiness change and keep
the workspace for diagnosis.

| # | Observation | Result |
| :--- | :--- | :--- |
| 1 | `asb-agent connect` opens the real project root. | **pending — to be filled by the operator** |
| 2 | A Codex session survives TUI exit and reattaches to the same tmux process. | **pending — to be filled by the operator** |
| 3 | A second agent can exist in the same checkout while the operator controls whether it runs. | **pending — to be filled by the operator** |
| 4 | An agent branch switch updates the TUI label. | **pending — to be filled by the operator** |
| 5 | External merge enables cleanup. | **pending — to be filled by the operator** |
| 6 | Dirty state and an active session each block cleanup. | **pending — to be filled by the operator** |
| 7 | Existing Orca create/resume hooks still connect. | **pending — to be filled by the operator** |
| 8 | Provider session ID and native resume with a real Codex (steps below). | **pending — to be filled by the operator** |

Observation 8, step by step, on the disposable workspace:

1. `asb-agent session start --checkout <id> --agent codex`, then
   `asb-agent session attach <session-id>`.
2. Send one short prompt that needs no tool use, then detach with `C-b d`.
3. `asb-agent session list --json`: record whether the session has a
   `providerSessionId`.
4. End the process without `session stop`: stop the workspace container
   (`asb-agent suspend --workspace <ws>` then `asb-agent resume
   --workspace <ws>`) or kill the pane from inside tmux.
5. Refresh the TUI (`r`): record whether the row becomes
   `exited_resumable`.
6. Press Enter on it: record whether Codex resumes the SAME conversation
   (the earlier prompt is in its history).

If step 3 shows no ID, the provider creates its session file lazily and
the discovery bounded to the first five seconds after launch never sees
it (see §5); record that as the finding rather than a pass.

Items the pilot is also the only evidence for (carried from Tasks 4, 8 and
10): the real curses suspend/restore around an attach, a real provider's
session-ID discovery inside the sandbox, and `ssh` end-of-options handling
with a real terminal.

---

## 5. Known limitations and deferred items

Drawn from the controller's ledger; none is fixed by this task. The
final review's fix wave (after this report was first written) fixed some
items that were listed here; they are marked **fixed in the fix wave**.

**Spec divergence to ratify: external-merge detection (spec §10.4)**

Spec §10.4 says the next refresh detects clean worktrees whose `HEAD` is
already contained in the target branch and labels them
`merged / cleanup available`. The implementation also requires at least
one exported sandbox ref (`refs/asb/<ws>/*`) and requires every such ref
to be contained in the integration branch. Scenario 11 covers that path
(`asb-agent pull`, which writes the ref, then `git merge`). The gap: an
operator who merges the worktree branch by hand without ever running
`pull` or a finish gets no label and no direct cleanup; `f` then runs a
full finish, which exports and merges (a no-op merge) before cleaning up.
Task 12 chose this on purpose: when the work lives only in the sandbox,
the operator worktree's `HEAD` is still the base commit and is always
contained in `main`, so a `HEAD`-only check would label every untouched
worktree as merged. The controller ratified this divergence. **Fixed in
the fix wave:** one exception, when the sandbox is positively absent
(never created, or purged by hand) there is no sandbox work to lose, so a
clean worktree whose own HEAD is in the integration branch is labelled
and cleaned without an export ref, and `f` offers cleanup instead of
finish.

**Security (needs a human decision)**

- `asb-agent pull` (existing command, outside this plan) reads the sandbox
  branch with `rev-parse --abbrev-ref HEAD` and passes it unvalidated, with
  no `--`, into a host `git fetch`. The sandbox checkout is agent-writable,
  so agent-controlled text reaches a host Git command line; a detached HEAD
  is also mishandled. Finish does not use `pull` (it validates the branch
  and fetches by full ref), but the external-merge path in §2 row 11 does,
  as an operator would.
- The finish export fetch still runs `upload-pack` against the
  agent-writable clone, as `pull` does. Git ignores
  `uploadpack.packObjectsHook` from repository config, but not every key
  `upload-pack` reads was audited. The hardening path is a fetch from
  inside the sandbox or a transport that ignores the source repository's
  config.
- The sandbox `git status` that guards a purge runs inside the container,
  so an agent could fake "clean"; it would only lose its own uncommitted
  work. Running it on the host would let an agent-set `core.fsmonitor` or
  filter execute on the host.

**Behaviour to know**

- The `merged / cleanup available` label and its direct cleanup always
  target the integration branch.
- Provider-ID discovery runs only during the first five seconds after
  launch, which always ends before the operator's first prompt. If a
  provider creates its session file only when the first message is sent,
  today's code stores no provider ID for that session, and native resume
  will not happen: after its process ends the session becomes
  `recovery_required`, never `exited_resumable`. Pilot observation 8
  decides whether a lazy discovery is needed; none is built yet.
- A split pane or extra tmux window keeps a session at `recovery_required`
  until the extra pane is gone (scenario 4).
- After a workspace container is recreated (not merely restarted), the
  tmux socket is missing and the probe reads UNKNOWN, so sessions become
  `recovery_required`. A `pgrep -x 'tmux: server'` check that would
  classify this as DEAD is deferred.
- A purge destroys tags, other ref namespaces (such as `refs/notes`),
  reflog-only commits and ignored files in the sandbox clone without
  checking them.
- A cleanup retry after Git already removed the worktree cannot delete the
  local branch (its name is not stored).
- Antigravity has no proven session-ID source: it never resumes natively.
- `session start` blocks the TUI while the workspace comes up.
- **Fixed in the fix wave:** `cli/asb-agent` imported the TUI, and so
  `curses`, at top level; it now imports it only for `tui`, which exits 2
  with a clear message on a Python without `_curses`.

**Deliberate v1 limits**

- `suspend` has no CLI or TUI session action; `session stop` and `d`
  end a session.
- `session resume` is CLI-only; in the TUI, Enter resumes an
  `exited_resumable` session.
- Adding a project is CLI-only (`asb-agent project add`).
- After a container restart, native resume is operator-triggered (Enter
  or `session resume`), not automatic: a divergence from spec §11.2
  ratified by the controller.

**Documentation and minor code items deferred by earlier reviews**

- **Fixed in the fix wave:** the suspended-workspace message now names
  `asb-agent resume --workspace <ws>`, and `lifecycle.md` §4 describes it;
  `ensure()`'s docstring no longer says it writes the registry.
- `codex.py`/`claude.py` module docstrings overstate the session-ID proof.
- `remote_run` can raise `ValueError` for an out-of-range port; `--title`
  is unvalidated on the CLI (the TUI neutralizes control characters).
- Registry/store: `remove()` on an unknown id creates an empty file;
  re-adding a project does not update its branch or worktree root; the
  integration branch is stored without `check-ref-format`; workspace names
  of pre-existing bindings are not validated; `_transact` chmods whatever
  parent it is given; a `.lock` file is created even for a rejected store.
- TUI: `discover` catches only Podman/OS/subprocess errors per binding, so
  an unexpected error hides a whole project; `addnstr` clips by
  characters, so wide titles can wrap; text entry is ASCII-only and strips
  spaces; an arrow key cancels an open prompt; a registry error message is
  not cleared by a later good refresh.
- Finish: `finish_preview`'s unreachable-sandbox refusal is not entered by
  a test; a store error in the post-merge re-probe shows "finish failed"
  after the merge landed (nothing removed); a killed fetch gets no
  `refs/asb` lock guidance.
- New modules mix absolute `asb.*` and relative imports.
