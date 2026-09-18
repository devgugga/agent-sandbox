# Sandbox Domain Pack

Single Source of Truth (SSoT) for the `agent-sandbox` (v2) runtime environment across all AI agents (Claude Code, OpenAI Codex, Google Antigravity) and orchestrators (Orca).

## Documentation Index

- [Configuration Reference](./configuration.md): Complete `.agent-sandbox.toml` schema and worked examples (hexmed-stack and BlackICE).
- [Workspace Lifecycle](./lifecycle.md): Single systemd runtime, boot ordering behind the network wait, command semantics, recovery by category, persistent agent sessions, the TUI, worktree creation, and finish/cleanup.
- [Provider Authentication](./authentication.md): Account vs. network vs. infrastructure diagnosis, where each credential lives, and login.
- [Security Boundaries](./security.md): Explicit boundary declarations, invariants, and what the sandbox does not protect.
- [Failure Modes & Forensics](./failure-modes.md): Consolidated forensic record from production edge cases, symptoms, causes, and fixes.
- [Known Regressions](./known-regressions.md): Catalogue of already-fixed defects, recorded by shape, for checking a diff against.

---

## 1. System Topology

Every workspace runs in an isolated network topology managed via rootless Podman, connected to a global Secret Service singleton:

```text
Serviço Global de Credenciais (Singleton):
host keyring.pass (ro,Z) ──┐
asb-credentials (ro,z)    ─┼─> asb-keyring (--network none, uid 1000)
asb-keyring-data (z)      ─┤       │
asb-keyring-runtime (z)   ─┘       │ unix:/run/asb-keyring/bus
                                   │
                   ┌───────────────┼───────────────┐
                   │               │               │
               asb-login      asb-<ws1>-agent  asb-<ws2>-agent

Topologia de Rede por Workspace:
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

- **`asb-keyring`**: The singleton Secret Service daemon. Runs as uid 1000 with `--userns keep-id:uid=1000,gid=1000`, `--network none` (zero network interfaces or egress), and `--restart no`, supervised by `asb-keyring.service`. Mounts the host passphrase read-only (`ro,Z`), binds the dedicated encrypted keyring data volume `asb-keyring-data` (`/run/asb-keyring-data`), mounts `asb-credentials` as read-only (`ro,z`) for legacy data migration, and exposes the D-Bus session bus Unix socket on the shared runtime volume `asb-keyring-runtime` (`/run/asb-keyring/bus`). Sole owner and writer of the GNOME Keyring database; workspace and login containers connect strictly as D-Bus clients and never mount `asb-keyring-data`.
- **`asb-<ws>-agent`**: The execution environment. Mirrors the host user (identical username, uid 1000, identical `$HOME`). Reached by Orca via OpenSSH published to `127.0.0.1:<random-port>`. Has no default network route and no external DNS. Mounts `asb-keyring-runtime` as read-only (`ro,z`) and sets `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus`.
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
| `login [--agent X]` | autentica um fornecedor, ou todos, uma vez por maquina |
| `auth status\|verify` | status de conta por fornecedor; `verify` faz uma chamada real |
| `up` | cria rede, clone, containers e unidades systemd; imprime a conexao |
| `suspend` | para o workspace e o tira do inicio automatico |
| `resume` | religa pelo systemd; automatico no login para workspaces nao suspensos |
| `pull` | traz o branch do workspace para o checkout primario |
| `connect` | abre um shell SSH num workspace ja rodando; nunca o inicia |
| `down` | remove containers e rede; **preserva seus arquivos** |
| `purge` | remove tambem os arquivos; exige `--yes` |
| `doctor` | diz o que falta e o comando exato para corrigir |
| `project add` | registra um projeto e seu checkout primario; nunca cria workspace |
| `session list\|start\|attach\|stop\|resume` | sessoes de agente persistentes em tmux dentro do workspace |
| `tui` | arvore de projetos, checkouts e sessoes; cria worktrees e os finaliza |

Authentication, credential storage and login are described in
[authentication.md](./authentication.md); start, stop, reboot and recovery in
[lifecycle.md](./lifecycle.md), which also covers `connect` (§4), agent
sessions (§5), the TUI and worktree creation (§6), and finish/cleanup (§7).

Additional utility commands:
- `asb-agent list`: lists active and stopped workspaces and their backing repositories.
- `asb-agent reload-allowlist --workspace <id>`: re-renders `squid.conf` and restarts the proxy **unit** (`systemctl --user try-restart`) without touching the agent container or changing its published SSH port.
  - The profile is read **only** from the operator's checkout — never from the clone inside the workspace. That clone sits in the agent's writable mount, so preferring it would let an agent extend its own egress policy and wait for the operator to apply it on the next reload. This is the same invariant that keeps `state/` outside the mount, and it is the same source `asb-agent up` uses: the two routes must never diverge.
- `asb-agent install-guards`: installs the host command wrappers (`asb-claude`, `asb-codex`, `asb-agy`) **and `asb-agent` itself** into `~/.local/bin`, so the CLI runs from any directory instead of only from the checkout. All four are symlinks, never copies: a copy ages silently and starts behaving differently from what this repository says. `asb-agent doctor` verifies each one still points at this checkout — moving the checkout breaks them, and the failure is otherwise silent.
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
- **TUI control state (`~/.local/state/agent-sandbox/projects.json`, `sessions.json`)**: Projects, checkout-to-workspace bindings and agent sessions, relationships only (files `0600`, directory `0700`). Never a credential, prompt, model output or transcript; Podman, systemd, tmux and the repositories stay authoritative. Details in [lifecycle.md §5](./lifecycle.md#5-persistent-agent-sessions).
- **Agent credentials volume (`asb-credentials`)**: Named Podman volume holding one directory per provider (`claude/`, `codex/`), mounted as the directories `~/.claude` and `~/.codex` in agent and login containers. Per-workspace session state (`asb-<ws>-session`) is mounted over the transcript subdirectories. The volume may still hold a legacy `keyrings/` tree, masked in clients by a read-only mode-000 tmpfs; the singleton mounts the volume read-only for migration. Details in [authentication.md](./authentication.md).
- **Keyring data volume (`asb-keyring-data`)**: Named Podman volume mounted read/write only in `asb-keyring` at `/run/asb-keyring-data:z`. Holds the active encrypted GNOME Keyring database and is never mounted in login or workspace containers.
- **Keyring runtime volume (`asb-keyring-runtime`)**: Named Podman volume mounted at `/run/asb-keyring:z` in `asb-keyring` and `/run/asb-keyring:ro,z` in client containers. Holds the active D-Bus session bus Unix socket (`/run/asb-keyring/bus`).
- **Keyring passphrase (`~/.config/agent-sandbox/keyring.pass`)**: 32 random bytes, permissions 0600 on the host, mounted strictly read-only (`-v ~/.config/agent-sandbox/keyring.pass:/run/asb-keyring-pass:ro,Z`) into `asb-keyring`. Never injected via environment variables (`ASB_KEYRING_PASS` is obsolete and never present in `podman inspect`), never accessible to workspace client containers.
- **SSH client key (`~/.config/agent-sandbox/id_ed25519`)**: Generated on demand on the host and authorized inside the container.

---

## 4. What to Do on Failure

1. **Run `asb-agent doctor`.** It checks Podman, Python, image, volumes, the
   `asb-keyring` service, the legacy `podman-restart` drop-in (must be absent),
   `asb-network.service`, third-party producers of the rootless namespace at
   boot, guards, tool drift and every workspace's egress. Each failing line
   carries its remediation.
2. **Recovery by category** (network, dead uplink, proxy, service, SSH,
   keyring, units that gave up): [lifecycle.md §3](./lifecycle.md#3-recovery-by-category).
3. **Account problems** (logged out, provider errors):
   [authentication.md](./authentication.md). Logging in again never repairs
   infrastructure.
4. **Agent cannot reach an external service**: egress is default-deny. Look for
   `TCP_DENIED/403` in `podman logs asb-<ws>-proxy`, add the domain under
   `[network].allow` in the operator's `.agent-sandbox.toml`, then
   `asb-agent reload-allowlist --workspace <id>`. Direct DNS queries (`dig`,
   `nslookup`) fail by design.
5. **`up` failed**: it is transactional; a failed creation rolls back its
   containers and networks and keeps the files under `~/asb-agent/<proj>/<ws>/`.
   Read stderr for the cause.
6. **Teardown**: `asb-agent down --workspace <id>` keeps files, branches and
   session state; `asb-agent purge --workspace <id> --yes` removes them too.
