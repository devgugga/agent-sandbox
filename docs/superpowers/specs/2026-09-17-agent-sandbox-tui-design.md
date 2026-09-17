# Design: Modular TUI for projects, worktrees, and agent sessions

**Date:** 2026-09-17
**Status:** Consolidated proposal awaiting document review
**Scope:** Sandbox access without an operational dependency on Orca, agent
selection, multiple sessions per checkout, transparent resumption, and safe
cleanup of integrated worktrees.
**Compatibility:** The existing runtime, commands, and recipes remain functional
throughout the implementation.

---

## 1. Context

`agent-sandbox` already provides the runtime properties that matter for security
and persistence: rootless Podman containers, systemd supervision, a closed
network topology, an allowlisted proxy, persistent credentials, SSH, and
per-workspace session volumes. Orca consumes this runtime through hooks under
`recipes/`, but it does not own these guarantees.

The current blocker is in the interaction layer. Orca PTY rehydration failures
can leave the remote process alive while losing the surface through which the
operator accessed the session. This prevents reliable use of the sandbox even
when its containers, SSH connection, and files remain healthy.

Separately, the main production modules hold too many responsibilities.
`cli/asb/lifecycle.py` combines preparation, volumes, resource creation,
rollback, supervision, readiness, and lifecycle operations. `cli/asb/auth.py`
combines rules for all three providers, login, status, live verification, and
presentation. The tests reflect that concentration.

This design adds a simple local interface and makes the domain modules
explicit. It does not replace the recently stabilized runtime and does not
propose a wholesale rewrite.

---

## 2. Goals

1. Use the sandbox from a terminal without depending on Orca's PTY.
2. List projects, primary checkouts, worktrees, and sessions in a TUI.
3. Start Codex, Claude, or Antigravity in the selected checkout.
4. Allow multiple sessions, including different agents, in the same checkout.
5. Let the operator decide whether sessions run concurrently.
6. Reopen a session where it stopped without generating an artificial summary.
7. Update the displayed branch automatically when an agent changes `HEAD`.
8. Remove integrated worktrees without deleting unintegrated work.
9. Reduce responsibility concentration in the current modules through an
   incremental, verifiable migration.
10. Preserve the current CLI, Orca recipe, and runtime contracts.

---

## 3. Non-goals

The first version does not include:

- an embedded code editor;
- a custom terminal emulator;
- an embedded browser;
- a graphical diff viewer;
- native GitHub, Linear, or Jira integrations;
- a mobile application;
- an agent scheduler;
- automatic write locking between agents;
- remote merges or automatic deletion of remote branches;
- replacement of the current Podman, systemd, networking, authentication, or
  credential mechanisms.

The system permits concurrency, but does not decide when concurrency is
appropriate. That decision remains with the operator.

---

## 4. Domain model

### 4.1 Relationships

```text
Project
├── Primary checkout
│   ├── AgentSession (Codex)
│   ├── AgentSession (Claude)
│   └── AgentSession (Antigravity)
│
├── Worktree A
│   ├── AgentSession (Codex)
│   └── AgentSession (Claude)
│
└── Worktree B
    └── AgentSession (Antigravity)
```

A project has one primary checkout and zero or more linked worktrees. Every
checkout can have zero or more sessions. Each session uses exactly one agent
and exactly one checkout.

The primary checkout does not mean the `main` branch. It is the repository's
primary working copy and can be on any branch. The interface uses a `primary`
badge to distinguish it from linked worktrees.

### 4.2 Entities

#### `Project`

- Stable identity derived from the Git common directory rather than the folder
  name.
- Path to the primary checkout.
- Configured integration branch. When it is not configured, the system may
  discover it from `refs/remotes/origin/HEAD` only when that reference is
  unambiguous; otherwise, the interface requires a choice.
- Configured root for new worktrees.

#### `Checkout`

- Stable identity independent of the branch.
- Owning project.
- Absolute path.
- `primary` or `worktree` kind.
- Association with a sandbox runtime.
- Current branch read from Git.
- Clean, dirty, or detached state.

The branch is not part of the persisted identity. The interface reads
`git symbolic-ref --short HEAD`; in a detached `HEAD` state, it displays the
abbreviated commit. As a result, `git checkout` or `git switch` run by an agent
updates the tree without renaming internal records.

