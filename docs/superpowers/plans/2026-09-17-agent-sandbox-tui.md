# Agent Sandbox TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide Orca-independent terminal access, persistent multi-agent
sessions, a project/worktree TUI, and evidence-based worktree cleanup without
changing the existing sandbox security model.

**Architecture:** Keep the current Podman/systemd runtime authoritative and add
small project, checkout, session, agent, and connection modules around it. Ship
usable SSH access first, then add tmux-backed sessions, then the curses TUI and
worktree lifecycle. Every stage preserves existing CLI and Orca recipe output.

**Tech Stack:** Python >= 3.11 standard library, `unittest`, Git, OpenSSH,
tmux inside the agent image, rootless Podman >= 6.1, user systemd, and curses.

**Spec:**
[`docs/superpowers/specs/2026-09-17-agent-sandbox-tui-design.md`](../specs/2026-09-17-agent-sandbox-tui-design.md)

## Global Constraints

- The existing Podman topology, systemd units, network isolation, credential
  volumes, session volumes, SSH readiness gates, and Orca recipe schema remain
  unchanged unless a task explicitly names the changed contract.
- Python host code uses only the standard library.
- The primary checkout means the repository's primary working copy; it does
  not imply the `main` branch.
- Git, Podman, systemd, tmux, and provider-native state remain authoritative.
  Registries store relationships only.
- Control state lives under `~/.local/state/agent-sandbox/`, outside every
  agent-writable mount. Files use mode `0600`; directories use mode `0700`.
- No registry stores credentials, prompts, model output, or transcripts.
- Unknown liveness becomes `recovery_required`; it never starts a duplicate
  process.
- The TUI never uses `git worktree remove --force`, deletes a remote branch,
  changes the primary checkout's branch implicitly, or removes a checkout
  without positive ancestry evidence.
- Unit tests import `asb_test_isolation` first and never access real Podman
  volumes, systemd units, credentials, SSH endpoints, or tmux servers.
- Integration resources use the `asb-test-` prefix and register cleanup with
  `SandboxFixture`.
- Each task is reviewed independently. Run `git diff --check`, the focused
  tests, and the full unit suite before its commit.
- Use `commit-curator` for every commit. Do not push. Keep Graphify paused
  throughout plan execution, then run one `graphify update .` and create the
  dedicated `🕸️ sync knowledge graph` commit after the final review.
- Runtime or image rollout requires a human checkpoint after Tasks 1-5 pass.
  Until that checkpoint, no running workspace is restarted or rebuilt.

## Standard Verification Commands

Run from the repository root:

```bash
python3 -m unittest discover -s tests/unit -v
python3 -m unittest discover -s tests/integration -v
bash tests/test-recipe.sh
bash tests/test-image.sh
git diff --check
```

Live provider tests remain opt-in and are not part of the default suite:

```bash
ASB_LIVE_AUTH=1 python3 -m unittest discover \
  -s tests/integration -p 'test_provider_auth.py' -v
```

---

### Task 1: Domain types and immutable identities

**Files:**
- Create: `cli/asb/projects/__init__.py`
- Create: `cli/asb/projects/model.py`
- Create: `cli/asb/checkouts/__init__.py`
- Create: `cli/asb/checkouts/model.py`
- Create: `cli/asb/sessions/__init__.py`
- Create: `cli/asb/sessions/model.py`
- Test: `tests/unit/test_domain_models.py`

**Interfaces:**
- Produces `ProjectId`, `CheckoutId`, `SessionId`, `TerminalId`, and
  `ProviderSessionId` as validated string value objects.
- Produces `Project`, `Checkout`, `AgentSession`, `CheckoutKind`, `AgentKind`,
  `CheckoutState`, and `SessionState`.
- IDs accept lowercase ASCII letters, digits, `_`, and `-`, with a maximum of
  64 characters. They reject empty input, path separators, whitespace, and
  shell metacharacters.

- [ ] **Step 1: Write the failing model tests**

Create `tests/unit/test_domain_models.py` with the isolation import first and
these contract cases:

```python
import asb_test_isolation  # noqa: F401

import unittest
from pathlib import Path

from asb.checkouts.model import Checkout, CheckoutId, CheckoutKind, CheckoutState
from asb.projects.model import Project, ProjectId
from asb.sessions.model import AgentKind, AgentSession, SessionId, SessionState


class TestIdentifiers(unittest.TestCase):
    def test_rejects_paths_whitespace_and_shell_text(self):
        for value in ("", "../x", "a/b", "two words", "x;rm"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SessionId(value)

    def test_accepts_generated_identifier(self):
        self.assertEqual(str(SessionId("s-0123456789abcdef")),
                         "s-0123456789abcdef")


class TestDomainRelationships(unittest.TestCase):
    def test_primary_is_a_checkout_kind_not_a_branch(self):
        project = Project(ProjectId("p-1"), Path("/repo"), "develop",
                          Path("/worktrees"))
        checkout = Checkout(CheckoutId("c-1"), project.id, Path("/repo"),
                            CheckoutKind.PRIMARY, "feat/x",
                            CheckoutState.CLEAN, "ws-1")
        self.assertEqual(checkout.branch, "feat/x")
        self.assertEqual(checkout.kind, CheckoutKind.PRIMARY)

    def test_session_identity_is_independent_of_terminal(self):
        session = AgentSession.new(CheckoutId("c-1"), AgentKind.CODEX,
                                   Path("/repo"), "Plan work")
        changed = session.with_state(SessionState.DETACHED,
                                     terminal_id="tmux-2")
        self.assertEqual(changed.id, session.id)
        self.assertNotEqual(changed.terminal_id, session.terminal_id)
```

