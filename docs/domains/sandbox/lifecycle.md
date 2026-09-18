# Workspace Lifecycle & Supervision

How a workspace starts, stops, survives a reboot and recovers, and how the
TUI runs agent sessions and worktrees on top of it (§5–§7). The model is
Emenda A's **single systemd runtime**
([spec](../../superpowers/specs/2026-09-16-single-systemd-runtime-design.md)),
validated on real boots in
[`docs/validation/startup-auth-pilot.md`](../../validation/startup-auth-pilot.md)
§6.8–§6.12.

---

## 1. Ownership: systemd starts, Podman creates

- The CLI **creates and removes** resources (networks, containers, volumes,
  unit files). **systemd starts, stops and restarts** them. Every ASB container
  is created with `--restart=no`, so `podman-restart.service` never touches
  them.
- Units run `podman start --attach` through a launcher from the versioned
  runtime copy in `~/.local/lib/agent-sandbox/runtime/<revision>/`, so a unit
  keeps working while the checkout moves on.
- Operate a supervised container only through its unit:
  `systemctl --user try-restart|restart|start asb-….service`. A direct
  `podman restart` kills the attached process and the unit's
  `ExecStopPost=podman stop` stops the container again
  ([R11](./known-regressions.md)).

### Units (`~/.config/systemd/user/`)

| Unit | Role | Starts after |
| :--- | :--- | :--- |
| `asb-network.service` | Single wait for real host connectivity. `Type=oneshot`, `RemainAfterExit=yes`, `TimeoutStartSec=infinity`; exits 0 only when a real probe to `github.com:443` succeeds | login |
| `asb-keyring.service` | Secret Service singleton; `ExecStartPost` readiness check (`runtime_check --role keyring`) | login (no network dependency) |
| `asb-<ws>-proxy.service` | Squid egress proxy | `asb-network.service` (`Requires=`) |
| `asb-<ws>-agent.service` | Agent container (SSH) | network, proxy, keyring |
| `asb-<ws>-fwd.service`, `asb-<ws>-docker.service`, service units | Optional roles | `asb-network.service` (`Requires=`) |
| `asb-<ws>.target` | Groups the workspace; **enabled** means "start at login" | — |

Container units use `Restart=always`, `RestartSec=5s` and
`StartLimitBurst=3` within `StartLimitIntervalSec=600s`.

### Boot order

With `Linger=no` (the default, kept on purpose), the user manager starts at
login, not at kernel boot. Then:

1. `asb-network.service` probes the host every 5 s and logs only state changes
   (`aguardando conectividade real`, `ainda aguardando …` every 60 s,
   `conectividade real confirmada`).
2. When it succeeds, every enabled workspace starts its proxy; the first proxy
   start creates Podman's shared rootless network namespace (`pasta`) — after
   connectivity, which is the whole point ([R10](./known-regressions.md)).
3. Agents start once their proxy and the keyring are up.

Measured: `pasta` born 105–318 ms after `asb-network.service` became active
on three real boots, including one with the cable unplugged for ~2 minutes.

Headless machines that must start workspaces before anyone logs in need
`loginctl enable-linger $USER`. That keeps services and published ports alive
with no operator present; enable it only as an explicit decision.

---

## 2. Commands and State Transitions

| Command | Effect | Preserves |
| :--- | :--- | :--- |
| `up --workspace <id> --repo <path>` | Checks host connectivity (30 s), creates clone, networks, containers and units, enables and starts the target, waits for proxy readiness, runs `mise install`, waits for SSH, prints the connection JSON | — (new container IDs and SSH port) |
| `suspend --workspace <id>` | Stops and **disables** the target: a suspended workspace stays stopped across reboots | everything |
| `resume --workspace <id>` | Checks host connectivity (30 s), enables and starts the target, probes readiness, prints the same connection JSON | container IDs, SSH port, uncommitted work |
| `reload-allowlist --workspace <id>` | Re-renders `squid.conf` from the operator's checkout and runs `systemctl --user try-restart` on the proxy unit; a suspended workspace picks it up on `resume` | agent container, SSH port |
| `down --workspace <id>` | Removes units, containers, networks and the nested-containers volume | clone under `~/asb-agent/…`, git branches, the session volume |
| `connect --workspace <id>` | Read-only: resolves the live connection and replaces the host process with `ssh` into a login shell (see §4) | everything |
| `purge --workspace <id> --yes` | `down` plus the clone, workspace state and session volume, and the project folder itself if it becomes empty | shared credentials |