#### `AgentSession`

- Stable internal ID.
- Associated checkout.
- Agent: `codex`, `claude`, or `antigravity`.
- Operator-defined title or a title derived from the initial task.
- Working directory.
- Current terminal ID, when one exists.
- Provider-native conversation ID, when one exists.
- Observed state and last known healthy time.

#### `SandboxRuntime`

- Exposes the connection and state of the existing environment.
- Does not redefine the current Podman/systemd topology.
- Can serve more than one checkout when they already share the same mount.
- Keeps the association between a checkout and an execution environment
  explicit.

### 4.3 Distinct identifiers

The following values are never treated as synonyms:

- `ProjectId`;
- `CheckoutId`;
- `SandboxId`;
- `SessionId`;
- `TerminalId`;
- `ProviderSessionId`;
- `AgentKind`.

This separation prevents a branch switch from breaking a session or an
ephemeral PTY from becoming the durable identity of a conversation.

---

## 5. Module architecture

Target structure:

```text
cli/asb/
├── projects/
│   └── registry.py
├── checkouts/
│   ├── model.py
│   ├── git.py
│   └── manager.py
├── sessions/
│   ├── model.py
│   ├── store.py
│   ├── manager.py
│   └── terminal.py
├── agents/
│   ├── base.py
│   ├── codex.py
│   ├── claude.py
│   └── antigravity.py
├── runtime/
│   ├── sandbox.py
│   ├── podman.py
│   ├── systemd.py
│   └── connection.py
├── diagnostics/
│   ├── checks.py
│   └── report.py
└── interfaces/
    ├── cli.py
    ├── tui.py
    └── orca.py
```

This tree describes responsibilities. It does not require empty files or
pass-through wrappers. Each module must hide meaningful behavior behind a small
interface. An extraction occurs only when the new module has cohesion and tests
through its interface.

### 5.1 `CheckoutManager`

Planned public interface:

```python
class CheckoutManager:
    def list(self, project_id: ProjectId) -> list[Checkout]: ...
    def inspect(self, checkout_id: CheckoutId) -> CheckoutStatus: ...
    def create(self, request: CreateCheckout) -> Checkout: ...
    def finish(self, request: FinishCheckout) -> FinishResult: ...
    def cleanup(self, checkout_id: CheckoutId) -> CleanupResult: ...
```

It owns Git validation, safe creation, change detection, integration evidence,
and removal. The TUI does not assemble Git commands directly.

### 5.2 `SessionManager`

Planned public interface:

```python
class SessionManager:
    def list(self, checkout_id: CheckoutId | None = None) -> list[AgentSession]: ...
    def start(self, request: StartSession) -> AgentSession: ...
    def attach(self, session_id: SessionId) -> AttachResult: ...
    def suspend(self, session_id: SessionId) -> None: ...
    def resume(self, session_id: SessionId) -> ResumeResult: ...
    def stop(self, session_id: SessionId) -> None: ...
```

It associates checkout, agent, terminal, and conversation. It does not decide
whether two sessions may work concurrently; it only carries out the operator's
explicit decision.

### 5.3 `AgentDriver`

Each provider is a real adapter behind the same seam:

```python
class AgentDriver:
    def launch(self, cwd: Path) -> LaunchCommand: ...
    def resume(self, cwd: Path, provider_session_id: str) -> LaunchCommand: ...
    def discover_session_id(self, evidence: SessionEvidence) -> str | None: ...
    def probe(self) -> AgentAvailability: ...
```

Provider-specific commands, ID formats, readiness detection, and resumption
belong to the provider driver. Codex, Claude, and Antigravity rules do not
spread across the session manager.

Before a driver promises resumption after process restart, its resume contract
must be proven by a real test. A provider without native resumption still
supports reattachment while its terminal is alive, but the interface must show
the limitation clearly and must never fabricate a summary.

### 5.4 Interfaces

- The CLI preserves existing commands and gains composed commands for projects,
  checkouts, and sessions.
- The TUI uses only public manager interfaces.
- The Orca adapter continues translating the existing recipe contract into the
  same runtime.
- A future GUI can consume the same interfaces without changing the runtime.

---

## 6. Sources of truth and persistence

