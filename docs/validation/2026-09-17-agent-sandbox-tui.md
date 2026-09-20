# Acceptance report: Agent Sandbox TUI

- **Plan:** `docs/superpowers/plans/2026-09-17-agent-sandbox-tui.md`, Task 13
- **Spec:** `docs/superpowers/specs/2026-09-17-agent-sandbox-tui-design.md`
- **Branch:** `feat/agent-sandbox-tui` (base `ec420ac`); automated evidence
  collected on 2026-09-18 at `2f9e924`; the human pilot (§4) ran across
  rounds 1-5 on 2026-09-19 and 2026-09-20, with fixes landed between
  rounds, plus a final passing re-run, ending at `9c30fa3` (unit suite
  1286 OK, recipe 39/39, verified by the controller)
- **Host:** Linux 7.2.5, Podman 6.1.1 (rootless), Python 3.14.7, Git 2.55.0;
  the image was rebuilt twice during the pilot for defects only a real
  workspace surfaced; `localhost/agent-sandbox:latest` = `13d17b20c0a6` at
  the passing round (rollback tags kept: `pre-onboarding` = `594065ee99fe`,
  the image used through round 3; `pre-mise` = `0315f5f5d01f`, used for
  round 5, after the onboarding fix and before the mise switch)
- **Status:** automated acceptance recorded below (§§1-3); the human pilot
  (§4) **PASSED** on 2026-09-20.
- **Sanitization (§§1-3, automated scenarios):** no credential, prompt,
  provider output or transcript was produced or recorded. Every agent is
  a harmless fake command (`sh -lc 'printf …; exec sleep 600'`); no
  provider binary ran and no provider API was contacted (`ASB_LIVE_AUTH`
  unset). Workspace names are shown by shape (`asb-test-<label>-<uid>-…`),
  never by the random value.
- **Sanitization (§4, human pilot):** real `claude`/`codex` binaries ran
  under the operator's own accounts on a disposable workspace, and real
  short prompts were sent to them. Nothing from those prompts or their
  output is recorded in this report — no prompt text, no provider output,
  no transcript, no credential, no account identifier. Only session
  metadata is quoted: session state, timestamps, and truncated provider
  session ids.

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
the injected `run_child`. The real terminal is the human pilot's
detach/quit/reopen bullet in §4 (exercised there with a Claude session,
not Codex).

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

The pilot ran on one disposable workspace, through the TUI itself — not
through the CLI-only script this section originally laid out. It took
five rounds across 2026-09-19 and 2026-09-20; interim rounds surfaced real
defects, each fixed and independently reviewed before the pilot continued:
Ghostty's `TERM` making `tmux attach-session` fail outright, exit 1
(round 1); accented characters rendering as `_` and a dead pane leaving
the operator stuck in the attached client (round 2); Claude's first-run
"Select login method" screen appearing in every new workspace (round 3);
and, after a real reboot, both agents reading `recovery_required` with no
stored `providerSessionId` (round 5) — the failure that produced Claude's
launch-time session-id assignment and Codex's lazy/contended discovery
design recorded in §5. The full round-by-round trail, including every
ruling made along the way, is in
`.superpowers/sdd/2026-09-17-agent-sandbox-tui/progress.md`. What follows
is the final, passing round (2026-09-20):

- A Claude session started on the primary checkout opened directly into a
  working conversation: no login screen, running in bypass-permissions
  mode; accented characters rendered correctly.
- Detaching with `C-b d`, quitting the TUI, reopening it, and pressing
  Enter on the row returned the SAME conversation.
- A worktree was created with `w`; a Codex session was started in it;
  from inside that session Codex ran `git switch -c teste-branch`; after
  `r` the TUI's branch label followed the new branch.
- Pressing `f` on that worktree while its session was still live was
  refused, with the reason shown on screen.
- Native resume across a REAL COMPUTER REBOOT, for both agents: after
  sending one prompt in each session and pressing `r`,
  `session list --json` showed a `providerSessionId` for both — Claude
  `0913403c-…`, Codex `01a0c074-…` — each with `startedAt` set and
  `endedAt` null. After the reboot, pressing Enter on each row returned
  each agent to its OWN conversation (native resume, not a fresh one).
- Observation 7 (existing Orca create/resume hooks still connect) was
  **not run**: the operator does not use Orca. That is recorded plainly,
  not as a pass.
- Observation 1 (`asb-agent connect` opens the real project root) is not
  re-tested here; it **passed earlier**, at the Task 5 checkpoint pilot on
  2026-09-18.

Observation 5 (external merge enables cleanup) and the dirty-worktree half
of observation 6 were not separately re-exercised live in this round;
they remain proven by automated scenarios 10-12 (§2), not by the human
pilot.

Items only this pilot proves, and now confirms: the real curses
`def_prog_mode`/`endwin` suspend-and-restore around an attach (the
automated suite only drives `handle_key` directly, per §1); a real
provider's session-ID handling running inside the sandbox
against a real `codex`/`claude` binary, not a harmless fake command; and
`ssh` behaviour against a real interactive terminal (round 1's Ghostty
`TERM` failure is exactly that class of defect, invisible to every
automated scenario).

---

## 5. Known limitations and deferred items

Drawn from the controller's ledger; none is fixed by this task. The
final review's fix wave (after this report was first written) fixed some
items that were listed here; they are marked **fixed in the fix wave**.
The human pilot (§4) fixed further items and surfaced new ones; those are
marked **fixed in the pilot**.

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