`up` and `resume` print JSON on stdout only after every probe passes; any
failure exits non-zero with an empty stdout. `up` is transactional: a failed
first creation rolls back the resources it created.

---

## 3. Recovery by Category

Start with `asb-agent doctor`; each failing line carries its remediation.
Account problems are never fixed by infrastructure commands, and
infrastructure problems are never fixed by logging in again — see
[authentication.md](./authentication.md).

| Category | Symptom | Action |
| :--- | :--- | :--- |
| Host network down at boot | Workspaces not started; `asb-network.service` `activating` | Nothing: the wait finishes by itself when connectivity returns (`journalctl --user -u asb-network.service`) |
| Dead rootless uplink | `doctor`: `uplink rootless morto`; Squid answers 500/503 | With the host network up, `asb-agent suspend` then `asb-agent resume` for **every** workspace, so the namespace is recreated with egress |
| Domain blocked | `TCP_DENIED/403` in `podman logs asb-<ws>-proxy` | Add the domain to `[network].allow` in the operator's `.agent-sandbox.toml`, then `asb-agent reload-allowlist --workspace <id>` |
| Proxy probe failed, cause unknown | `doctor` points at the proxy logs | `podman logs --tail 50 asb-<ws>-proxy` |
| Service down | `doctor` lists the service | `asb-agent resume --workspace <id>`; if it keeps failing, `podman logs <service container>` |
| SSH / agent stopped | `doctor`: workspace `stopped` | `asb-agent resume --workspace <id>` |
| Keyring stopped | `doctor`: `asb-keyring parado` | `systemctl --user restart asb-keyring.service` |
| Unit gave up | `systemctl --user status` shows `start-limit-hit` | Read `journalctl --user -u <unit>` first; after fixing the cause, `systemctl --user reset-failed <unit>` and `asb-agent resume --workspace <id>` |
| Workspace missing after `down` | `doctor`: `missing_container` | `asb-agent up --workspace <id> --repo <path>` (new ID and port) |

Deleting credentials, resetting Podman globally or running
`podman unshare --rootless-netns` are not recovery steps.

---

## 4. Direct SSH access without Orca

`connect --workspace <id>` opens an interactive shell on a workspace that is
already running, without going through Orca. It resolves the live
connection with the same read-only lookup `resolve_connection` already does
for `discover`/`ensure` (container, published port, SSH key) and then
replaces the host process with `ssh` (`os.execvp`), so there is no wrapper
process left behind. The remote side runs `sh -lc 'cd -- <project_root> &&
exec ${SHELL:-/bin/bash} -l'`, landing the operator in a login shell inside
the checkout.

`connect` never starts, resumes, rebuilds or otherwise mutates a workspace.
Any failure `resolve_connection` already raises for every other caller
(container never created, origin lost, port unreadable, SSH key missing)
surfaces unchanged as a `PodmanError`, exit code 2, same as the rest of
this CLI. A workspace that was never created names `up` in that message; a
missing SSH key names `resume`; a suspended (stopped) workspace publishes
no port (`podman port` exits 0 with no output), and the message says the
workspace may be suspended and names `asb-agent resume --workspace <ws>`.