| Information | Source of truth |
|---|---|
| Projects, worktrees, branches, commits, and dirty state | Git |
| Containers, networks, and ports | Podman |
| Startup and restart | systemd |
| Live terminal process | tmux inside the sandbox |
| Agent conversation | Provider-native state |
| Session title and relationships | `agent-sandbox` registry |

The `agent-sandbox` registry does not copy the branch, dirty state, liveness,
or conversation content. It stores only relationships that do not belong to
the sources above.

### 6.1 Storage

- Global project registry under `~/.local/state/agent-sandbox/`.
- Session registry alongside the protected state of each sandbox.
- Files use mode `0600`; directories use mode `0700`.
- Atomic writes through a temporary file in the same directory followed by a
  rename.
- A local lock during mutations prevents two TUIs from overwriting state.
- No secrets, tokens, passphrases, or conversation content in the registry.
- Interface state always remains outside the agent-writable mount.

Existing session volumes remain responsible for provider-native history. The
new registry references those histories; it does not move or convert them.

---

## 7. Session continuity

### 7.1 Two continuity levels

1. **Process continuity:** the TUI closed, but the container, tmux session, and
   agent remain alive. The next launch reattaches to the same PTY.
2. **Conversation continuity:** the host or container restarted and the process
   died. The driver runs the provider-native resume command with the persisted
   `ProviderSessionId`.

Neither path creates a summary to seed a new conversation.

### 7.2 Recovery flow

```text
open session
    │
    ├─ terminal confirmed alive
    │      └─ attach to the same tmux/PTY
    │
    ├─ terminal confirmed dead + valid ProviderSessionId
    │      └─ run provider-native resume command
    │
    ├─ conversation completed by operator
    │      └─ keep completed; do not relaunch
    │
    └─ liveness uncertain
           └─ recovery_required; do not create a duplicate process
```

The terminal backend is authoritative for liveness. A saved `TerminalId` is
not evidence of a live process.

### 7.3 States

- `starting`;
- `running`;
- `detached`;
- `suspended`;
- `exited_resumable`;
- `completed`;
- `recovery_required`;
- `failed`.

Transitions are recorded only after the corresponding operation is confirmed.
A failure between dispatch and confirmation produces a recoverable state, not
presumed success.

### 7.4 Terminal

`tmux` runs inside the sandbox and keeps the process alive after the TUI
detaches. The TUI does not implement ANSI emulation, scrollback, or PTY
rehydration.

When attaching:

1. the TUI suspends its `curses` screen;
2. it opens an SSH connection to the sandbox;
3. it attaches to the corresponding tmux session;
4. the standard tmux detach returns control to the TUI;
5. the tree is redrawn from the sources of truth.

A tmux name is derived only from a validated `SessionId`, never from raw title
or task text.

---

## 8. TUI

### 8.1 Technology

- Python and the standard library (`curses`).
- No new mandatory host dependency.
- No interface daemon.
- No embedded terminal.
- Initial entry through a new subcommand that preserves current parser
  behavior, for example `asb-agent tui`.

### 8.2 Main tree

```text
Projects
├── hexmed-stack
│   └── feat/new-worklist [primary]
│       ├── Codex · Plan new worklist · running
│       └── Antigravity · Implementation · detached
│
└── agent-sandbox
    ├── feat/startup-auth-redesign [primary]
    │   ├── Claude · Startup auth · detached
    │   └── Codex · Resolve sandbox · running
    └── fix/runtime-owned-ssh-pty
        └── Codex · Investigate PTY · suspended
```

### 8.3 First-version actions

- add or discover a project;
- expand and collapse a project or checkout;
- create a worktree;
- create a session by choosing an agent;
- attach to and detach from a session;
- suspend, resume, and stop a session;
- finish work;
- clean up an already integrated worktree;
- refresh branch and state information;
- exit without stopping agents.

The TUI displays the tree while managing sessions. During attachment, the
session occupies the full terminal. Detaching returns to the tree.

---

## 9. Worktree creation

Minimal flow:

1. select a project or checkout;
2. provide the new branch name;
3. show the base, path, and conceptual command;
4. confirm;
5. create the branch and worktree;
6. register the new checkout only after creation succeeds.

