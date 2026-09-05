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