- [ ] **Step 2: Run the tests and confirm the missing-package failure**

Run:

```bash
python3 -m unittest discover -s tests/unit -p 'test_domain_models.py' -v
```

Expected: `ModuleNotFoundError` for the first new package.

- [ ] **Step 3: Implement the value objects and dataclasses**

Use one shared validation shape in each package without a general utility
module. The public form of an ID is:

```python
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class SessionId(str):
    def __new__(cls, value: str):
        if not isinstance(value, str) or not _ID.fullmatch(value):
            raise ValueError(f"invalid session id: {value!r}")
        return super().__new__(cls, value)
```

Use `StrEnum` for kinds and states and frozen dataclasses for records. Generate
new IDs from `secrets.token_hex(8)` with prefixes `p-`, `c-`, and `s-`.
`AgentSession.with_state()` uses `dataclasses.replace()` and never mutates an
existing record.

- [ ] **Step 4: Verify both branches of every validator**

Run the focused test, then the full unit suite:

```bash
python3 -m unittest discover -s tests/unit -p 'test_domain_models.py' -v
python3 -m unittest discover -s tests/unit -v
git diff --check
```

- [ ] **Step 5: Commit the isolated domain model**

Use `commit-curator` with title:

```text
✨ add stable project and session identities: domain model
```

Stage only the six package files and `tests/unit/test_domain_models.py`.

---

### Task 2: Atomic project registry

**Files:**
- Create: `cli/asb/projects/registry.py`
- Test: `tests/unit/test_project_registry.py`

**Interfaces:**
- Consumes `Project` and `ProjectId` from Task 1.
- Produces `ProjectRegistry(path: Path)`, `list() -> list[Project]`,
  `get(project_id: ProjectId) -> Project`, `add(primary: Path,
  integration_branch: str | None, worktree_root: Path) -> Project`, and
  `remove(project_id: ProjectId) -> None`.
- Produces `CheckoutBinding(checkout_id, project_id, source_path, workspace)`
  plus `bindings(project_id)`, `bind_checkout()`, and `unbind_checkout()`.
  `source_path` is the operator checkout; the sandbox execution checkout is
  always resolved live from `ConnectionInfo.project_root`.
- Project identity is the SHA-256 prefix of the canonical Git common directory,
  obtained with `git rev-parse --path-format=absolute --git-common-dir`.
- Schema 1 JSON is written atomically while holding an exclusive `fcntl` lock.

- [ ] **Step 1: Write registry failure and persistence tests**

Create temporary Git repositories and cover: primary checkout discovery,
linked-worktree deduplication through the common directory, missing Git repo,
corrupt JSON, concurrent sequential writers through two registry instances,
file mode, directory mode, and a missing project ID.

Core assertions:

```python
first = registry.add(repo, "main", tmp / "worktrees")
second = registry.add(linked_worktree, "main", tmp / "worktrees")
self.assertEqual(first.id, second.id)
self.assertEqual(registry.path.stat().st_mode & 0o777, 0o600)
self.assertEqual(registry.path.parent.stat().st_mode & 0o777, 0o700)
self.assertEqual(json.loads(registry.path.read_text())["schemaVersion"], 1)
```

- [ ] **Step 2: Confirm RED**

```bash
python3 -m unittest discover -s tests/unit -p 'test_project_registry.py' -v
```

Expected: import failure for `asb.projects.registry`.

- [ ] **Step 3: Implement locked read-modify-write**

Store this shape only:

```json
{
  "schemaVersion": 1,
  "projects": [
    {
      "id": "p-0123456789abcdef",
      "primary": "/absolute/repo",
      "gitCommonDir": "/absolute/repo/.git",
      "integrationBranch": "main",
      "worktreeRoot": "/absolute/worktrees",
      "checkouts": [{
        "id": "c-0123456789abcdef",
        "sourcePath": "/absolute/repo",
        "workspace": "repo-a1b2c3d4"
      }]
    }
  ]
}
```

Open `<registry>.lock` with mode `0600`, acquire `LOCK_EX`, reload inside the
lock, write a same-directory temporary file with `os.open(..., 0o600)`, call
`os.fsync()`, and finish with `os.replace()`. Reject unknown schema versions
and non-object roots without overwriting them.

- [ ] **Step 4: Verify registry durability and isolation**

```bash
python3 -m unittest discover -s tests/unit -p 'test_project_registry.py' -v
python3 -m unittest discover -s tests/unit -v
git diff --check
```

- [ ] **Step 5: Commit the registry**

Use `commit-curator` with title:

```text
✨ add atomic project registry: project discovery
```

---

### Task 3: Typed runtime connection discovery

**Files:**
- Create: `cli/asb/runtime/__init__.py`
- Create: `cli/asb/runtime/connection.py`
- Create: `cli/asb/runtime/sandbox.py`
- Modify: `cli/asb/projects/registry.py`
- Modify: `cli/asb/lifecycle.py:892-910`
- Test: `tests/unit/test_runtime_connection.py`
- Modify tests: `tests/unit/test_lifecycle.py`

**Interfaces:**
- Produces frozen `ConnectionInfo(workspace, host, port, username,
  identity_file, project_root)`.
