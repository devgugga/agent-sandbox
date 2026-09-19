# Configuration Reference (`.agent-sandbox.toml`)

This document defines the configuration schema for `.agent-sandbox.toml` in the project root.

Every field is optional. An absent field assumes its default value, and the default is always closed (least privilege). An absent file is equivalent to an empty file: an isolated sandbox with no access to host Docker, no forwarded host ports, and default network filtering.

---

## 1. Schema Reference

```toml
[network]
# Domínios adicionais liberados no Squid, somados à allowlist base.
# Prefixo "." casa o domínio e todos os subdomínios.
allow = ["pypi.org", "files.pythonhosted.org", ".sentry.io"]

[docker]
# Portas de serviços do HOST alcançáveis pelo agente (§6.1).
# Apenas as declaradas. Nunca faixas.
host_ports = [5432, 6379]

# Portas do SANDBOX publicadas em 127.0.0.1 no HOST para acesso pelo navegador/operador.
# Suporta inteiros diretos ([8081]) ou mapeamentos explícitos (["18080:80"]).
publish_ports = ["18080:80", 8081]

# Runtime de containers DENTRO do sandbox (§6.2).
#   "none"   (padrão) — sem containers aninhados
#   "nested"          — Podman rootless dentro do sandbox
mode = "nested"

# Acesso à API do Docker do HOST, via broker filtrado (§6.3).
#   "none" (padrão) — nenhum acesso
#   "read"          — version, events, ps, inspect, logs. Mutação → 403.
# Exige `asb-agent install-broker` executado uma vez com sudo.
host_api = "read"

[services]
# Serviços descartáveis, criados no `up` e destruídos no `down`.
# Alcançados pelo agente em asb-<ws>-svc-<nome>, pela rede interna.
[services.db]
image = "docker.io/library/postgres:17"
env = { POSTGRES_USER = "sandbox", POSTGRES_PASSWORD = "sandbox", POSTGRES_DB = "sandbox" }
```

### Notes on Service Containers

Images without a `USER` directive (such as official `postgres` images) require `--user 0`. Under rootless `keep-id`, unmapped root resolves to the mapped host user, causing `initdb` to fail with `Operation not permitted` when setting permissions on its own database directories. The runtime handles this flag automatically for service containers.

### Changes from v1 Schema

- **No `tools` configuration**: The Single Source of Truth for project runtimes and tool versions is the project's own `mise.toml`. Machine-local overrides belong in `mise.local.toml`.
- **`[sandbox] mode = "isolated" | "attached"` is gone**: The coarse "attached" switch was replaced by explicit, granular axes: `docker.host_ports` and `docker.host_api`.
- **`[proxy] java` is removed**: It was an unverified, one-off adjustment that is no longer needed.

---

## 2. Toolchain Provisioning & Shared Cache (`asb-toolcache`)

Development runtimes (Java, Node, Python, pnpm, uv, Maven, process-compose) are declared in `mise.toml` files within the project repository rather than configured in `.agent-sandbox.toml`.

### Shared Tool Cache
To prevent redundant multi-gigabyte downloads across multiple workspaces and task recycles, the sandbox maintains a shared persistent volume: `asb-toolcache`.
- **Mount Location**: Mounted into the agent container at `/run/asb-toolcache:Z`.
- **Cached Runtimes**: Transparently symlinked into the agent home directory at startup:
  - `~/.local/share/mise` -> `/run/asb-toolcache/mise` (installed toolchain binaries)
  - `~/.cache` -> `/run/asb-toolcache/cache` (pip, npm, and general caches)
  - `~/.m2` -> `/run/asb-toolcache/m2` (Maven repository cache)
  - `~/.local/share/uv` -> `/run/asb-toolcache/uv` (uv-managed Python standalone runtimes)
- **Persistence**: Survives `asb-agent down` and container destruction. Removed only on manual `podman volume rm asb-toolcache`.

### Multi-Directory Discovery & Cold Cache Duration
During `asb-agent up`:
1. The runtime discovers all `mise.toml` manifests starting from the project root and scanning subdirectories hierarchically.
2. Build output and dependency folders are automatically pruned from the search (`.git`, `node_modules`, `target`, `dist`, `build`, `.venv`, `.next`, `__pycache__`).
3. For each manifest, `mise install -y` is executed non-interactively in the corresponding folder.
4. **Cold Cache vs Hot Cache**: On the very first `up` for a repository, all toolchains are downloaded through the Squid proxy, which may take several minutes depending on network bandwidth. Subsequent workspaces and recycled containers reuse the cached binaries from `asb-toolcache` in seconds.
5. If tool installation fails in any directory (e.g. missing allowlist domain), `asb-agent up` exits with code 1, does not emit the Orca JSON handshake, and preserves the workspace so the operator can adjust `.agent-sandbox.toml` and retry `asb-agent up` directly.