`connect` does not verify or record the host key, matching the policy
`readiness.py` and `auth.py` already use for this same loopback SSH: host
keys are baked into the image once per build and shared by every
workspace, and the published port is ephemeral and reused, so pinning a
host key per `[127.0.0.1]:<port>` would hard-fail after a rebuild or a
reused port. `connect` writes nothing to `~/.ssh/known_hosts`.

---

## 5. Persistent agent sessions

An agent session is a provider process (`codex`, `claude`, `antigravity`)
running in a tmux session inside a workspace, so it survives the operator
closing the terminal. Control state lives in
`~/.local/state/agent-sandbox/`: `projects.json` (projects and checkouts)
and `sessions.json` (sessions). Both hold relationships only — never a
prompt, model output or transcript.

### Registering a checkout

```bash
asb-agent project add --repo <path> [--integration-branch <b>] [--worktree-root <dir>]
```

Registers the project and its primary checkout (the repository's primary
working copy) and prints one schema-1 JSON line with `projectId`,
`checkoutId`, `sourcePath` and `workspace`. The `checkoutId` is what the
session commands take. Registering the same path again returns the same
identity. Without `--integration-branch` the branch is discovered from
`refs/remotes/origin/HEAD`, or the command fails. `--worktree-root`
defaults to `<repo-name>-worktrees` next to the repository; worktree
creation (§6) uses it. `project add` never creates a workspace.

The workspace name is derived from the checkout path alone
(`workspace_id(path, {})`), so a checkout always maps to the same
workspace. A workspace created by Orca for the same repository carries a
different name and is never adopted.

### Session commands

