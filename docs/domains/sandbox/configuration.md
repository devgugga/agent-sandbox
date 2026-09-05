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

## 2. Worked Examples

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
```

**How it operates:**
1. The agent container is provided `/dev/fuse` and an isolated volume `asb-<ws>-containers` mounted at `$HOME/.local/share/containers`.
2. Inside the sandbox, the agent executes `podman build`, `podman run`, and `podman compose` entirely rootless and inside its own boundary.
3. Image layers and container storage persist across `suspend`/`resume` and `down`/`up` in the dedicated volume, preventing repeated pulls.
4. No host Docker socket is exposed, and the agent container remains unprivileged (`--privileged` is never used).