The default base comes from project configuration. Without configuration, the
interface uses `refs/remotes/origin/HEAD` only when that reference is
unambiguous; otherwise, it requires a choice. Starting from the currently
selected checkout also requires an explicit choice to avoid accidentally
creating stacked dependencies.

Required validation:

- valid branch name;
- branch and path do not already exist;
- path is contained in the permitted worktree root;
- project is recognized through the same Git common directory;
- no shell interpolation;
- rollback only resources proven to have been created by the current
  operation.

---

## 10. Finishing, merging, and cleanup

### 10.1 Principle

A worktree can be removed automatically only after the system proves that its
work has been integrated into the target branch.

### 10.2 `finish`

```text
finish
  ├─ check for active sessions
  ├─ check dirty state
  ├─ locate a clean checkout of the target branch
  ├─ integrate according to project policy
  ├─ confirm a zero exit status
  ├─ prove the source HEAD is an ancestor of the target
  ├─ remove the worktree
  └─ optionally delete the already integrated local branch
```

If there is no safe checkout of the target branch, the operation blocks with
concrete guidance. It does not silently change the primary checkout's branch
and does not discard operator changes.

In the first version, the integration policy executed by the TUI is a normal
Git merge equivalent to `git merge --no-edit <source-branch>`, run in a clean
checkout that is already on the target branch. The TUI does not rebase, squash,
force-push, or implicitly switch branches. Projects that require another policy
can continue integrating externally and use only subsequent detection and
cleanup.

When a merge conflicts:

- no worktree is removed;
- no branch is deleted;
- the conflict state is reported;
- the required recovery is shown to the operator;
- cleanup can be retried after the integration is resolved.

### 10.3 Integration evidence

The minimum proof is equivalent to verifying that the source commit is an
ancestor of the target branch. A successful merge command exit status alone is
not sufficient.

Before removal, the system must also prove:

- the worktree is clean;
- no live session is attached to it;
- the target branch is configured and resolves;
- the path belongs to the expected project;
- the checkout is not the primary checkout.

### 10.4 External merge

If the operator merges outside the TUI, the next refresh detects clean
worktrees whose `HEAD` is already contained in the target branch. They appear
as `merged / cleanup available`.

### 10.5 Policy

Planned configuration:

```toml
[worktrees]
base_branch = "main"
cleanup_after_merge = true
delete_merged_branch = true
```

Without `cleanup_after_merge`, the TUI asks for confirmation after proving
integration. Even with the option enabled, any uncertainty blocks removal.

Remote branches are never deleted automatically. A cleanup failure after a
merge produces `merged / cleanup pending`, which permits an idempotent retry.

---

## 11. Failure handling

### 11.1 General rule

Uncertain state is never promoted to success. Destructive operations require
positive evidence; absence of an error does not count as evidence.

### 11.2 Main cases

| Failure | Behavior |
|---|---|
| TUI closes | Sessions continue in tmux |
| SSH disconnects | TUI returns to the tree and leaves the session detached |
| tmux is alive, registry is stale | tmux prevails; registry is reconciled |
| registry points to dead tmux | Native resume or `recovery_required` |
| liveness is uncertain | Do not start a second agent |
| container restarts | Driver attempts native resume after readiness |
| branch changes | Tree rereads Git and refreshes the label |
| partial worktree creation | Roll back only resources created by this operation |
| merge conflicts | Preserve worktree and branch |
| merge succeeds, cleanup fails | `cleanup_pending`, safe retry |
| worktree is dirty | Block removal |
| session is active | Block automatic removal |

---

## 12. Security

- The TUI does not relax any sandbox restriction.
- All agent access continues through SSH and the existing runtime.
- Control state remains outside the agent-writable mount.
- IDs, branch names, paths, and session names are validated before use.
- Subprocesses receive separate arguments; controlled text never becomes a
  shell command.
- Do not use `git worktree remove --force` or an equivalent in the normal flow.
- Do not delete a branch without ancestry evidence and explicit configuration.
- Do not store credentials or transcripts in the TUI registry.
- Do not follow worktree paths outside registered roots.
- The TUI can never remove the primary checkout.
- Git, Podman, systemd, SSH, or tmux inspection failures close the operation.

---

## 13. Test strategy

### 13.1 Interfaces as test surfaces

