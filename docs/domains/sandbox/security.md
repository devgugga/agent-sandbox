# Security Boundaries & Isolation Model

This document outlines the security architecture of `agent-sandbox` (v2), its non-negotiable invariants, and an explicit declaration of what the sandbox does not protect against.

Read this before enabling optional capabilities in `.agent-sandbox.toml`.

---

## 1. Non-Negotiable Invariants

The sandbox is designed around strict containment boundaries enforced by rootless Podman and network topology:

1. **Host `$HOME` is never mounted in any container.** The agent receives an identical mount path (`~/asb-agent/<proj>/<ws>/`), but its view is strictly confined to the workspace worktree.
2. **No host credentials enter the sandbox.** No host SSH keys (`~/.ssh`), Git credentials, Personal Access Tokens (PATs), or GitHub CLI tokens are copied or mounted into the sandbox.
3. **The host Docker socket (`/var/run/docker.sock`) is NEVER mounted directly.** Unfiltered Docker socket access is equivalent to root on the host. When Docker access is enabled, it is exclusively routed through a read-only HTTP broker (`host_api = "read"`).
4. **The agent container has NO direct network egress, NO `CAP_NET_ADMIN`, and NO `sudo`.** Network egress is blocked at the network topology level (`--internal` network without a default route).
5. **The primary checkout (`~/Data/Projects/<proj>`) is never mounted.** The sandbox operates on a hardlink clone with isolated worktrees under `~/asb-agent/<proj>/<ws>/`.
6. **The Secret Service daemon runs as a strictly isolated singleton (`asb-keyring`).** It has `--network none` (zero network interfaces or egress), no workspace mounts, and mounts the host passphrase strictly as read-only (`ro,Z`). Client containers never receive the passphrase.

---

## 2. Explicit Declarations: What Is NOT Protected

Security boundaries must be declared plainly. The following behaviors are possible and intentional consequences of requested configurations:

### Exfiltration to an allowed domain is possible
If a domain is present on the allowlist (e.g. `github.com` or `gist.github.com`), the agent can send arbitrary payloads to that domain. A secret GitHub Gist, an issue comment, or a git push to an external repository is a viable egress channel. **No network-level egress filter can prevent data exfiltration to a permitted destination.**

### `host_api = "read"` grants passwordless Docker reading to uid 1000
When `host_api = "read"` is configured in `.agent-sandbox.toml`, the agent can query `GET /containers/json`, `GET /containers/{id}/json`, and `GET /containers/{id}/logs`. While destructive operations (`POST`, `DELETE`, `PUT`) return `403 Forbidden`, the agent can:
- List all containers running on the host Docker daemon.
- Read environment variables of host containers (which may include database passwords, API tokens, or session secrets).
- Inspect container volume mount points and read container logs.

### `mode = "nested"` gives the agent a full container runtime inside the boundary
Enabling `mode = "nested"` provides the agent with an isolated, rootless Podman runtime inside the container. The agent cannot break out to the host filesystem, but it has the ability to:
- Pull large images and consume host disk space in the `asb-<ws>-containers` volume.
- Spawn numerous nested processes consuming host CPU and memory.

### The command guard is NOT containment
The host wrappers (`asb-claude`, `asb-codex`, `asb-agy`) intercept invocations and exit 77 when an agent tries to run outside the sandbox. This mechanism prevents **accidental** execution when Orca launches agents with autonomous flags. **It is not a security boundary**: anyone or any process that knows the real binary path can execute it directly. The container boundary is the sole containment mechanism.

---

## 3. Network & DNS Boundary

### Topology Enforcement (Fail-Closed)
In v2, network isolation is enforced by the network topology itself, not by runtime firewall rulesets:
- The internal network `asb-<ws>` is created with `--internal`. The kernel assigns no default gateway route and no external DNS servers to this network.
- The agent container attaches **only** to the internal network. Even if the proxy container crashes or fails to start, the agent container has zero network path to the internet.