---

## 3. Agent Context Tools (`rtk`, `graphify`)

Two tools are baked into the **image** rather than declared per project, because every project uses them and a `mise.toml` entry would turn them into a repeated download in each repository:

| Tool | Role | Runtime network |
| :--- | :--- | :--- |
| `rtk` | CLI proxy that filters and summarises command output to save agent context | none |
| `graphify` | knowledge graph over the repository (tree-sitter AST, local) | none for code |
| `uv` | Python package/tool manager; also required by projects such as `hexmed-stack/pacs/server` | pypi.org (per project allowlist) |

Neither requires configuration: `rtk` runs on defaults (`~/.config/rtk/` is not created) and `graphify` installs its own skill into the project it is run against, so that skill travels with the worktree. Neither needs an allowlist entry — installation happens during `podman build` on the host, and both are offline at runtime.

`rtk` telemetry is opt-in upstream and is additionally pinned off with `RTK_TELEMETRY_DISABLED=1`.

### Install location is not incidental

The tools are installed to `/usr/local/bin` (binaries) and `/opt/uv-tools` (the graphify virtualenv), never under `~/.local`. The entrypoint deletes and re-links parts of the home directory on every start to mount `asb-toolcache`:

```bash
rm -rf "$ASB_HOME/.local/share/uv"
ln -sfn /run/asb-toolcache/uv "$ASB_HOME/.local/share/uv"
```

`uv tool install` defaults to exactly that path. Installing there at build time would delete graphify on the first container start, and the symptom (`graphify: command not found`) would give no hint of the cause. `UV_TOOL_DIR` is therefore set only for the build step — at runtime it stays unset, so an agent's own `uv tool install` lands in the persistent toolcache, which is where it belongs.

### Version pinning and drift

Versions are pinned as build args and published as image labels:

```dockerfile
ARG UV_VERSION=0.12.10
ARG RTK_VERSION=0.46.0
ARG GRAPHIFY_VERSION=0.9.51
LABEL asb.rtk.version="${RTK_VERSION}" asb.graphify.version="${GRAPHIFY_VERSION}"
```

A pinned build is reproducible, but the image then drifts behind the host, where the operator upgrades these tools. `asb-agent doctor` closes that gap by comparing each label against the host binary:

```
ok   rtk 0.46.0 (imagem e host em sincronia)
FALTA rtk 0.46.0 na imagem, 0.48.1 no host  ->  asb-agent build
```

Drift is reported but does not fail `doctor`: the image stays usable on the older version. What must not happen is the divergence staying invisible. If the host does not have the tool at all, nothing is printed — not every host uses `rtk`, and warning there would be noise rather than diagnosis.

---

## Provider CLIs (`claude`, `codex`, `agy`): mise `latest`, root-owned

The three provider CLIs follow a different policy from the tools above: they are installed with mise, using the same aqua backends as the operator's host (`aqua:anthropics/claude-code`, `aqua:openai/codex`, `aqua:google-antigravity/antigravity-cli`), each at `latest` resolved **at image build time**. Every rebuild takes the newest release mise accepts, so two builds can differ. Nothing is installed from npm or from a pinned tarball any more; Node.js stays in the image because Orca's remote agent compiles `node-pty` inside the container (see `failure-modes.md`).

