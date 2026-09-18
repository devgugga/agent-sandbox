# Workspace Lifecycle & Supervision

How a workspace starts, stops, survives a reboot and recovers. The model is
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
missing SSH key names `resume`; a suspended (stopped) workspace surfaces
the raw `podman port` failure — the fix is still `asb-agent resume`.

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
creation (Task 11 of the TUI plan) uses it. `project add` never creates a
workspace.

The workspace name is derived from the checkout path alone
(`workspace_id(path, {})`), so a checkout always maps to the same
workspace. A workspace created by Orca for the same repository carries a
different name and is never adopted.

### Session commands

| Command | Effect | Touches a workspace |
| :--- | :--- | :--- |
| `session list [--checkout <id>] [--json]` | Reads `sessions.json` and prints one line per session (id, checkout id, agent, state, title), or `{"schemaVersion": 1, "sessions": [...]}` with the stored fields only | never — works offline; states are as last recorded |
| `session start --checkout <id> --agent <codex\|claude\|antigravity> [--title <t>]` | Brings the checkout's workspace up if needed (`asb-agent up`, the same boundary Orca calls), then starts the agent in the sandbox checkout; prints `<session-id> <state>` | the only command that can start a workspace |
| `session attach <session-id>` | Replaces the CLI process with `ssh` running `tmux attach-session -t =asb-<session-id>`; detach with `C-b d` and control returns to the calling shell. A session in `exited_resumable` is natively resumed first | live connection only |
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
