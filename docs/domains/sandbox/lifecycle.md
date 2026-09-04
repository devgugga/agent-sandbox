# Sandbox Lifecycle: Suspend, Resume and Reboot

## Why this document exists

A pod that stops — because the machine rebooted, or because the workspace was
put to sleep — does **not** come back safe on its own. Restarting it the obvious
way produces a running agent with **no network isolation at all**. This was
measured, not theorised:

```
podman pod start <pod>
  → squid container dies       (its config lived in /tmp, which is tmpfs)
  → agent container starts anyway
  → nft list ruleset           → empty
  → curl https://example.com   → 200
  → getent hosts example.com   → resolves
```

The proxy dying was the only visible symptom. The security boundary failed in
silence, which is the more dangerous half.

Two independent facts cause it:

1. **The netns is recreated on every pod start.** nftables rules live in the
   network namespace, and the firewall is applied by a `--rm` init container
   that runs once at `up`. Nothing re-applies it on a restart.
2. **The Squid config used to live in `mktemp`.** `/tmp` is tmpfs, so a reboot
   erased the bind-mount source. `podman pod start` then fails on Squid *only*
   and starts everything else — a partial start is not treated as an error.

## What replaces `podman pod start`

`agent-sandbox resume --workspace <id>` restores the pod in the same order `up`
builds it:

1. Start **only the infra container** — this creates the netns without starting
   any user container. (`podman start $(podman pod inspect … .InfraContainerID)`
   was verified to start the infra alone.)
2. Apply the firewall, then **prove** it applied by reading back
   `nft list table inet asb`.
3. Start Squid and prove, from inside the pod, that it has a default route, can
   resolve an allowed domain and completes an HTTP CONNECT through the proxy.
   A running Squid process alone is not health. Only then start services,
   forwarders and the agent **last**. Before emitting the connection JSON,
   synchronize the current guard and explicit agent-configuration manifest.
   This upgrades an existing authenticated workspace without replacing its
   keyring or writable layer. The entrypoint gates SSH with a unique per-start
   token until synchronization completes, so Orca cannot reconnect halfway
   through materialization.

Any failure in steps 1–3 stops the whole pod and exits non-zero. A half-started
pod is exactly the unsafe state this path exists to prevent.

`resume` never routes through `up`, which begins with `podman pod rm -f`.

## Per-pod state lives in `~/.config/agent-sandbox/pods/<pod>/`

| File | Purpose |
| :--- | :--- |
| `squid.conf` | rendered allowlist; bind-mounted into the Squid container |
| `profile.json` | normalized profile (mode, services, attach, allow) |
| `repo` | the host path mounted at `/home/agent/workspace` |

Not `mktemp`. `down` and `prune` remove the directory; leaving it behind leaks
state per workspace forever.

A pod created before this change has no state directory. `resume` refuses it
with a clear message instead of guessing — recreate the workspace.

## The agent refuses to serve an unprotected sandbox

`image/entrypoint.sh` probes for direct egress before starting `sshd`. If a TCP
connection to `1.1.1.1:443` succeeds without a proxy, the pod firewall is
definitively absent, and the entrypoint exits 1 rather than serving a sandbox
that only looks like one.

- Gated on `ASB_ENFORCE_FIREWALL=1`, set only on the pod's agent container. The
  auth container runs **outside** any pod and needs direct egress for device
  login; without the gate it could never authenticate.
- **Positive detection only.** With no network at all the probe cannot tell
  "firewall present" from "host offline", and lets the agent start. There is no
  egress to protect in that case, but it is a real gap — the ordered `resume`
  path, not this check, is what guarantees isolation.

## Reboot: Orca does not re-run `create`

Orca records each runtime in `~/.config/orca/orca-ephemeral-vm-runtimes.json`
with `status: "running"`, and that record survives a reboot. On the next launch
Orca dials the SSH port it already stored — it does **not** call `create`, and
it does not call `resume` either.

So the reboot path is ours:

```bash
agent-sandbox install-autostart   # ~/.config/systemd/user/agent-sandbox-restore.service
```

A **user** unit wanted by `default.target`, with no `After=default.target` (that
would close an ordering cycle) and no lingering — Orca only runs after login, so
a unit that starts at login is early enough. It calls `agent-sandbox
restore-all`, which resumes every `asb-*` pod.

The unit deliberately has `Restart=on-failure`. Before creating any network
namespace, `restore-all` waits for the host to have both a default route and
working DNS. This ordering is required with rootless `pasta`: a namespace born
before DHCP can keep the route-less snapshot even after the host becomes
online. The bounded wait fails the oneshot and systemd retries five seconds
later.

`ExecStart` carries the repo's absolute path, baked in at install time. **Moving
or renaming the `agent-sandbox` checkout silently breaks boot restore** — re-run
`install-autostart` after a move.

`restore-all` exits 0 when the only thing it could not restore is a pod created
before per-pod state existed (`resume` returns 2 for those, and they are counted
as ignored). A boot unit that goes `failed` for a legacy pod would hide a real
failure in every other pod.

**The stored SSH port is load-bearing.** `podman pod create -p 127.0.0.1::22`
resolves the random port at *create* time and stores it concretely in
`InfraConfig.PortBindings`, so a restart reuses it and Orca's saved connection
stays valid. Verified: port `33613` survived a reboot in the pod spec. The port
is inside `ip_local_port_range`, so another process can steal it across a
reboot; `resume` then fails on the infra start and says so rather than
half-starting.

## Orca lifecycle hooks

`recipes/suspend.sh` and `recipes/resume.sh` implement the optional pair from
the recipe contract (`doctor` requires them paired). `resume` re-emits the full
connection JSON, as the contract requires, because the port may change.

They cover Orca's own sleep/wake. **They do not cover reboot** — see above.

All four hooks source `recipes/common.sh`. The workspace-id derivation used to
be duplicated between `create` and `destroy`, and each time the copies diverged
a pod leaked; `tests/test-recipe.sh` now fails if any hook redefines it.

Every consumer `orca.yaml` must declare the complete set:

```yaml
create:  ./scripts/orca-vm/create.sh
destroy: ./scripts/orca-vm/destroy.sh
suspend: ./scripts/orca-vm/suspend.sh
resume:  ./scripts/orca-vm/resume.sh
```

Use `agent-sandbox doctor` after installation or a reboot. It checks images,
key files, persistent state, authenticated image use, firewall and real proxy
connectivity for every running pod. A stopped pod is reported as unverified and
returns non-zero; `doctor` does not guess whether it was intentionally suspended
or failed during restore.

`up` never replaces an existing workspace implicitly. Use `resume` for an
existing pod or `down` explicitly before creating a replacement; this prevents
a failed rebuild from destroying a healthy writable layer and saved state.