- **Fixed in the pilot** (human decision, round 1): `asb-agent pull` used
  to read the sandbox branch with `rev-parse --abbrev-ref HEAD` and pass
  it unvalidated, with no `--`, into a host `git fetch`, and mishandled a
  detached HEAD. `pull()` in `cli/asb/lifecycle.py` now validates the
  branch name and the destination ref (`GitRepository.valid_branch_name`,
  `valid_ref`), fetches after `--`, and refuses a detached HEAD before any
  `git fetch` runs. Finish already validated and fetched by full ref;
  both paths do now.
- The finish export fetch and `pull` still run `upload-pack` against the
  agent-writable clone. Git ignores `uploadpack.packObjectsHook` from
  repository config, but not every key `upload-pack` reads was audited.
  The hardening path is a fetch from inside the sandbox or a transport
  that ignores the source repository's config — a transport concern, not
  fixed by the branch-name validation above.
- The sandbox `git status` that guards a purge runs inside the container,
  so an agent could fake "clean"; it would only lose its own uncommitted
  work. Running it on the host would let an agent-set `core.fsmonitor` or
  filter execute on the host.

**Behaviour to know**

- The `merged / cleanup available` label and its direct cleanup always
  target the integration branch.
- **Superseded in the pilot** (round 5's reboot failure): discovery is no
  longer limited to a five-second window at launch. Claude no longer
  discovers a session id at all — the manager generates a UUID, passes it
  at launch with `claude --session-id <uuid>`, and stores it immediately
  (`cli/asb/agents/claude.py`). Codex still discovers at launch (bounded
  attempts) but now also discovers lazily on every reconcile/attach and
  once more right before a session reaches a final state
  (`SessionManager._discover_lazily`/`_last_discovery`), so a rollout the
  provider creates only on the first prompt is still picked up. The
  remaining limit, by ruling: a candidate is accepted for a session only
  when its timestamp falls outside the lifetime of every OTHER
  same-agent, same-cwd session (live or final) that lacks a stored id —
  so while two Codex sessions are open at once in the same checkout,
  NEITHER can claim an id until one of them ends; ambiguity yields none,
  never a wrong conversation. A session record saved before this change
  has no `started_at`, so lazy discovery never runs for it — the pilot's
  own leftover records had to be cleared for this reason.
- Both agents now launch with their bypass flags: Claude with
  `--dangerously-skip-permissions`, Codex with
  `--dangerously-bypass-approvals-and-sandbox` (`permission_args` in
  `cli/asb/agents/claude.py`/`codex.py`) — matching how Orca launches them
  and the human's stated expectation that the sandbox is the isolation
  boundary, not an in-session prompt.
- Codex used to ask to trust the workspace folder again after a restart.
  Its trusted paths live in `~/.codex/config.toml`, which sits inside the
  shared credential volume but is not itself a credential
  (`asb.staging.filter_codex_config` strips only the `[projects."..."]`
  tables keyed by host path); the entrypoint's config manifest copies
  that filtered file from the host over the sandbox copy at every
  container start, and the sandbox path never matches a host path anyway,
  so no trust entry written there can survive. Resolved without touching
  that file: the Codex driver passes the trust as a per-launch config
  override on the command line, on launch and on resume —
  `-c projects."<cwd>".trust_level="trusted"`, with `<cwd>` the session's
  sandbox checkout (`ConnectionInfo.project_root`). Nothing shared is
  mutated and there is no start-order race. A `cwd` containing a double
  quote, a backslash or a control character makes the driver omit the
  flag entirely, so a broken TOML value can never be emitted; in that
  case Codex prompts for trust as before. The key, the value and the
  quoted dotted path were measured against the image binary
  (`codex 0.155.0`) in throwaway containers — see
  `docs/validation/2026-09-17-agent-session-contracts.md` §4.2.1. What is
  NOT verified is that the prompt is suppressed in a live session: that
  needs a TTY and a real conversation.
- Provider CLIs (`claude`, `codex`, `agy`) now install via `mise latest`
  into a root-owned tree (`/opt/asb-mise`), ahead of the toolcache on
  `PATH`, resolved fresh at each image build instead of pinned versions
  (see `docs/domains/sandbox/configuration.md`, "Provider CLIs"). mise's
  own minimum-release-age default is kept as a supply-chain safeguard, so
  the image can trail the host by the newest release or two.
- Login shells inside the container are NOT PATH-protected against the
  agent: `/etc/profile.d/agent-sandbox.sh` puts `/opt/asb-mise/bin` first,
  but in an interactive login shell Debian's stock `~/.profile` runs
  afterwards and prepends `$HOME/.local/bin`/`$HOME/bin`, so a binary the
  agent writes there shadows `claude`/`codex`/`agy` in that shell. This is
  not a boundary the image can hold — the agent owns its container `HOME`
  and can rewrite `~/.profile` itself. What does hold: `/opt/asb-mise`
  cannot be modified by uid 1000, one workspace's agent cannot replace
  another workspace's or the auth clients' binaries, and session launches
  never go through a login shell (only a human operator's own `connect`
  session uses one).
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
- **Fixed in the pilot:** `codex.py`/`claude.py` module docstrings used to
  overstate the session-ID proof; they now document the mechanism each
  driver actually uses (Claude's launch-time UUID assignment; Codex's
  scan, subagent/`exec` filtering, and the contended-lifetime rule).
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