### DNS Tunneling Prevention
The agent container has **no external DNS resolution**. Name resolution occurs exclusively upstream inside the Squid proxy container. This design:
- Completely eliminates DNS tunneling as a data exfiltration vector.
- Eliminates DNS resolution timeouts and IPv4/IPv6 dual-stack race conditions.

---

## 4. Credential Isolation & The Singleton Secret Service

Agent model credentials are authenticated once per machine (`asb-agent login`) and shared by every workspace. Full storage and login contract: [authentication.md](./authentication.md).

| Agent | Storage | Encrypted at rest | Exposure |
| :--- | :--- | :--- | :--- |
| Claude Code | `~/.claude/.credentials.json`, a regular file in the `claude/` directory of `asb-credentials` | no | plaintext, readable by agent processes in **every** workspace |
| OpenAI Codex | `~/.codex/auth.json`, a regular file in the `codex/` directory of `asb-credentials` | no | plaintext, readable by agent processes in every workspace |
| Google Antigravity | GNOME Keyring entries in `asb-keyring-data`, owned by `asb-keyring` | yes (host `keyring.pass`) | files unreachable from clients; secrets usable by any client through the Secret Service bus |

An agent that can run code in one workspace can therefore read the Claude and Codex credentials used by all workspaces. Session transcripts are isolated per workspace (`asb-<ws>-session`); credentials are not.

### Secret Service Daemon Isolation (`asb-keyring`)
To eliminate multi-daemon concurrency race conditions and session drops, exactly one container (`asb-keyring`, labeled `asb.keyring.schema=2`) runs GNOME Keyring and D-Bus session bus:
- **Zero Network (`--network none`)**: `asb-keyring` has no network interfaces beyond loopback. It has no external egress, no internal workspace bridge attachment, and cannot establish outbound connections.
- **No Workspace Mounts**: `asb-keyring` has no access to workspace files, host directories, Docker sockets, or SSH keys.
- **Single Owner of Keyring Files & Data Volume Separation**: Encrypted keyring files are separated into a dedicated volume `asb-keyring-data` mounted exclusively in `asb-keyring`. Workspace and login containers mount `asb-credentials` (the per-provider credential directories) and the read-only D-Bus socket volume `asb-keyring-runtime`. Clients never mount `asb-keyring-data`.
- **Legacy Keyring Shadow Mask**: Because existing keyring files remain preserved in `asb-credentials/keyrings` during non-destructive migration, client containers mount a secure read-only tmpfs shadow mask (`--mount type=tmpfs,destination=/run/asb-credentials/keyrings,ro,notmpcopyup,tmpfs-mode=000`). This completely prevents workspace or login client processes from reading, listing, or modifying legacy keyring files, while the per-provider credential directories stay writable.
- **Passphrase Protection**: The 32-byte cryptographically secure random passphrase (`~/.config/agent-sandbox/keyring.pass`, file mode `0600`) is mounted strictly read-only into `/run/asb-keyring-pass:ro,Z`.
  - The passphrase is **never baked into any container image**.
  - The passphrase is **never passed as an environment variable** (never visible in `podman inspect`).
  - Workspace client containers do not mount the passphrase and do not receive `ASB_KEYRING_PASS`.
  - A copy of the container image or volume stolen or moved to another machine cannot decrypt the keyring without the host's `keyring.pass`.
- **D-Bus Session Bus Over Private Unix Socket**: `asb-keyring` publishes its D-Bus session socket inside named Podman volume `asb-keyring-runtime` at `/run/asb-keyring/bus`. Workspace clients mount this volume as read-only (`:ro,z`) and communicate via `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus`. The socket is strictly local to container namespaces and is never exposed over TCP or host network ports.
- **Resumable Migration & Schema Auto-Upgrade**: Legacy data in `asb-credentials/keyrings` is copied to `asb-keyring-data/keyrings` through staging and verified with `/run/asb-keyring-data/.migration_done`. If interrupted, migration safely resumes on the next startup without data loss. Existing schema 1 singleton containers or containers with legacy mounts are automatically recreated on `ensure_keyring_service()` without removing volumes or passfiles.
