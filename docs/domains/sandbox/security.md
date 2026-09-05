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

## 4. Credential Isolation & The Antigravity Keyring

Agent model credentials are authenticated once per machine (`asb-agent login`) and stored in a dedicated named volume (`asb-credentials`):

| Agent | Storage Format | Protection Mechanism |
| :--- | :--- | :--- |
| Claude Code | `claude.json` | Linked into `$HOME/.claude/.credentials.json` |
| OpenAI Codex | `codex-auth.json` | Linked into `$HOME/.codex/auth.json` |
| Google Antigravity | `keyrings/` | Secret Service D-Bus encrypted keyring |

### Keyring Passphrase Protection
Antigravity stores its OAuth tokens in the GNOME Keyring. The keyring is encrypted using a 32-byte cryptographically secure random passphrase generated at `~/.config/agent-sandbox/keyring.pass` (file mode `0600`).
- The passphrase is **never baked into any container image**.
- A copy of the container image or volume stolen or moved to another machine cannot decrypt the keyring without the host's `keyring.pass`.