- Produces `resolve_connection(workspace: str) -> ConnectionInfo` by checking
  the existing agent container and reading the live Podman port, origin, SSH
  key, and project root.
- Produces `ConnectionInfo.ssh_argv(command: tuple[str, ...] = ()) -> list[str]`.
- Produces `SandboxRuntime.discover(project)`, `binding_for(checkout)`, and
  `ensure(checkout)`. Discovery associates existing workspace state with its
  operator origin; `ensure()` delegates to the current lifecycle only when no
  live binding exists and records the binding only after readiness succeeds.
- `lifecycle.emit()` delegates serialization to `ConnectionInfo` but emits the
  exact existing JSON fields and no additional stdout.

- [ ] **Step 1: Write contract tests around current output**

Test exact SSH arguments and exact lifecycle JSON:

```python
info = ConnectionInfo("ws-1", "127.0.0.1", 2222, "v",
                      Path("/keys/id_ed25519"), Path("/sandbox/repo"))
self.assertEqual(info.ssh_argv(("pwd",)), [
    "ssh", "-tt", "-o", "IdentitiesOnly=yes", "-o",
    "StrictHostKeyChecking=accept-new", "-i", "/keys/id_ed25519",
    "-p", "2222", "--", "v@127.0.0.1", "pwd",
])
self.assertEqual(info.to_lifecycle_payload(), {
    "workspace": "ws-1", "port": 2222, "user": "v",
    "project_root": "/sandbox/repo",
})
```

Also assert that missing container, missing origin, missing port, corrupt port,
and missing key each raise `PodmanError` without printing connection JSON.

- [ ] **Step 2: Confirm RED**

```bash
python3 -m unittest discover -s tests/unit -p 'test_runtime_connection.py' -v
```

- [ ] **Step 3: Extract connection resolution without changing readiness**

Keep `up()` and `resume()` readiness order intact. `resolve_connection()` may
run only after their existing readiness gates. The SSH argument builder uses a
list, validates port range `1..65535`, puts `--` before the destination, and
encodes a remote argument tuple as one `shlex.join()` command string. It never
invokes a local shell. Existing-workspace discovery uses the same origin lookup
as lifecycle and never starts, resumes, or removes a container.

For a missing runtime, `SandboxRuntime.ensure()` invokes the stable CLI boundary
with an injected runner:

```python
[str(root / "cli" / "asb-agent"), "up", "--workspace", workspace,
 "--repo", str(checkout.source_path)]
```

It captures stdout, requires exit zero, parses the existing lifecycle payload,
then calls `resolve_connection()` for live evidence. This avoids a second
in-process implementation of workspace startup and prevents lifecycle output
from corrupting the TUI screen.

- [ ] **Step 4: Prove compatibility through both producer paths**

```bash
python3 -m unittest discover -s tests/unit -p 'test_runtime_connection.py' -v
python3 -m unittest discover -s tests/unit -p 'test_lifecycle.py' -v
bash tests/test-recipe.sh
python3 -m unittest discover -s tests/unit -v
git diff --check
```

- [ ] **Step 5: Commit the extraction**

Use `commit-curator` with title:

```text
♻️ extract typed sandbox connections: runtime boundary
```

---

### Task 4: Direct SSH access without Orca

**Files:**
- Create: `cli/asb/interfaces/__init__.py`
- Create: `cli/asb/interfaces/cli.py`
- Modify: `cli/asb-agent`
- Modify tests: `tests/unit/test_cli_dispatch.py`
- Test: `tests/unit/test_connect_cli.py`
- Update: `docs/domains/sandbox/lifecycle.md`

**Interfaces:**
- Produces `connect(workspace: str, *, execute=os.execvp) -> int`.
- Adds `asb-agent connect --workspace <id>`.
- The command resolves live connection data and replaces the host process with
  SSH running `sh -lc 'cd -- <quoted-project-root> && exec
  ${SHELL:-/bin/bash} -l'`.

- [ ] **Step 1: Write CLI parsing and execution tests**

Patch `resolve_connection` and inject a recorder for `execute`. Assert parser
registration, dispatch, exact argv, and no shell subprocess:

```python
calls = []
with mock.patch("asb.interfaces.cli.resolve_connection", return_value=info):
    rc = connect("ws-1", execute=lambda file, argv: calls.append((file, argv)))
self.assertEqual(rc, 0)
self.assertEqual(calls[0][0], "ssh")
self.assertIn("sh -lc", calls[0][1][-1])
self.assertIn("cd -- /sandbox/repo && exec ${SHELL:-/bin/bash} -l",
              calls[0][1][-1])
```

Use `shlex.quote()` only for the remote project path; local SSH arguments stay
separate.

- [ ] **Step 2: Confirm parser and module failures**

```bash
python3 -m unittest discover -s tests/unit -p 'test_connect_cli.py' -v
python3 -m unittest discover -s tests/unit -p 'test_cli_dispatch.py' -v
```

- [ ] **Step 3: Implement the smallest usable Orca-independent path**

Keep `cli/asb-agent` as parser and dispatcher only. Put process replacement in
`interfaces/cli.py`. Do not start, resume, rebuild, or mutate a workspace from
`connect`; a stopped workspace returns the existing infrastructure error and
guidance to run `asb-agent resume`.

- [ ] **Step 4: Verify no current command changed**

