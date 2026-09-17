# Failure Modes & Forensic Record

This document consolidates operational lessons and failure modes discovered during the development and production hardening of `agent-sandbox`.

Each entry records a real failure mode formatted as **Symptom**, **Cause**, and **Fix**.

---

## 1. `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` Set in Container Image

- **Symptom**: Startup warning `Permission mode forced to default — CLAUDE_CODE_SUBPROCESS_ENV_SCRUB is set`. Claude Code silently disables `--dangerously-skip-permissions`, requiring manual approval on every command.
- **Cause**: In the original specification, this variable protected host subprocesses. Inside the container it provides no additional protection, but Claude detects it and disables autonomous execution.
- **Fix**: Never export `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` in container environment variables or image definitions.

---

## 2. Comments inside Line-Continued Commands

- **Symptom**: Podman fails at runtime with `Error: requires at least 1 arg(s), only received 0`. `bash -n` syntax checking reports no errors and automated tests remain green until runtime.
- **Cause**: In Bash, placing a `#` comment on a line with a trailing backslash (`\`) terminates the logical command immediately. All subsequent continuation lines become orphaned commands.
- **Fix**: Never place inline comments between line continuations in shell scripts.

---

## 3. Non-Deterministic Workspace Naming

- **Symptom**: Containers or networks leak indefinitely after workspace teardown. Orca's `destroy` hook reports success while background resources remain active.
- **Cause**: Workspace names derived from shell PID (`$$`) or unnormalized paths cannot be reproduced by the teardown command.
- **Fix**: Derive workspace names deterministically from `ORCA_VM_INSTANCE_ID` (sanitized with `tr -c 'a-zA-Z0-9._-' '-'`) or normalized repository path hash (`<basename>-<sha256[0:8]>`).

---

## 4. Grep-Based Authentication Verification

- **Symptom**: Unauthenticated container images or credential states are marked as valid.
- **Cause**: Grepping output for strings such as `logged in` matches both positive and negative responses (e.g. `not logged in`).
- **Fix**: Verify authentication strictly by exit codes (`returncode == 0`), such as `codex login status`, Claude execution test, or `asb-agy --version`.

---

## 5. Unpaired Negative Security Assertions (False Greens)

- **Symptom**: Security test assertions pass ("egress blocked") even when the container failed to launch or crashed immediately.
- **Cause**: Negative assertions check that a network request failed. If the environment never started, the command fails and the test falsely concludes the firewall blocked it.
- **Fix**: Always pair negative assertions with positive controls verifying the environment is responsive (`require` in `tests/assert.sh`). Validate structured response contents rather than checking for presence of output.

---

## 6. Squid Subdomain ACL Redundancy (`dstdomain`)

- **Symptom**: Squid proxy container fails to start: `ERROR: '.github.com' is a subdomain of 'github.com'` and `FATAL: Bungled /etc/squid/squid.conf`.
- **Cause**: In Squid configuration, `.domain.com` matches both apex and subdomains. Including both `domain.com` and `.domain.com` in the same `dstdomain` ACL triggers a fatal configuration error.
- **Fix**: Normalize and prune domains in `cli/asb/squid.py`: remove redundant child entries when a parent wildcard is declared, and deduplicate list entries.

---

## 7. Antigravity Missing `.googleusercontent.com`

- **Symptom**: Antigravity CLI (`agy`) aborts at startup with `Forbidden` despite valid authentication credentials.
- **Cause**: The Antigravity account eligibility check attempts to fetch the user's profile avatar from Google content domains (`*.googleusercontent.com`). If blocked by the proxy, the CLI refuses to initialize.
- **Fix**: Include `.googleusercontent.com` in `image/squid/allowlist-base.txt`.

---

## 8. Antigravity Demands Login on SSH Sessions

- **Symptom**: `agy` prompts for interactive device-auth on every workspace connection over SSH, ignoring valid cached credentials.
- **Cause**: Antigravity checks for `SSH_CONNECTION`, `SSH_CLIENT`, and `SSH_TTY`. When detected, it assumes a new remote terminal and skips local keyring access.
- **Fix**: The `asb-agy` guard wrapper unsets `SSH_CONNECTION`, `SSH_CLIENT`, and `SSH_TTY` immediately before invoking the real `agy` binary.

---

## 9. OpenSSH Environment Variable Scrubbing

- **Symptom**: Environment variables passed to the container (e.g. `HTTPS_PROXY`, `NO_PROXY`) are empty inside SSH sessions (`ssh agent@127.0.0.1 'echo $HTTPS_PROXY'`).
- **Cause**: The OpenSSH daemon scrubs environment variables when initializing user sessions for authenticated users.
- **Fix**: In `image/entrypoint.sh`, write essential proxy and path variables to both `/etc/environment` (loaded by PAM) and `/etc/profile.d/agent-sandbox.sh` (sourced by login shells).

---

## 10. Orca Recipe Selector Invisibility

- **Symptom**: The agent sandbox recipe does not appear in the "Run on" selector in Orca.
- **Cause**: Either **Settings → Experimental → "Cloud VM"** is toggled off in Orca, or `orca.yaml` is not committed on the project's primary git branch.
- **Fix**: Enable the "Cloud VM" experimental setting in Orca, and ensure `orca.yaml` is tracked and committed on the primary branch.

---

## 11. Squid Configuration File Permissions

- **Symptom**: Squid proxy exits immediately with `FATAL: Unable to open configuration file: /etc/squid/squid.conf: (13) Permission denied`.
- **Cause**: Host files created with restrictive permissions (such as `0600`) cannot be read by the Squid daemon running as unprivileged uid 900.
- **Fix**: Explicitly set permissions to `0644` on `squid.conf` before mounting into the proxy container.

---

## 12. Missing `--userns=keep-id` on Agent Container

- **Symptom**: The agent container cannot write to its workspace mount with `Permission denied` or `fatal: could not create leading directories`.
- **Cause**: In rootless Podman without `--userns=keep-id`, host uid 1000 maps to root (uid 0) inside the user namespace. Files owned by the host user appear owned by root, preventing the container user (uid 1000) from writing.
- **Fix**: Pass `--userns keep-id:uid=1000,gid=1000` when starting the agent container.

---

## 13. Sibling Worktree Path Collision at Filesystem Root

- **Symptom**: Git worktree creation fails with `fatal: could not create leading directories: /workspace-Teste`.
- **Cause**: Mounting the project repository at `/workspace` causes Orca's sibling worktree generator to construct paths like `/workspace-<name>` in the filesystem root, which is read-only (`0555`).
- **Fix**: Mount the workspace inside the user's home directory: `$HOME/asb-agent/<proj>/<ws>/`.

---

## 14. Claude Code Hanging on Non-Interactive Stdin

- **Symptom**: Non-interactive command invocations (`claude -p "..."`) hang indefinitely during automated scripts.
- **Cause**: Claude Code detects an open stdin pipe and pauses waiting for interactive user terminal input.
- **Fix**: Redirect standard input from `/dev/null` (`< /dev/null`) for non-interactive Claude prompts.

---

## 15. Node Header Fetch Failure during Native Module Build

- **Symptom**: Orca workspace startup aborts with `Request was cancelled` during initial connection.
- **Cause**: Orca provisions its remote agent (`~/.orca-remote`) inside the container and compiles native modules (`node-pty`) with `node-gyp`. `node-gyp` requires Node headers downloaded from `nodejs.org`.
- **Fix**: Include `nodejs.org` in `image/squid/allowlist-base.txt`.

---

## 16. Service Containers Failing under `keep-id` without `--user 0`

- **Symptom**: Disposable service containers (e.g. `postgres`) fail during initialization with `Operation not permitted` during directory permission adjustments.
- **Cause**: Container images without a `USER` directive inherit user namespace mappings that prevent internal setup scripts from executing required `chown` operations.
- **Fix**: Launch service containers explicitly with `--user 0`.

---

## 17. Toolchain Installation Failure during Workspace Startup (`up`)

- **Symptom**: `asb-agent up` exits with a non-zero exit code (1), outputs `erro: falha na instalacao de ferramentas mise em: <dir>`, prints the underlying `mise` stderr diagnostics, and suppresses the Orca recipe JSON output. The workspace containers remain running.
- **Cause**: A runtime declared in `mise.toml` requires binary assets, source code, or cryptographic attestations from an external domain not present in the proxy allowlist (`allowlist-base.txt` or project `.agent-sandbox.toml`).
- **Fix**: Check the `stderr` output printed by `asb-agent up` to identify the blocked domain. Add the domain to `[network] allow = [...]` in the project's `.agent-sandbox.toml`. Because the workspace containers and networks are preserved on `mise install` failure, the operator can immediately re-run `asb-agent up` to retry without paying the cost of re-provisioning the workspace.

---

## 18. Silent Rootless Podman Network Uplink Failure (`pasta` Without Egress)

- **Symptom**: After a reboot, workspaces look healthy (`running`, SSH answers) but nothing leaves the sandbox. Squid accepts the agent's connection on port 3128 and answers `NONE_NONE/500` or `503`; agents show timeouts that mimic login or provider outages; `podman pull` stalls on large blobs. Inside the proxy the routing table is intact, yet outbound TCP/DNS fails with `Network is unreachable (os error 101)`. `asb-agent doctor` reports `uplink rootless morto`.
- **Cause**: Podman's shared rootless network namespace was created **before** the host had working connectivity, and it keeps no egress while anything holds it open. In the pilot (`docs/validation/startup-auth-pilot.md` §6.2, §6.6) the producer was the project's own `podman-restart` drop-in, whose `ExecStartPre` ran `podman unshare --rootless-netns` at login on every boot; running that command again did not repair the namespace. This mechanism is a hypothesis confirmed by prediction on real boots, not proven at the kernel level.
- **Fix** (Emenda A, [lifecycle.md](./lifecycle.md)):
  1. Only systemd starts ASB containers; all are `--restart=no`, and the drop-in is removed by `up` and flagged by `doctor`.
  2. Every workspace unit requires `asb-network.service`, which exits only after a real probe to `github.com:443`. The namespace is then born by the first proxy start, after connectivity: measured 105–318 ms after the wait on three real boots, including ~2 minutes without a cable.
  3. If the state still happens (for example a third-party producer listed by `doctor`), with the host network up run `asb-agent suspend` then `asb-agent resume` for **every** workspace so the namespace is recreated with egress. See [R10](./known-regressions.md).

---

## 19. Workspace Not Started Immediately after Host Reboot (`Linger=no`)

- **Symptom**: Right after boot, checked over SSH before anyone logs in, workspace containers are not running.
- **Cause**: With `Linger=no` (the systemd default), the user manager and its units (`asb-network.service`, `asb-keyring.service`, `asb-<ws>.target`) start at **login**, not at kernel boot.
  - **Desktop with graphical login**: the display manager login starts them; enabled workspaces come up once `asb-network.service` confirms connectivity.
  - **Headless / SSH-only machine**: nothing starts until a session opens.
- **Fix**:
  - Desktop: no action. After login, `asb-agent doctor` shows the state; suspended workspaces stay stopped until `asb-agent resume --workspace <id>`.
  - Headless machines that must start unattended: `loginctl enable-linger $USER`.
  > [!IMPORTANT]
  > **Do not enable linger by default.** It keeps services and published ports alive with no operator present; enable it only as an explicit decision.

---

## 20. Multi-Daemon Keyring Concurrency & Session Loss (False Green Login)

- **Symptom**: `asb-agent login` succeeds in its temporary container, but workspace containers ask for authentication again.
- **Cause**: Before the singleton, every container (login and each workspace) ran its own `dbus-daemon` and `gnome-keyring-daemon` against shared `keyrings/` files. A daemon does not reload encrypted records written by another instance, and concurrent daemons risked corrupting the database. The same investigation later found that Claude Code does **not** use the Secret Service at all: it stores a plain file (`~/.claude/.credentials.json`), and it lost its login because of a symlinked credential path ([R2](./known-regressions.md)). Only Antigravity depends on the keyring.
- **Fix**: one Secret Service owner, `asb-keyring`:
  1. Runs with `--network none`, uid 1000, label `asb.keyring.schema=2`, no workspace mounts, `--restart=no`, supervised by `asb-keyring.service` with a readiness check. Sole owner of `asb-keyring-data`; the passphrase is mounted read-only and never passed as an environment variable. Existing `asb-credentials/keyrings` data is migrated once through staging and a `.migration_done` marker, without mutating the source.
  2. Publishes `/run/asb-keyring/bus` in `asb-keyring-runtime`; clients mount it read-only and set `DBUS_SESSION_BUS_ADDRESS`. Clients never mount `asb-keyring-data`, and a mode-000 tmpfs masks the legacy `keyrings/` tree.
  3. Containers created before the singleton lack these mounts and cannot gain them on `resume`. `doctor` flags them and prints `asb-agent pull … && asb-agent down … && asb-agent up …` — pull first, to keep unmerged work.
  4. `doctor` checks container state, schema, mount contract, socket and `org.freedesktop.secrets`. A stopped keyring is restarted through its unit: `systemctl --user restart asb-keyring.service`. An outdated schema or mount contract is fixed by removing the container; the next workspace preparation recreates it without touching volumes or the passphrase.

---

## 21. Agent Fails Its First Start When Workspaces Start Together

- **Symptom**: After a reboot, one agent unit shows `NRestarts=1`; its journal has `rm: cannot remove '/home/<user>/.claude/plugins.asb-staging.1/…': Directory not empty` and the container exited with status 1. The retry 5 s later succeeds.
- **Cause**: the entrypoint materialized host configuration into the shared `~/.claude` volume through a temporary directory named with `$$`, which is 1 in every container. Workspaces now start together right after `asb-network.service`, so two agents raced on the same path. Each such failure also spends one of the three starts allowed by `StartLimitBurst`.
- **Fix**: the swap of each destination is serialized across containers with `flock` on its parent directory (`image/entrypoint.sh`); rebuild the image and recreate workspaces to pick it up. See [R12](./known-regressions.md).
