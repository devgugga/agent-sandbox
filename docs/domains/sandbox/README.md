# Sandbox Domain Pack

Single Source of Truth (SSoT) for the `agent-sandbox` (v2) runtime environment across all AI agents (Claude Code, OpenAI Codex, Google Antigravity) and orchestrators (Orca).

## Documentation Index

- [Configuration Reference](./configuration.md): Complete `.agent-sandbox.toml` schema and worked examples (hexmed-stack and BlackICE).
- [Security Boundaries](./security.md): Explicit boundary declarations, invariants, and what the sandbox does not protect.
- [Failure Modes & Forensics](./failure-modes.md): Consolidated forensic record from production edge cases, symptoms, causes, and fixes.

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

- **`asb-keyring`**: The singleton Secret Service daemon. Runs as uid 1000 with `--userns keep-id:uid=1000,gid=1000`, `--network none` (zero network interfaces or egress), and `--restart unless-stopped`. Mounts the host passphrase read-only (`ro,Z`), binds the dedicated encrypted keyring data volume `asb-keyring-data` (`/run/asb-keyring-data`), mounts `asb-credentials` as read-only (`ro,z`) for legacy data migration, and exposes the D-Bus session bus Unix socket on the shared runtime volume `asb-keyring-runtime` (`/run/asb-keyring/bus`). Sole owner and writer of the GNOME Keyring database; workspace and login containers connect strictly as D-Bus clients and never mount `asb-keyring-data`.
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
| `login` | autentica os tres agentes (bootstrap inicial da maquina) |
| `up` | cria rede, clone e containers; imprime a conexao |
| `resume` | religa (prepara uplink rootless e podman start); automatico apos reboot |
| `pull` | traz o branch do workspace para o checkout primario |
| `down` | remove containers e rede; **preserva seus arquivos** |
| `purge` | remove tambem os arquivos; exige `--yes` |
| `doctor` | diz o que falta e o comando exato para corrigir |

> [!TIP]
> **Autenticação de Agentes & Secret Service Singleton**:
> O sandbox centraliza o GNOME Keyring em um container singleton (`asb-keyring`, schema 2), eliminando conflitos de concorrência entre daemons. Containers clientes e workspaces conectam-se ao Secret Service via socket Unix compartilhado (`DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus` montado de `asb-keyring-runtime:ro,z`).
> Os bancos de dados ativos do keyring residem no volume dedicado `asb-keyring-data`. O volume `asb-credentials` pode preservar uma cópia legada de `keyrings/` como origem de migração e rollback. Clientes de workspace e login montam `asb-credentials` com uma máscara tmpfs sobre esse subdiretório (`--mount type=tmpfs,destination=/run/asb-credentials/keyrings,ro,notmpcopyup,tmpfs-mode=000`), mantendo apenas `claude.json` e `codex-auth.json` graváveis e impedindo acesso direto tanto aos bancos ativos quanto à cópia legada.
>
> Diferença entre os agentes:
> - **OpenAI Codex**: Persiste seu token diretamente no arquivo `codex-auth.json` em `asb-credentials` (com link simbólico para `~/.codex/auth.json`).
> - **Claude Code**: Conecta-se ao Secret Service / libsecret via D-Bus quando disponível, mantendo fallback de compatibilidade em `claude.json` (`~/.claude/.credentials.json`).
> - **Google Antigravity**: Comunica-se exclusivamente via Secret Service D-Bus para cifrar tokens OAuth no GNOME Keyring.
>
> A autenticação inicial pode ser feita via `asb-agent login` (sobe um container efêmero conectado ao bus para validar os três agentes e depois ser removido) ou diretamente de dentro de qualquer workspace ativo (via terminal SSH). As credenciais persistem imediatamente no volume e valem para todos os workspaces.
>
> **Atenção para migração de workspaces antigos**: Containers criados antes da arquitetura singleton não possuem o mount de `asb-keyring-runtime`, o socket D-Bus ou a máscara de isolamento de keyrings. Como o Podman não permite adicionar mounts a containers existentes em `resume`, workspaces antigos precisam ser recriados (`asb-agent down` seguido de `asb-agent up`). Execute **sempre** `asb-agent pull --workspace <id>` antes de recriar um workspace antigo para preservar alterações locais não integradas.