- **Location**: a root-owned mise tree at `/opt/asb-mise` (`libexec/mise`, `config/config.toml`, `data/installs/...`). `MISE_DATA_DIR`/`MISE_CONFIG_DIR`/`MISE_CACHE_DIR`/`MISE_STATE_DIR` are set only for that build step, never as `ENV`, so an agent's own `mise install` still lands in `asb-toolcache`.
- **Never under `~/.local/share/mise`**: the entrypoint replaces that path with a symlink to the shared, agent-writable toolcache. An install there would vanish on the first start, and one workspace's agent could replace the binaries every workspace and the auth clients use.
- **PATH**: `/opt/asb-mise/bin` holds symlinks straight to the installed executables and comes before `~/.local/bin` and the toolcache shims in the image `ENV PATH`, which the entrypoint copies to `/etc/environment`. That is the path sessions use: `asb-agent` starts agents through non-interactive `ssh` exec and tmux runs the agent command without a login shell, so `claude`, `codex` and `agy` resolve to `/opt/asb-mise/bin` there. Symlinks rather than mise shims: a shim consults user config at runtime and could resolve another version, or none.
- **Login shells are not protected**: `/etc/profile.d/agent-sandbox.sh` also puts `/opt/asb-mise/bin` first, but in an interactive login shell Debian's stock `~/.profile` runs afterwards and prepends `$HOME/.local/bin` and `$HOME/bin`, so a file the agent writes there shadows the provider CLIs in that shell. This is not a boundary the image can keep: the agent owns its container `HOME` and can rewrite `~/.profile` itself. What does hold: uid 1000 cannot modify anything under `/opt/asb-mise`, one workspace's agent cannot replace another workspace's or the auth clients' binaries, and session launches never go through a login shell.
- **Smoke gate, not version gate**: the build fails unless each binary resolves to `/opt/asb-mise/bin`, runs as the unprivileged user, and prints `--version` in its known format — `<v> (Claude Code)`, `codex-cli <v>`, `<v>` (agy). The versions read there are written to `/opt/asb-mise/versions` (`claude=…`, `codex=…`, `agy=…`, root-owned, `0644`). A Containerfile `LABEL` cannot carry a value computed in a `RUN`, so the old `asb.claude.version`/`asb.codex.version`/`asb.agy.version` labels are gone rather than faked. Read it with `podman run --rm --entrypoint cat localhost/agent-sandbox:latest /opt/asb-mise/versions`.
- **Self-update**: the binaries are root-owned and cannot replace themselves. `DISABLE_AUTOUPDATER=1` (Claude Code) and `AGY_CLI_DISABLE_AUTO_UPDATE=1` (read from the agy binary's strings, undocumented) silence the attempt. Codex only offers `check_for_update_on_startup` in `~/.codex/config.toml`, which is the credential volume, so it is left alone.
- **`latest` is mise's `latest`**: mise 2026.9.11 hides releases younger than its built-in minimum release age from `latest` (`mise ls-remote` warns "N newer releases hidden by minimum_release_age"), so the image can trail the host by the newest release or two.

---

## 3. Worked Examples

### Example 1: `hexmed` (Host Services & Filtered Docker Inspection)

In `hexmed`, tests and workflows require access to host infrastructure services (PostgreSQL on port 5432, Redis on port 6379) and read-only inspection of host containers (e.g. DCM4CHEE DICOM archive), plus external dependencies from npm and Python registries:

```toml
# /path/to/hexmed/.agent-sandbox.toml

[network]
allow = [
  "registry.npmjs.org",
  "repo.maven.apache.org",
  "pypi.org",
  "files.pythonhosted.org"
]

[docker]
# Reach PostgreSQL (5432) and Redis (6379) running on the host
host_ports = [5432, 6379]

# Enable read-only Docker API access through the host broker.
# The agent can run `docker ps`, `docker logs`, and `docker inspect`
# to check service status, but cannot create, stop, or delete containers.
host_api = "read"
```

**Prerequisites for this configuration:**
1. Run `asb-agent install-broker` once on the host with `sudo` to set up the systemd socket broker (`/run/asb-docker/docker.sock`).
2. The agent container accesses host services via `localhost:5432` and `localhost:6379` through the dedicated `asb-<ws>-fwd` forwarder.

---

### Example 2: `BlackICE` (Nested Container Runtime)

In `BlackICE`, the agent develops and tests containerized pipelines. Rather than mounting the host Docker socket (which breaks container isolation), `BlackICE` enables an isolated, rootless Podman runtime inside the sandbox:

```toml
# /path/to/BlackICE/.agent-sandbox.toml

[network]
allow = [
  "registry.npmjs.org",
  "pypi.org",
  "files.pythonhosted.org",
  "quay.io",
  ".docker.io",
  "registry-1.docker.io",
  "production.cloudflare.docker.com"
]

[docker]
# Run rootless Podman inside the sandbox without privileges on the host
mode = "nested"
# Publish ports to 127.0.0.1 on the host for browser access (Traefik 80 -> 18080, dashboard 8081)
publish_ports = ["18080:80", 8081]
```

**How it operates:**
1. The agent container is provided `/dev/fuse` and an isolated volume `asb-<ws>-containers` mounted at `$HOME/.local/share/containers`.
2. Inside the sandbox, the agent executes `podman build`, `podman run`, and `podman compose` entirely rootless and inside its own boundary.
3. Image layers and container storage persist across `suspend`/`resume` and `down`/`up` in the dedicated volume, preventing repeated pulls.
4. No host Docker socket is exposed, and the agent container remains unprivileged (`--privileged` is never used).
