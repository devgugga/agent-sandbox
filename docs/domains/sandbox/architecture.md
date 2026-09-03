# Sandbox Architecture

## Principles & Core Boundaries

`agent-sandbox` provisions an isolated, disposable execution environment per project workspace managed by Orca, without requiring permanent host privileges or running privileged containers.

```
+-------------------------------------------------------------------------+
| Pod: asb-<workspace> (Podman Rootless)                                  |
|                                                                         |
|  [Init Container] (terminates after bootstrap)                          |
|    - Runs with CAP_NET_ADMIN                                            |
|    - Applies nftables ruleset in shared network namespace               |
|                                                                         |
|  [Squid Proxy Container]                                                |
|    - Runs as uid 900                                                    |
|    - Sole process allowed external network egress                       |
|    - Filters outbound CONNECT requests against allowlist                |
|                                                                         |
|  [Disposable Services] (e.g. Postgres, Redis)                           |
|    - Declared in .agent-sandbox.toml                                    |
|    - Accessible inside pod at 127.0.0.1:<port>                          |
|                                                                         |
|  [Agent Execution Container]                                            |
|    - Runs as unprivileged user 'agent' (uid 1000)                       |
|    - Zero CAP_NET_ADMIN; no sudo; no host Docker socket                 |
|    - Interacts with outside world strictly via HTTP/HTTPS proxy         |
|    - Reached by Orca via OpenSSH on 127.0.0.1:<ephemeral-port>          |
+-------------------------------------------------------------------------+
```

## Operation Modes

### 1. Isolated Mode (`mode = "isolated"`)
- Default mode for standard tasks and clean unit/integration test runs.
- Ephemeral instances of databases or cache stores (PostgreSQL, Redis) run directly inside the pod.
- Services start fresh for each workspace and disappear upon `agent-sandbox down`.

### 2. Attached Mode (`mode = "attached"`)
- Used when a workspace requires access to existing host development services that cannot easily be containerized ephemerally.
- Forwarders (`socat`) running under uid 900 bind to loopback inside the pod and forward traffic to the host gateway on declared ports.
- Surgical forwarding: only declared ports in `[[attach]]` are accessible.
