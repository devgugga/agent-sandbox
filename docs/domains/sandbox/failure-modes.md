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

## 18. Silent Rootless Podman Network Uplink Failure (`pasta` Failure)

- **Symptom**: Outbound network connections from within the sandbox freeze or fail across all containers while local bridges remain intact. Following a host reboot, containers restored by `podman-restart.service` remain marked as `running` while the shared rootless user network namespace lacks a functional `pasta` process (`container running + uplink rootless morto`). In this state, Squid accepts local connections from the agent on port 3128, but replies with `NONE_NONE/500` or `NONE_NONE/503` because it cannot reach external destinations. AI agents (Claude Code, OpenAI Codex, Google Antigravity) then exhibit timeout or connection abort symptoms that mimic authentication failures or upstream provider outages. In `podman pull`, small image layers complete while large blobs stall indefinitely (e.g. at 16 KiB) and restart in a loop. Direct socket probes inside the proxy container show routing tables intact (`default via 10.89.x.1 dev eth1`), but all outbound TCP/DNS requests fail with `Network is unreachable (os error 101)`.
- **Cause**: The rootless Podman user-namespace network uplink helper (`pasta`) silently stops forwarding external traffic or its user session scope terminates upon host reboot or suspend. Because container-side interfaces and bridges remain up, Podman does not detect the broken uplink on its own and restores or leaves containers running without an active uplink.
- **Fix**: The architecture provides automated recovery across the operational lifecycle and maintains explicit diagnostics:
  1. **Automated Workspace Lifecycle (`up` & `resume`)**: Both `asb-agent up` and `asb-agent resume` explicitly invoke `podman.ensure_rootless_netns()` (`podman unshare --rootless-netns $(command -v true)`) before creating or starting the Squid proxy container, ensuring the user network namespace uplink is functional before any container dependent on external egress begins communicating.
  2. **Automated User Login / Reboot Recovery (`systemd` drop-in)**: `install.podman_restart()` installs a systemd user drop-in at:
     ```text
     ~/.config/systemd/user/podman-restart.service.d/agent-sandbox.conf
     ```
     containing:
     ```ini
     [Service]
     ExecStartPre=/usr/bin/podman unshare --rootless-netns /usr/bin/true
     ```
     followed by `systemctl --user daemon-reload` and enabling `podman-restart.service`. This drop-in forces systemd to initialize the rootless netns before Podman attempts to restart containers on user session login (or system boot if linger is enabled). The configuration adheres to §16 by referencing absolute host binary paths rather than repository checkout paths.
  3. **Diagnostic & Manual Recovery (`asb-agent doctor`)**: `asb-agent doctor` probes active workspaces with live DNS and TCP checks to distinguish a blocked allowlist from a dead rootless uplink (`ws: uplink rootless morto`). For unmanaged sessions or manual intervention, reconnecting the rootless network namespace uplink on the host with:
     ```bash
     podman unshare --rootless-netns true
     ```
     instantly restarts the `pasta` network namespace uplink in place without requiring container restarts or recreation. Active workspaces can be validated at any time using `asb-agent doctor`.

---

## 19. Workspace Not Restored Immediately after Host Reboot (`Linger=no`)

- **Symptom**: *"O workspace sumiu depois do reboot"* / Containers are not running immediately after host system boot when inspecting via headless connection or SSH before user login.
- **Cause**: By default on systemd Linux installations, user account linger is disabled (`Linger=no`, checked via `loginctl show-user $USER --property=Linger`). Without linger, the user's `systemd --user` session manager — along with its enabled user services such as `podman-restart.service` — initializes **upon interactive login**, not at system kernel boot.
  - **Desktop with graphical login** (standard interactive developer setup): The operator logs in via the display manager (GDM, SDDM, etc.), which immediately initializes the user's systemd manager and `default.target`, executing `podman-restart.service` and restoring all `unless-stopped` workspace containers before Orca or browser sessions connect.
  - **Headless server / SSH-only remote workflow**: Containers remain inactive following a reboot until an interactive session is opened by the user.
- **Fix**:
  - For standard desktop workstations: No action required. Logging into the desktop graphical session automatically restores all running workspaces.
  - For headless/remote servers where workspaces must boot unattended before any user logs in: explicitly enable user session linger on the host:
    ```bash
    loginctl enable-linger $USER
    ```
  > [!IMPORTANT]
  > **Do not enable linger by default.** Keeping user workspaces alive unattended on an unlogged system alters security posture by maintaining active services and published network ports without an operator present. Enabling linger must be an explicit, conscious operator decision.
  - After login, verify restored workspace state with:
    ```bash
    asb-agent doctor
    ```
    or manually restart stopped workspaces with `asb-agent resume --workspace <id>`.

---

## 20. Multi-Daemon Keyring Concurrency & Session Loss (False Green Login)

- **Symptom**: `asb-agent login` passes successfully in its temporary container, but subsequent commands in workspace containers (`asb-claude`, `asb-agy`, or interactive sessions) prompt for authentication again or report missing credentials ("perdi a sessão"). Re-running login temporarily succeeds only to fail again in workspaces.
- **Cause**: Prior to the singleton architecture, each container (the ephemeral login container and every workspace container) launched its own isolated `dbus-daemon` and `gnome-keyring-daemon` against the shared `keyrings/` storage on the `asb-credentials` volume. When `asb-agent login` wrote credentials, it verified them against its own in-container daemon before terminating. A newly launched workspace container started a separate daemon instance, which does not safely detect or reload encrypted records written by another daemon instance over shared files. Furthermore, concurrent workspaces running multiple daemons simultaneously risked race conditions and database corruption. (Codex was unaffected because it stores its token directly in `codex-auth.json`).
- **Fix**: Centralized Secret Service ownership into a global singleton container (`asb-keyring`):
  1. **Singleton Daemon**: Exactly one `asb-keyring` container runs with `--network none`, `--restart unless-stopped`, and uid 1000. It has no workspace mounts and is the sole owner and writer of the `keyrings/` database. Passphrase is mounted strictly read-only (`ro,Z`) and never exposed in environment variables.
  2. **Shared D-Bus Session Socket**: `asb-keyring` publishes `/run/asb-keyring/bus` into the `asb-keyring-runtime` volume. All client containers (ephemeral login and workspace agents) mount `asb-keyring-runtime` as read-only (`:ro,z`) and connect using `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus`. Neither clients nor login containers run local D-Bus or GNOME Keyring daemons.
  3. **Migrating Old Workspaces**: Containers created prior to the singleton architecture do not mount `asb-keyring-runtime` and lack the session bus address. Because volume mounts cannot be dynamically attached to existing containers, old workspaces must be recreated:
     ```bash
     # Crucial: pull local workspace changes first to protect unmerged work!
     asb-agent pull --workspace <ws>
     asb-agent down --workspace <ws>
     asb-agent up --workspace <ws> --repo <repo>
     ```
  4. **Diagnostics and Recovery**:
     - Verify keyring service health using `asb-agent doctor`. It checks container status, socket readiness, and verifies `org.freedesktop.secrets` responsiveness on the session bus.
     - To recover a stopped or unhealthy keyring service, run `asb-agent login`. If schema corruption or incompatible versions occur, remove the container with `podman rm -f asb-keyring` and run `asb-agent login`.
