# Sandbox Domain Pack

Single Source of Truth (SSoT) for the `agent-sandbox` (v2) runtime environment across all AI agents (Claude Code, OpenAI Codex, Google Antigravity) and orchestrators (Orca).

## Documentation Index

- [Configuration Reference](./configuration.md): Complete `.agent-sandbox.toml` schema and worked examples (hexmed-stack and BlackICE).
- [Security Boundaries](./security.md): Explicit boundary declarations, invariants, and what the sandbox does not protect.
- [Failure Modes & Forensics](./failure-modes.md): Consolidated forensic record from production edge cases, symptoms, causes, and fixes.

---

## 1. System Topology

Every workspace runs in an isolated network topology managed via rootless Podman:

```text
rede asb-<ws>  (--internal: sem rota default, sem DNS externo)
│
├─ asb-<ws>-agent      uid 1000 · -p 127.0.0.1::22 · NENHUM egresso
├─ asb-<ws>-proxy      interna + EXTERNA         → internet (allowlist do Squid)
├─ asb-<ws>-docker     interna + socket do broker → SEM rede externa   [opt-in]
├─ asb-<ws>-fwd        interna + gateway do host  → SEM internet       [opt-in]
└─ asb-<ws>-svc-<nome> interna apenas (postgres, redis, …)
```

The agent reaches everything by **container name** across restarts. Outbound traffic is forced through the proxy via `HTTPS_PROXY=http://asb-<ws>-proxy:3128`.

### Container Roles

- **`asb-<ws>-agent`**: The execution environment. Mirrors the host user (identical username, uid 1000, identical `$HOME`). Reached by Orca via OpenSSH published to `127.0.0.1:<random-port>`. Has no default network route and no external DNS.
- **`asb-<ws>-proxy`**: Squid egress proxy. Connected to both `asb-<ws>` (internal) and `asb-<ws>-out` (external bridge with internet egress). Enforces TLS CONNECT filtering against the combined allowlist and resolves upstream DNS.
- **`asb-<ws>-docker`** *(opt-in)*: Docker API bridge created when `docker.host_api = "read"`. Forwards port 2375 to `/run/asb-docker/docker.sock` via `socat`. Bound strictly to the internal network with no external internet route.
- **`asb-<ws>-fwd`** *(opt-in)*: Host port forwarder created when `docker.host_ports` are declared. Bridges specific declared ports to the host gateway (`host.containers.internal`) without opening general network access.
- **`asb-<ws>-svc-<nome>`**: Disposable service containers (e.g. `postgres:17`, `redis:7-alpine`) declared under `[services]`. Reside strictly on the internal network and disappear on `down`.

---

## 2. CLI Commands

The CLI entrypoint is `cli/asb-agent` (symlinked as `asb`):

| Comando | O que faz |
| :--- | :--- |
| `build` | constroi a imagem base espelhando seu usuario |
| `login` | autentica os tres agentes; **uma vez por maquina** |
| `up` | cria rede, clone e containers; imprime a conexao |
| `resume` | religa (`podman start`); depois de reboot e automatico |
| `pull` | traz o branch do workspace para o checkout primario |
| `down` | remove containers e rede; **preserva seus arquivos** |
| `purge` | remove tambem os arquivos; exige `--yes` |
| `doctor` | diz o que falta e o comando exato para corrigir |

Additional utility commands:
- `asb-agent list`: lists active and stopped workspaces and their backing repositories.
- `asb-agent suspend --workspace <id>`: puts workspace containers to sleep (`podman stop`).
- `asb-agent install-guards`: installs host command wrappers (`asb-claude`, `asb-codex`, `asb-agy`) into `~/.local/bin`.
- `asb-agent install-broker`: configures and starts the filtered Docker read-only broker (requires `sudo`).

---

## 3. Where Files Live

### Filesystem Layout

The user inside the container mirrors the host user: identical username, uid 1000, identical `$HOME` (e.g., `/home/v`).

```text
host                                          container
~/asb-agent/<proj>/<ws>/                ←→   $HOME/asb-agent/<proj>/<ws>/
   ├─ <proj>/                                clone com hardlinks (projectRoot)
   └─ <proj>-<Nome>/                         worktrees irmas criadas pelo Orca
```

- **Primary checkout on host (`~/Data/Projects/<proj>`)**: **Never mounted**. The sandbox interacts only with its hardlink clone under `~/asb-agent/<proj>/<ws>/`.
- **Workspace mount (`~/asb-agent/<proj>/<ws>/`)**: Mount path is identical inside and outside the container.
- **Workspace state (`~/.local/state/agent-sandbox/<ws>/`)**: Kept outside the mounted directory so the agent cannot edit its own allowlist. Holds `squid.conf`, `origin`, and `staging/`.
- **Agent credentials (`asb-credentials` volume)**: Named Podman volume mounted at `/run/asb-credentials:Z`. Symlinks inside the container connect agent credential paths (`.claude/.credentials.json`, `.codex/auth.json`, `.local/share/keyrings`) into this volume.
- **Keyring passphrase (`~/.config/agent-sandbox/keyring.pass`)**: 32 random bytes, permissions 0600 on the host, injected into the container via `ASB_KEYRING_PASS`.
- **SSH client key (`~/.config/agent-sandbox/id_ed25519`)**: Generated on demand on the host and authorized inside the container.

---

## 4. What to Do on Failure

1. **Run `asb-agent doctor`**:
   Checks rootless Podman, Python version, base container image, credentials volume, and systemd `podman-restart.service`. If anything is missing, it outputs the exact command to fix it.

2. **Workspace fails during startup (`asb-agent up`)**:
   `up` is transactional. If a failure occurs during initialization, `_sweep_containers` automatically rolls back: all `asb-<ws>-*` containers and `asb-<ws>` networks are cleaned up. Your workspace files under `~/asb-agent/<proj>/<ws>/` are preserved. Check stderr for configuration errors (e.g. uninstalled broker or invalid image name).

3. **Agent cannot reach an external service or API**:
   - Outbound egress is default-deny. Inspect proxy logs:
     ```bash
     podman logs asb-<ws>-proxy
     ```
   - Look for `TCP_DENIED/403` lines. Add required domains under `[network].allow` in `.agent-sandbox.toml` and recreate or restart the workspace.
   - External DNS is disabled in the agent container by design. Direct DNS queries (`dig`, `nslookup`) fail intentionally.

4. **Reboot recovery**:
   Workspaces use `--restart=unless-stopped`. On system boot, `podman-restart.service` automatically restarts running containers. To verify health after boot, run `asb-agent doctor`. Workspaces can also be restarted manually at any time with `asb-agent resume --workspace <id>`.

5. **Clean teardown**:
   - `asb-agent down --workspace <id>`: removes all containers and internal networks, keeping workspace files and git branches intact.
   - `asb-agent purge --workspace <id> --yes`: deletes containers, networks, state, and the workspace directory under `~/asb-agent`.
