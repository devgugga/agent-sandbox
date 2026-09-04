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

## User Namespace: `keep-id`

The pod is created with `--userns=keep-id:uid=1000,gid=1000`. Without it, the
host user's uid 1000 maps to uid **0** inside the container, the mounted
repository appears owned by root, and the agent (uid 1000) **cannot write to
its own workspace** — the sandbox is useless for its primary purpose.

Three consequences follow, and each one broke the sandbox when missed:

| Requirement | Why |
| :--- | :--- |
| `--userns` on `podman pod create`, never on `podman run --pod` | Podman rejects the latter: *"cannot set user namespace mode when joining pod with infra container"*. |
| Firewall init container runs as `--user 1000` | Under `keep-id` the user namespace owner is uid 1000, not 0. As root the `nft` calls fail with *"Operation not permitted"* and **the firewall silently does not come up**, leaving the sandbox with no network isolation at all. |
| Service containers run as `--user 0` | Images with no `USER` directive (such as `postgres`) are resolved by `keep-id` to the mapped host uid, and `initdb` then fails to adjust permissions on the image's own directories. |

## Repository Mount Point

The repository is mounted at `/home/agent/workspace`, and that path is what
`create.sh` reports as `projectRoot`.

It is deliberately **not** `/workspace`. Orca creates sibling worktrees of the
project root (`<root>-<name>`), so a project root at `/workspace` puts the
sibling at `/workspace-Teste` — in the filesystem root, which is mode `555` and
not writable even by root inside the container. The observed failure was
`fatal: could not create leading directories`. With the mount under
`/home/agent`, the parent is owned by the agent and both Orca worktree layouts
(siblings and in-repo `.worktrees`) work.

## Operation Modes

### 1. Isolated Mode (`mode = "isolated"`)
- Default mode for standard tasks and clean unit/integration test runs.
- Ephemeral instances of databases or cache stores (PostgreSQL, Redis) run directly inside the pod.
- Services start fresh for each workspace and disappear upon `agent-sandbox down`.

### 2. Attached Mode (`mode = "attached"`)
- Used when a workspace requires access to existing host development services that cannot easily be containerized ephemerally.
- Squid does **not** serve this case: it is a CONNECT proxy for TLS and does not carry the PostgreSQL wire protocol. Attached mode uses its own mechanism.
- Forwarders (`socat`) running under uid 900 bind to loopback inside the pod and forward traffic to the host gateway on declared ports. The property is preserved: the agent still has no direct egress and only talks to loopback; the process that leaves is uid 900, already permitted by the firewall.
- Surgical forwarding: only declared ports in `[[attach]]` are accessible. Never open private ranges — the host participates in a Tailscale network and `pasta` copies host interfaces into the pod's namespace, so allowing RFC1918 or CGNAT would hand the agent the whole tailnet.

> **Unverified.** Attached mode has never run end to end. `tests/test-attached.sh`
> skips whenever nothing is listening on the host port, which has been every
> run so far. Treat this section as design intent, not as observed behavior.