```bash
python3 -m unittest discover -s tests/unit -p 'test_connect_cli.py' -v
python3 -m unittest discover -s tests/unit -p 'test_cli_dispatch.py' -v
bash tests/test-recipe.sh
python3 -m unittest discover -s tests/unit -v
git diff --check
```

- [ ] **Step 5: Commit the first operator-facing capability**

Use `commit-curator` with title:

```text
✨ add direct sandbox shell access: SSH interface
```

This is the first deployable checkpoint. It requires no image rebuild and no
workspace restart.

---

### Task 5: Provider drivers with explicit resume support

**Files:**
- Create: `cli/asb/agents/__init__.py`
- Create: `cli/asb/agents/base.py`
- Create: `cli/asb/agents/codex.py`
- Create: `cli/asb/agents/claude.py`
- Create: `cli/asb/agents/antigravity.py`
- Test: `tests/unit/test_agent_drivers.py`
- Create: `docs/validation/2026-09-17-agent-session-contracts.md`

**Interfaces:**
- Produces `LaunchCommand(argv: tuple[str, ...], env: Mapping[str, str])`.
- Produces `AgentAvailability(available: bool, version: str | None,
  resume_supported: bool, reason: str)`.
- Produces abstract `AgentDriver.launch(cwd)`, `resume(cwd, session_id)`,
  `discover_session_id(evidence)`, and `probe(run)`.
- Produces `SessionEvidence` plus `capture_before(cwd)` and
  `capture_after(baseline)`. Evidence contains paths and sanitized metadata,
  never transcript content.
- Codex resumes only with `("codex", "resume", provider_session_id)`.
- Claude resumes only with `("claude", "--resume", provider_session_id)`.
- Antigravity launches with `("agy",)` and resumes with
  `("agy", "--conversation", provider_session_id)` after the image binary
  confirms that option. The host binary observed during planning exposes
  `--conversation`; the image version remains the authoritative gate.

- [ ] **Step 1: Characterize installed binaries without launching a model**

Record binary versions and sanitized `--help` evidence for launch, resume, and
session ID options. Run help/version commands only; do not send prompts. In the
validation document, use the columns `provider`, `version`, `launch`, `resume`,
`session-id-source`, and `decision`. Record unsupported features explicitly.

- [ ] **Step 2: Write deterministic driver tests**

```python
self.assertEqual(CodexDriver().launch(Path("/repo")).argv, ("codex",))
self.assertEqual(CodexDriver().resume(Path("/repo"), "abc").argv,
                 ("codex", "resume", "abc"))
self.assertEqual(ClaudeDriver().resume(Path("/repo"), "abc").argv,
                 ("claude", "--resume", "abc"))
self.assertEqual(AntigravityDriver().resume(Path("/repo"), "abc").argv,
                 ("agy", "--conversation", "abc"))
```

Cover invalid provider IDs, missing binaries, version timeout, unknown version
output, and a help contract that lacks the expected resume option. A missing
option makes that installed driver return `resume_supported=False` and makes
`resume()` raise `ResumeUnsupported`.

- [ ] **Step 3: Confirm RED and implement adapters**

```bash
python3 -m unittest discover -s tests/unit -p 'test_agent_drivers.py' -v
```

Drivers return commands; they do not spawn processes. `probe()` receives an
injected runner with a five-second timeout and sanitizes output to the first
line. No driver imports auth internals in this stage. `SessionEvidence` contains
the provider state paths present before launch and after the first healthy
probe. Codex accepts exactly one new JSONL whose first `session_meta` payload
contains an `id`; Claude and Antigravity use the exact metadata location proven
in the validation document. Zero or multiple candidates return `None`.

- [ ] **Step 4: Verify driver boundaries**

```bash
python3 -m unittest discover -s tests/unit -p 'test_agent_drivers.py' -v
python3 -m unittest discover -s tests/unit -v
git diff --check
```

- [ ] **Step 5: Commit the drivers and evidence**

Use `commit-curator` with title:

```text
✨ add provider session drivers: agent boundary
```

### Human checkpoint after Task 5

Review Tasks 1-5 and exercise `asb-agent connect` against one existing
workspace. Confirm that Orca recipes still emit byte-for-byte compatible JSON.
Proceed to Task 6 only after accepting an image rebuild that adds tmux. The
checkpoint does not require destroying, purging, or recreating any workspace.

---

### Task 6: Atomic session registry

**Files:**
- Create: `cli/asb/sessions/store.py`
- Test: `tests/unit/test_session_store.py`

**Interfaces:**
- Produces `SessionStore(path: Path)` with `list()`, `get()`, `insert()`,
  `replace()`, and `remove()`.
- Schema 1 stores session relationships and observed state only.
- `replace()` requires matching IDs and increments integer `revision`.

- [ ] **Step 1: Write persistence and corruption tests**

Assert round-trip of every session state, missing file as empty state, duplicate
ID rejection, stale revision rejection, unknown schema rejection, corrupt JSON
preservation, no prompt/output fields, mode `0600`, directory `0700`, and two
store instances updating without lost writes.

Expected stored object:

```json
{
  "schemaVersion": 1,
  "revision": 3,
  "sessions": [{
    "id": "s-0123456789abcdef",
    "checkoutId": "c-0123456789abcdef",
    "agent": "codex",
    "title": "Plan work",
    "cwd": "/sandbox/repo",
    "terminalId": "asb-s-0123456789abcdef",
    "providerSessionId": null,
    "state": "detached",
    "lastHealthyAt": "2026-09-17T20:00:00Z"
  }]
}
```