New tests enter through `CheckoutManager`, `SessionManager`, `AgentDriver`, and
`SandboxRuntime`. They do not assert private command-assembly details when an
observable result covers the contract.

When extracting a module, old tests that inspect implementation details are
replaced with tests of the new interface; they are not retained in duplicate
layers.

### 13.2 Required cases

1. Two sessions in the same worktree.
2. Codex, Claude, and Antigravity in the same checkout.
3. Closing and reopening the TUI reattaches to the same process.
4. Two TUIs do not corrupt the registry.
5. Restarting the container resumes the conversation through its native ID
   when supported.
6. Uncertain state does not create a duplicate process.
7. Voluntary completion does not cause an automatic relaunch.
8. Switching branches refreshes the tree without changing `CheckoutId`.
9. Detached `HEAD` is displayed without breaking the catalog.
10. Creation uses the configured base.
11. Stacked creation requires an explicit choice.
12. A merge conflict preserves the worktree and branch.
13. A successful merge plus ancestry evidence permits cleanup.
14. An external merge is detected.
15. A dirty worktree blocks removal.
16. An active session blocks automatic removal.
17. The primary checkout is never removed.
18. A cleanup failure becomes an idempotent retry.
19. A remote branch is not deleted.
20. Existing CLI commands and Orca recipes keep their behavior.

### 13.3 Verification by stage

Each stage runs focused unit tests, integrations for the affected flow, and the
relevant existing suite. No stage proceeds with a known regression or an
unexplained runtime change.

---

## 14. Incremental migration

### Stage 1 — Model and connection without runtime changes

- Introduce domain types and empty registries.
- Extract `ConnectionInfo` from the JSON already emitted by the lifecycle.
- Add direct SSH access.
- Preserve current recipes and stdout.

### Stage 2 — Agent drivers

- Centralize launch, resume, readiness, and provider-specific IDs.
- Keep the existing authentication commands.
- Prove actual provider resumption before advertising it.

### Stage 3 — Persistent sessions

- Add tmux to the image.
- Implement the atomic registry.
- Implement start, attach, detach, stop, and reconciliation.
- Prove that closing the interface does not stop the agent.

### Stage 4 — Navigator TUI

- Implement the tree and actions through public interfaces.
- Suspend `curses` during attachment.
- Refresh Git and session states after detachment.

### Stage 5 — Worktrees and cleanup

- Create worktrees with a preview and confirmation.
- Implement integration evidence.
- Implement idempotent finish and cleanup operations.

### Stage 6 — Reduce large modules

- Move behavior from the lifecycle only after new interfaces cover it.
- Move provider rules from `auth.py` into the drivers.
- Turn `doctor.py` into a composition of checks with structured results.
- Keep temporary wrappers only while a real consumer needs them.
- Remove wrappers and old tests after all consumers migrate.

There is no general rewrite commit. Each extraction preserves behavior, has its
own test, and can be reverted independently.

---

## 15. Acceptance criteria

- `asb-agent tui` opens without changing or restarting existing workspaces.
- The operator can navigate projects, the primary checkout, and worktrees.
- The displayed branch follows the real `HEAD`.
- A worktree accepts multiple sessions and different agents.
- Closing the TUI preserves running agents.
- Reopening the TUI reattaches to the existing process without a summary.
- When the process has died, the driver resumes the native conversation without
  a summary.
- Uncertain liveness never produces a duplicate agent.
- The TUI can create a worktree after showing its base and path.
- A dirty or primary worktree, or one with an active session, is not removed.
- An integrated worktree is removed automatically when configured.
- An external merge is recognized and can be cleaned up manually.
- A merge conflict does not delete any work.
- Current commands, Orca hooks, and tests remain functional.
- The new implementation does not add a terminal emulator or PTY daemon.
- New responsibilities do not increase `lifecycle.py`, `auth.py`, or
  `doctor.py`; they enter the corresponding domain modules.

---

## 16. Expected outcome

`agent-sandbox` gains its own operational interface and no longer depends on
the health of Orca's PTY. The operator keeps the useful part of the experience:
projects, a primary checkout, worktrees, agent selection, multiple sessions,
and transparent resumption.

The security runtime remains intact. New behavior grows through deep, testable
modules, and large files shrink incrementally without repeating a long and
unstable migration of the entire environment.