| Command | Effect | Touches a workspace |
| :--- | :--- | :--- |
| `session list [--checkout <id>] [--json]` | Reads `sessions.json` and prints one line per session (id, checkout id, agent, state, title), or `{"schemaVersion": 1, "sessions": [...]}` with the stored fields only | never — works offline; states are as last recorded |
| `session start --checkout <id> --agent <codex\|claude\|antigravity> [--title <t>]` | Brings the checkout's workspace up if needed (`asb-agent up`, the same boundary Orca calls), then starts the agent in the sandbox checkout; prints `<session-id> <state>` | the only command that can start a workspace |
| `session attach <session-id>` | Replaces the CLI process with `ssh` running `tmux attach-session -t <target>` (the session's tmux id `$N`, found by its tag, or `=asb-<session-id>` when it cannot be located); detach with `C-b d` and control returns to the calling shell. A session in `exited_resumable` is natively resumed first | live connection only |
| `session stop <session-id>` | Ends the session (`completed`, never relaunched); prints `<session-id> <state>` | live connection only |
| `session resume <session-id>` | Native resume of a dead but resumable session; prints `<session-id> <state>` | live connection only |

`attach`, `stop` and `resume` resolve the live connection read-only, like
`connect` (§4): a stopped workspace surfaces the same `PodmanError`, exit
code 2, and the fix is `asb-agent resume --workspace <ws>`. `attach`
refuses a session in `recovery_required`, `completed` or `failed` with a
one-line message and exit code 2, without launching anything. `start`
exits 2 when the terminal did not confirm a running session, and `resume`
exits 2 when the session is not live afterwards. Registry, session-store
and driver errors print one line on stderr and exit 2.

### Session states and recovery

tmux is the source of truth; a stored terminal id is never evidence that
a process is alive. `start` tags the tmux session with the user option
`@asb_session asb-<session-id>`, so a session renamed by the operator
(`C-b $`) or by the agent itself is still found: probe, stop and attach
list every pane whose session carries that tag or that exact name, and
target the session by its tmux id. No such session is DEAD only when tmux
positively says so (the server lists nothing matching, or no server
runs); two matching sessions are uncertainty. A session that is both
renamed and untagged is not found. A probe lists every pane of the
session:

| tmux evidence | Recorded state | What happens |
| :--- | :--- | :--- |
| session exists, pane alive | `detached` (`running` right after its own launch) | attach rejoins the same process |
| pane dead with exit status 0 | `completed` | never relaunched |
| pane dead otherwise, provider id known and resume confirmed by the sandbox binary | `exited_resumable` | native resume on `attach` or `resume` |
| pane dead otherwise, no resumable conversation | `recovery_required` | nothing is launched |
| anything else (more than one pane, two matching sessions, deleted socket, SSH failure) | `recovery_required` | nothing is launched or attached |

A refresh (TUI or `reconcile`) never launches a process, skips
`suspended` and `starting` records, and writes only real transitions.
The provider session id is discovered once after launch (five polls, one
second apart) from the workspace's session volume; zero or several
candidates store no id, so such a session cannot be resumed natively.

---

## 6. The TUI

`asb-agent tui` needs an interactive terminal (exit 2 otherwise) and shows
one tree: projects, then each project's primary checkout and worktrees,
then each checkout's sessions (`agent  state  title`). Worktrees that Git
lists but the registry does not know appear as `unregistered`; a
registered worktree whose path is gone is marked `missing`.

A checkout row shows its workspace status (`ready`, `absent`,
`unavailable: <reason>`) and a branch. When the workspace is `ready` the
branch is read from the sandbox checkout, where the agent works, so an
agent's `git switch` shows on the next refresh; otherwise it is the
operator checkout's branch, marked `(host)`. The tree is read only at
start, on `r` and after an action, never in the background.

| Key | Action |
| :--- | :--- |
| `j`/`k`, arrows | move |
| Enter | fold a project or checkout; on a session, attach (see below) |
| `n` | start a session on the selected checkout (choose the agent); an unregistered worktree is registered first |
| `d` | session menu: `s` stops the selected session after an explicit `y` |
| `w` | create a worktree (below) |
| `f` | finish or clean up a worktree (§7) |
| `r` | refresh |
| `q` | quit; never stops, suspends or kills a session or workspace |

Attach runs the same `ssh … tmux attach-session` as `session attach`, as a
child process: curses is suspended, `C-b d` detaches, and the tree
returns. A session in `recovery_required`, `completed` or `failed` is not
attached. Titles, branches and paths are shown with control characters
replaced by `?`.

### Creating a worktree (`w`)

`w` asks for a new branch name, then the base (the project's integration
branch; the selected checkout's branch only as an explicit second
choice), then the path (default `<worktree-root>/<branch with / as ->`).
A preview shows the project, base and commit, branch and path; only `y`
creates. The path must be absolute, new, inside the worktree root and
outside `~/asb-agent/`; a missing root is created with mode `0700`.
Creation refuses if the base no longer resolves to the commit the preview
showed, runs `git worktree add -b <branch> <path> <base>`, and registers the checkout only after Git succeeds and the new worktree is
found on the new branch at that commit. A failure removes only what this
creation made (never with `--force`, and the branch only while it still
points at the base) and reports anything left. No workspace is created
until the first session starts.

---

## 7. Finishing a worktree

`f` in the TUI (`asb-agent tui`) on a worktree row integrates its work and,
only with positive evidence, cleans it up. The primary checkout is never
finished. Nothing is removed without proof that its work is integrated;
absence of an error is not evidence.

### Confirmation

`f` asks for the target branch (default: the project's integration
branch), then shows the worktree's path, branch and commit, the sandbox
branch and commit that the merge takes (read on the host without
mutation), the target branch and the clean checkout where the merge
runs, and two explicit toggles that both default to **no**: `c` cleanup
after merge and `b` delete the local branch (`git branch -d`, after
cleanup only). Only `y` proceeds, and the finish is bound to the sandbox
branch and commit it showed: if the sandbox moved since, the export is
refused and nothing is merged. There is no remote action: remote
branches are never touched and no remote Git command runs.

A worktree row shows `merged / cleanup available` only when a fresh
check at that refresh proves the worktree HEAD and every exported
sandbox ref (`refs/asb/<workspace>/...`, at least one) are ancestors of
the integration branch, for example after a manual `asb-agent pull` and
`git merge`. `f` on such a row offers the cleanup directly.

A `missing` worktree row (Git already removed it, for example when a
cleanup was interrupted before the registry update) shows
`merged / cleanup pending` when its export refs prove integration. `f`
on any `missing` worktree row offers the cleanup; the cleanup proves
integration again and is `blocked` without that proof.

### Evidence before mutation (fixed order)

1. The source worktree is present, listed by Git, clean and on a branch.
2. Every session of the checkout is `completed`/`failed` or its tmux
   probes DEAD. ALIVE or UNKNOWN (including a session with no terminal)
   blocks; finish never stops a session. A sandbox that is positively
   absent has no process to probe.
3. The target branch is valid, exists locally and is already checked
   out in a clean checkout other than the source. No checkout's branch
   is ever switched.
4. Export: the sandbox branch (a detached sandbox HEAD blocks) is
   validated with `git check-ref-format --branch`, must still be the
   branch and commit the confirmation showed, and is fetched by full ref
   into `refs/asb/<workspace>/<branch>` in the operator repository:

   ```text
   git fetch --no-tags --no-write-fetch-head -- <sandbox> \
       +refs/heads/<branch>:refs/asb/<workspace>/<branch>
   ```

   The fetched ref must equal the commit resolved before the fetch.
   `asb-agent pull` is not used.
5. `git merge --no-edit <ref>` in the target checkout. A conflict keeps
   Git's conflict state and reports the paths and the recovery
   (`git -C <target> merge --abort`, or resolve and commit). A merge
   interrupted by its timeout is `blocked` with the same recovery:
   inspect `git -C <target> status` and abort a merge in progress.
6. Both the exported sandbox commit and the worktree's own HEAD must be
   ancestors of the new target HEAD; otherwise the result is
   `cleanup_pending` ("integration is not proven").

Git commands that mutate (`fetch`, `merge`, `worktree remove`,
`branch -d`) run with a 600 s timeout; reads keep the 10 s one, and so
do `worktree add` and its rollback `branch -D` in worktree creation (§6).

### Cleanup and retry

With cleanup enabled, in order: probe the sessions again, purge the
bound sandbox, remove the worktree (`git worktree remove`, never
`--force`), optionally delete the local branch (`git branch -d`, a
refusal is reported), and remove the registry binding. The purge runs
`asb-agent purge --workspace <ws> --yes` and is accepted only when the
sandbox is then absent.

Before the purge the sandbox must prove that nothing in it would be
lost. The guard proves:

- the sandbox checkout is clean, untracked files included (`git status`
  runs inside the sandbox, so an agent-set `core.fsmonitor` or filter
  never runs on the host);
- its HEAD still equals the exported commit;
- every branch tip and every stash entry (the whole `refs/stash`
  reflog) exists in the operator repository and is integrated into the
  target;
- the sandbox clone has no extra worktree.

A purge still destroys, without checking: tags, other ref namespaces
(such as `refs/notes`), commits reachable only from reflogs, and
gitignored files.

| Result | Meaning |
| :--- | :--- |
| `merged` | Merge proven; nothing removed; cleanup available |
| `conflict` | Conflict state left in the target; nothing removed |
| `blocked` | Refused before any removal; the message says why |
| `cleanup_pending` | A step failed or was not proven; the message lists what was done and what remains |
| `cleaned` | Sandbox, worktree, optional branch and binding are gone; the source commit is reachable from the target |

A retry re-inspects what remains and resumes at the first missing step:
an absent sandbox skips the purge, and a worktree Git already removed is
reconciled only after its export refs prove integration. A missing
worktree without that evidence is `blocked` and needs manual recovery.
An interrupted `worktree remove` is `cleanup_pending` and names the
path to inspect.