- [ ] **Step 2: Confirm RED, then implement using the Task 2 write pattern**

```bash
python3 -m unittest discover -s tests/unit -p 'test_session_store.py' -v
```

Repeat the atomic write code inside the session package rather than creating a
cross-domain storage framework. Validate every decoded field before returning
records.

- [ ] **Step 3: Verify every decoder branch**

```bash
python3 -m unittest discover -s tests/unit -p 'test_session_store.py' -v
python3 -m unittest discover -s tests/unit -v
git diff --check
```

- [ ] **Step 4: Commit the store**

Use `commit-curator` with title:

```text
✨ add atomic session registry: session persistence
```

---

### Task 7: tmux terminal backend and image capability

**Files:**
- Create: `cli/asb/sessions/terminal.py`
- Modify: `image/Containerfile`
- Modify: `tests/test-image.sh`
- Test: `tests/unit/test_terminal_backend.py`

**Interfaces:**
- Produces `TmuxTerminal(connection: ConnectionInfo, run=subprocess.run)`.
- Produces `Liveness.ALIVE`, `Liveness.DEAD`, and `Liveness.UNKNOWN`.
- Produces `start(terminal_id, cwd, command)`, `probe(terminal_id)`,
  `attach_argv(terminal_id)`, `stop(terminal_id)`, and `capture_exit_status()`.
- `probe()` returns `ALIVE`, `DEAD`, or `UNKNOWN`; SSH/timeout failures are
  `UNKNOWN`, never `DEAD`.

- [ ] **Step 1: Write branch-complete backend tests**

Assert exact remote argv for start, probe, attach, and stop. Cover tmux exit 0,
tmux exit 1 with explicit missing-session output, SSH exit 255, timeout, invalid
terminal ID, and a command containing spaces. The start command must resemble:

```text
tmux new-session -d -s asb-s-0123456789abcdef -c /sandbox/repo -- codex
```

All local subprocess calls receive argument lists and `shell=False`.

- [ ] **Step 2: Confirm RED**

```bash
python3 -m unittest discover -s tests/unit -p 'test_terminal_backend.py' -v
```

- [ ] **Step 3: Add tmux and implement the backend**

Add `tmux` to the existing Debian package installation line. Add an image test
that checks `tmux -V` in the built image. Do not change entrypoint, systemd,
Podman arguments, mounts, networking, or SSH configuration.

- [ ] **Step 4: Verify image and backend**

```bash
python3 -m unittest discover -s tests/unit -p 'test_terminal_backend.py' -v
bash tests/test-image.sh
python3 -m unittest discover -s tests/unit -v
git diff --check
```

- [ ] **Step 5: Commit the isolated image change**

Use `commit-curator` with title:

```text
✨ add tmux session backend: terminal persistence
```

---

### Task 8: Session manager and recovery state machine

**Files:**
- Create: `cli/asb/sessions/manager.py`
- Test: `tests/unit/test_session_manager.py`

**Interfaces:**
- Consumes `SessionStore`, `TmuxTerminal`, and the driver map.
- Produces `StartSession`, `AttachResult`, `ResumeResult`, and
  `SessionManager.list/start/attach/suspend/resume/stop/reconcile`.
- State changes are persisted only after terminal evidence confirms the action.
- A start snapshots provider metadata before launch, performs one bounded
  discovery after the terminal becomes healthy, and persists a provider ID only
  when the driver finds exactly one valid candidate. Missing or ambiguous
  evidence leaves the ID empty and never guesses from "most recent" state.

- [ ] **Step 1: Write the state-transition matrix tests**

Use fakes rather than real SSH/tmux. Cover these exact transitions:

| Stored state | Probe | Provider ID | Result |
|---|---|---|---|
| `running` | `ALIVE` | any | `detached`, same terminal |
| `detached` | `DEAD` | valid and supported | `starting`, native resume |
| `detached` | `DEAD` | absent/unsupported | `recovery_required` |
| any active | `UNKNOWN` | any | `recovery_required`, no launch |
| `completed` | any | any | remains `completed`, no launch |

Also prove two sessions in one checkout get distinct IDs and tmux names, a
failed start becomes `failed`, a unique discovered provider ID is persisted,
ambiguous discovery stores no ID, and a stop is recorded only after a dead
probe.

- [ ] **Step 2: Confirm RED**

```bash
python3 -m unittest discover -s tests/unit -p 'test_session_manager.py' -v
```

- [ ] **Step 3: Implement transitions as explicit branches**

The start path is:

```python
record = store.insert(AgentSession.new(request.checkout_id, request.agent,
                                       request.cwd, request.title))
record = store.replace(record.with_state(
    SessionState.STARTING,
    terminal_id=terminal_name(record.id),
))
baseline = driver.capture_before(request.cwd)
terminal.start(terminal_name(record.id), request.cwd,
               driver.launch(request.cwd))
if terminal.probe(terminal_name(record.id)) is not Liveness.ALIVE:
    return store.replace(record.with_state(SessionState.FAILED))
provider_id = driver.discover_session_id(driver.capture_after(baseline))
return store.replace(record.with_state(
    SessionState.RUNNING,
    provider_session_id=provider_id,
    last_healthy_at=clock(),
))
```

Persist the latest returned record at every step so revisions remain correct.
Do not catch `BaseException`; cancellation remains visible to the caller.