Additional utility commands:
- `asb-agent list`: lists active and stopped workspaces and their backing repositories.
- `asb-agent suspend --workspace <id>`: puts workspace containers to sleep (`podman stop`).
- `asb-agent reload-allowlist --workspace <id>`: re-renders `squid.conf` and restarts the proxy container without touching the agent container or changing its published SSH port.
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
- **Agent credentials volume (`asb-credentials`)**: Named Podman volume mounted at `/run/asb-credentials:z` in client containers so `codex-auth.json` and the legacy fallback `claude.json` remain writable. It may retain a preserved legacy `keyrings/` tree as a migration and rollback source, but clients mask that subdirectory with a read-only mode-000 tmpfs and cannot access it. The singleton mounts this volume read-only for migration.
- **Keyring data volume (`asb-keyring-data`)**: Named Podman volume mounted read/write only in `asb-keyring` at `/run/asb-keyring-data:z`. Holds the active encrypted GNOME Keyring database and is never mounted in login or workspace containers.
- **Keyring runtime volume (`asb-keyring-runtime`)**: Named Podman volume mounted at `/run/asb-keyring:z` in `asb-keyring` and `/run/asb-keyring:ro,z` in client containers. Holds the active D-Bus session bus Unix socket (`/run/asb-keyring/bus`).
- **Keyring passphrase (`~/.config/agent-sandbox/keyring.pass`)**: 32 random bytes, permissions 0600 on the host, mounted strictly read-only (`-v ~/.config/agent-sandbox/keyring.pass:/run/asb-keyring-pass:ro,Z`) into `asb-keyring`. Never injected via environment variables (`ASB_KEYRING_PASS` is obsolete and never present in `podman inspect`), never accessible to workspace client containers.
- **SSH client key (`~/.config/agent-sandbox/id_ed25519`)**: Generated on demand on the host and authorized inside the container.

---

## 4. What to Do on Failure

1. **Run `asb-agent doctor`**:
   Checks rootless Podman, Python version, base container image, credentials volume (`asb-credentials`), toolcache volume (`asb-toolcache`), `asb-keyring` singleton service health and schema/mount contract, D-Bus session socket and `org.freedesktop.secrets` responsiveness, systemd `podman-restart.service`, legacy workspace compatibility, and active workspace rootless network uplink health.
   - If `asb-keyring` is missing, stopped, or not responding: run `asb-agent login` to initialize or heal it.
   - If `asb-keyring` has an incompatible schema: remove it with `podman rm -f asb-keyring` and re-run `asb-agent login`.
   - If an uplink is dead: run `podman unshare --rootless-netns true`.

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
   Workspaces use `--restart=unless-stopped`. On system boot/login, `podman-restart.service` automatically restarts running containers. To ensure the shared rootless network namespace is functional before container restoration, `asb-agent` installs a systemd user drop-in (`~/.config/systemd/user/podman-restart.service.d/agent-sandbox.conf`) configuring `ExecStartPre=podman unshare --rootless-netns <true>`. Under the default Linux setting (`Linger=no`), user services start upon interactive login (e.g. desktop graphical session); for headless/server setups where workspaces must start unattended before login, enable linger with `loginctl enable-linger $USER`. To verify health after boot, run `asb-agent doctor`. Workspaces can also be restarted manually at any time with `asb-agent resume --workspace <id>`, which automatically ensures the rootless netns uplink is active before starting the proxy.

5. **Clean teardown**:
   - `asb-agent down --workspace <id>`: removes all containers and internal networks, keeping workspace files and git branches intact.
   - `asb-agent purge --workspace <id> --yes`: deletes containers, networks, state, and the workspace directory under `~/asb-agent`.