- [ ] **Step 4: Audit branch shape and run tests**

For every conditional introduced in `manager.py`, list the entering test and
input in the task report. Then run:

```bash
python3 -m unittest discover -s tests/unit -p 'test_session_manager.py' -v
python3 -m unittest discover -s tests/unit -v
git diff --check
```

- [ ] **Step 5: Commit the manager**

Use `commit-curator` with title:

```text
✨ add evidence-based session recovery: session manager
```

---

### Task 9: Session CLI and full-screen attachment

**Files:**
- Modify: `cli/asb/interfaces/cli.py`
- Modify: `cli/asb-agent`
- Test: `tests/unit/test_session_cli.py`
- Test: `tests/integration/test_session_lifecycle.py`
- Modify tests: `tests/unit/test_cli_dispatch.py`
- Update: `docs/domains/sandbox/lifecycle.md`

**Interfaces:**
- Adds `session list`, `session start`, `session attach`, `session stop`, and
  `session resume` nested commands.
- `session start` requires `--checkout`, `--agent`, and optional `--title`.
  Workspace selection comes from the persisted checkout binding.
- `session attach` replaces the CLI process with the SSH/tmux argv and returns
  control to the invoking shell after the operator detaches from tmux. The TUI
  uses the same argv through a child subprocess so it can restore curses.

- [ ] **Step 1: Write parser, dispatch, and argv tests**

Assert every registered nested command has dispatch, invalid agents fail in
argparse, list emits schema 1 JSON with `--json`, text output contains no
provider-native transcript, and attach targets exactly one validated tmux ID.

- [ ] **Step 2: Confirm RED**

```bash
python3 -m unittest discover -s tests/unit -p 'test_session_cli.py' -v
python3 -m unittest discover -s tests/unit -p 'test_cli_dispatch.py' -v
```

- [ ] **Step 3: Implement composition in the interface module**

Construct managers from the project registry, runtime resolver, session store,
terminal backend, and driver map. Keep construction in a `session_services()`
factory so tests inject fakes and do not touch the host. Starting the first
session for a checkout calls `SandboxRuntime.ensure(checkout)`; later sessions
reuse the persisted checkout/workspace binding.

- [ ] **Step 4: Verify compatibility and an isolated integration path**

Add one integration case using an `asb-test-` workspace that starts a harmless
`sh -lc 'printf ready; exec sleep 60'` session, detaches, lists it, reattaches,
and stops it. The fixture must register the tmux session for cleanup.

```bash
python3 -m unittest discover -s tests/unit -p 'test_session_cli.py' -v
python3 -m unittest discover -s tests/unit -p 'test_cli_dispatch.py' -v
python3 -m unittest discover -s tests/integration \
  -p 'test_session_lifecycle.py' -v
bash tests/test-recipe.sh
git diff --check
```

- [ ] **Step 5: Commit the session CLI**

Use `commit-curator` with title:

```text
✨ add persistent agent session commands: CLI interface
```

---

### Task 10: Read-only curses tree and action controller

**Files:**
- Create: `cli/asb/interfaces/tui.py`
- Create: `cli/asb/interfaces/tui_model.py`
- Modify: `cli/asb-agent`
- Test: `tests/unit/test_tui_model.py`
- Test: `tests/unit/test_tui_controller.py`
- Modify tests: `tests/unit/test_cli_dispatch.py`

**Interfaces:**
- Adds `asb-agent tui`.
- Produces pure `build_tree(projects, checkouts, sessions) -> tuple[TreeRow, ...]`.
- Produces `TuiController.refresh()`, `toggle()`, `move()`, `activate()`, and
  `quit()`; curses only renders controller state and maps keys.
- Initial keys: arrows or `j/k`, `Enter`, `n` new session, `w` new worktree,
  `f` finish, `d` detach/stop menu, `r` refresh, and `q` quit.

- [ ] **Step 1: Write pure tree tests**

Cover project ordering, primary badge independent of branch, linked worktrees,
multiple sessions in one checkout, detached `HEAD`, collapsed nodes, empty
projects, stale session state after reconciliation, and stable selection after
refresh.

- [ ] **Step 2: Write controller tests with a fake screen**

Assert `Enter` on a session calls attach once, curses suspension and restoration
occur around attach even on failure, `q` never calls stop, terminal resize
redraws, and a narrow terminal displays a bounded message instead of raising.

- [ ] **Step 3: Confirm RED and implement the pure model first**

```bash
python3 -m unittest discover -s tests/unit -p 'test_tui_model.py' -v
python3 -m unittest discover -s tests/unit -p 'test_tui_controller.py' -v
```

Render only precomputed `TreeRow` values. Do not run Git, Podman, SSH, tmux, or
provider commands from drawing code. `curses.wrapper()` owns setup/teardown.
The refresh service reads the displayed branch from the sandbox execution
checkout at `ConnectionInfo.project_root`, because that is where an agent runs
`git switch`. It retains the operator checkout path only for worktree ownership
and integration.

- [ ] **Step 4: Verify TUI behavior without a live terminal**

```bash
python3 -m unittest discover -s tests/unit -p 'test_tui_*.py' -v
python3 -m unittest discover -s tests/unit -p 'test_cli_dispatch.py' -v
python3 -m unittest discover -s tests/unit -v
git diff --check
```

- [ ] **Step 5: Commit the TUI shell**

Use `commit-curator` with title:

```text
✨ add project and session navigator: curses TUI
```

---

### Task 11: Worktree discovery and safe creation

**Files:**
- Create: `cli/asb/checkouts/git.py`
- Create: `cli/asb/checkouts/manager.py`
- Modify: `cli/asb/interfaces/tui.py`
- Modify: `cli/asb/interfaces/tui_model.py`
- Test: `tests/unit/test_checkout_git.py`
- Test: `tests/unit/test_checkout_manager.py`

**Interfaces:**
- Produces `GitRepository.run(*args)`, `common_dir()`, `worktrees()`,
  `branch()`, `status()`, `is_ancestor()`, and `remote_default_branch()`.
- Produces `CreateCheckout(branch, base, path)` and
  `CheckoutManager.list/inspect/create`.
- Every Git call uses `git -C <path>` with argument lists and captured stderr.

- [ ] **Step 1: Write Git parser tests using real temporary repositories**

Use `git worktree list --porcelain -z` and test spaces/newlines in paths,
primary detection, detached `HEAD`, dirty state, absent `origin/HEAD`,
unambiguous `origin/HEAD`, invalid branch names, and ancestry true/false.

- [ ] **Step 2: Write creation transaction tests**

Cover configured base, explicit selected-checkout base, ambiguous missing base,
existing branch, existing path, path outside configured root, Git failure before
creation, Git failure after branch creation, and registry failure after a
successful Git command. Rollback removes only the branch/worktree created by
the current transaction and only after proving ownership.

- [ ] **Step 3: Confirm RED and implement without shell interpolation**

```bash
python3 -m unittest discover -s tests/unit -p 'test_checkout_*.py' -v
```

The create command is exactly:

```python
["git", "-C", str(project.primary), "worktree", "add", "-b",
 request.branch, str(request.path), request.base]
```

Validate the branch first with `git check-ref-format --branch`. Resolve both
the configured root and requested parent before checking containment.

- [ ] **Step 4: Connect preview and confirmation to the TUI**

The confirmation view shows project, base commit/branch, new branch, absolute
path, and whether the operation creates a branch. Registration happens only
after Git returns zero and inspection confirms the new checkout. Runtime
creation remains lazy: the first session calls `SandboxRuntime.ensure()`, which
creates the sandbox clone from this operator worktree and stores its binding.

- [ ] **Step 5: Verify creation and existing behavior**

```bash
python3 -m unittest discover -s tests/unit -p 'test_checkout_*.py' -v
python3 -m unittest discover -s tests/unit -p 'test_tui_*.py' -v
python3 -m unittest discover -s tests/unit -v
git diff --check
```

- [ ] **Step 6: Commit worktree creation**

Use `commit-curator` with title:

```text
✨ add transactional worktree creation: checkout manager
```

---

### Task 12: Merge evidence, finish, and idempotent cleanup

**Files:**
- Modify: `cli/asb/checkouts/model.py`
- Modify: `cli/asb/checkouts/manager.py`
- Modify: `cli/asb/runtime/sandbox.py`
- Modify: `cli/asb/interfaces/tui.py`
- Modify: `cli/asb/interfaces/tui_model.py`
- Test: `tests/unit/test_checkout_finish.py`
- Modify tests: `tests/unit/test_runtime_connection.py`
- Test: `tests/integration/test_worktree_finish.py`
- Update: `docs/domains/sandbox/lifecycle.md`

**Interfaces:**
- Produces `FinishCheckout(checkout_id, target_branch,
  cleanup_after_merge, delete_merged_branch)`.
- Produces `FinishResult(state, source_commit, target_commit, message)` with
  states `MERGED`, `CONFLICT`, `BLOCKED`, `CLEANUP_PENDING`, and `CLEANED`.
- `cleanup(checkout_id)` accepts only a non-primary, clean checkout with no live
  sessions whose source commit is an ancestor of the resolved target.
- Produces `SandboxRuntime.export_head(binding) -> (commit, namespaced_ref)` by
  invoking the existing `asb-agent pull` contract and resolving the resulting
  `refs/asb/<workspace>/<validated-branch>` in the operator repository.

- [ ] **Step 1: Write the destructive-operation matrix before code**

Use temporary Git repositories and fake session liveness. Cover: primary
checkout, dirty source, active session, unknown liveness, missing target,
target checked out but dirty, no checkout of target, merge conflict, merge exit
zero without ancestry, ancestry proven, external merge, worktree removal
failure, local branch deletion disabled/enabled, and remote branch preservation.
Also cover a sandbox execution branch that differs from the operator worktree,
export of its exact `HEAD`, export failure, and a successful export followed by
merge.

For every blocked case assert that both the source path and branch still exist.
For successful cleanup assert the source commit remains reachable from the
target.

- [ ] **Step 2: Confirm RED**

```bash
python3 -m unittest discover -s tests/unit -p 'test_checkout_finish.py' -v
```

- [ ] **Step 3: Implement evidence collection before mutation**

The operation order is fixed. `export_head()` fetches the exact commit from the
sandbox clone into `refs/asb/<workspace>/<branch>` in the operator repository;
it does not trust a same-named host branch to already contain agent work:

```python
status = inspect(source)
sessions = session_manager.list(source.id)
target = locate_clean_target_checkout(request.target_branch)
source_commit, source_ref = runtime.export_head(source.workspace)
git.merge(target.path, source_ref)  # git merge --no-edit <validated-ref>
target_commit = git.rev_parse(target.path, "HEAD")
if not git.is_ancestor(source_commit, target_commit):
    return FinishResult.cleanup_pending(source_commit, target_commit,
                                        "integration is not proven")
return cleanup_after_proof(...)
```

Do not insert `--` between `merge` and the branch; validate the branch with Git
before constructing the namespaced ref, and validate the final ref with
`git check-ref-format`. On conflict, leave Git's conflict state intact and
return concrete recovery guidance. Delete the operator worktree and its sandbox
binding only after ancestry is proven. With cleanup enabled, the sequence is:
purge the bound sandbox through an internal evidence-bearing runtime call,
remove the operator worktree without force, optionally delete the merged local
branch, then remove the registry binding. A failure at any step returns
`CLEANUP_PENDING`; retry re-inspects which resources remain and never repeats a
destructive operation blindly.

- [ ] **Step 4: Implement idempotent cleanup**

Re-running cleanup after Git removed the worktree but before registry update
must reconcile the missing path, recheck ancestry, remove the stale checkout
record, and return `CLEANED`. A missing source path without ancestry evidence is
`BLOCKED` and requires manual recovery.

- [ ] **Step 5: Add TUI confirmation and external-merge label**

Show `merged / cleanup available` only after a fresh ancestry check. The finish
confirmation includes source commit, target branch, target checkout path, and
the local-branch deletion policy. No remote deletion action exists.

- [ ] **Step 6: Verify all safety branches and integration behavior**

```bash
python3 -m unittest discover -s tests/unit -p 'test_checkout_finish.py' -v
python3 -m unittest discover -s tests/integration \
  -p 'test_worktree_finish.py' -v
python3 -m unittest discover -s tests/unit -v
bash tests/test-recipe.sh
git diff --check
```

Run `test-shape-auditor` against the Task 12 diff and fix every unentered
conditional branch before committing.

- [ ] **Step 7: Commit finish and cleanup**

Use `commit-curator` with title:

```text
✨ add evidence-based worktree cleanup: finish workflow
```

---

### Task 13: End-to-end acceptance and documentation

**Files:**
- Create: `tests/integration/test_tui_acceptance.py`
- Create: `docs/validation/2026-09-17-agent-sandbox-tui.md`
- Update: `docs/domains/sandbox/README.md`
- Update: `docs/domains/sandbox/lifecycle.md`

**Interfaces:**
- No new production interface.
- Produces a sanitized acceptance report with command, expected result, actual
  result, exit status, and cleanup evidence for every scenario.

- [ ] **Step 1: Add automated acceptance scenarios**

Exercise two sessions in one checkout, different agents using fake harmless
commands, TUI close with live tmux, reattachment, uncertain liveness, voluntary
completion, branch label refresh, dirty-worktree refusal, external merge, merge
conflict preservation, and primary-checkout refusal. Use only temporary Git
repositories and `asb-test-` runtime resources.

- [ ] **Step 2: Run the complete automated verification**

```bash
python3 -m unittest discover -s tests/unit -v
python3 -m unittest discover -s tests/integration -v
for test in tests/test-*.sh; do bash "$test"; done
git diff --check
```

Record exact failures; do not normalize a flaky or skipped required scenario
into a pass.

- [ ] **Step 3: Run the controlled human pilot**

On one disposable workspace, record these observations without credentials or
transcripts:

1. `asb-agent connect` opens the real project root.
2. A Codex session survives TUI exit and reattaches to the same tmux process.
3. A second agent can exist in the same checkout while the operator controls
   whether it runs.
4. An agent branch switch updates the TUI label.
5. External merge enables cleanup.
6. Dirty state and an active session each block cleanup.
7. Existing Orca create/resume hooks still connect.

Stop the pilot on the first unexpected runtime, auth, network, mount, or
readiness change. Preserve the workspace for diagnosis.

- [ ] **Step 4: Review before declaring acceptance**

Run `regression-sentinel`, `test-shape-auditor`, and `claim-verifier` against
the complete implementation diff. Resolve Important findings and rerun the
affected verification.

- [ ] **Step 5: Commit acceptance evidence**

Use `commit-curator` with title:

```text
📝 document TUI acceptance evidence: agent sessions
```

- [ ] **Step 6: Synchronize Graphify once**

```bash
graphify update .
git diff --check
```

Commit strictly `graphify-out/**` with the exact title:

```text
🕸️ sync knowledge graph
```

Resume the Graphify hook after the graph commit.

---

## Rollout and rollback

Tasks 1-5 can be deployed without rebuilding an image or restarting a running
workspace. Task 4 is immediately usable as the fallback terminal path.

Task 7 adds one Debian package. Build the image under its normal versioned tag,
run `tests/test-image.sh`, and validate a disposable workspace before any
existing workspace is restarted. Existing containers remain usable with
`asb-agent connect`; they simply cannot host managed tmux sessions until they
are deliberately recreated against the new image.

Every registry has an independent schema version and rejects unknown schemas
without rewriting them. Rolling back application code therefore preserves the
registry files and provider-native session volumes. Rollback never invokes
`purge`, deletes credentials, removes worktrees, or rewrites Git history.

Large-module decomposition is deliberately excluded from this rollout. It is
specified in
[`2026-09-17-agent-sandbox-module-decomposition.md`](2026-09-17-agent-sandbox-module-decomposition.md)
and begins only after this plan's acceptance report is approved.
