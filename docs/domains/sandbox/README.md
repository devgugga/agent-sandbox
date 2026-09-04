# Sandbox Domain Pack

This domain pack serves as the Single Source of Truth (SSoT) for the `agent-sandbox` runtime environment across all AI agents and orchestrators.

## Documentation Index

- [Architecture](./architecture.md): Pod structure, container lifecycles, and isolated vs attached modes.
- [Network & Firewall](./network.md): nftables ruleset, Squid proxy egress filtering, and domain allowlists.
- [Credentials & Security](./credentials.md): SSH authentication, host isolation, and agent tokens.
- [Authentication](./authentication.md): Device-auth workflow and derivative image generation.
- [Lifecycle](./lifecycle.md): Suspend, resume, and why a rebooted pod must never be restarted with `podman pod start`.
- [Troubleshooting](./troubleshooting.md): Operational edge cases, environment propagation, and runtime diagnostics.
- [Hexmed Stack Notes](./hexmed-notes.md): Configuration reference for the `hexmed-stack` project.
- [Enforcement](./enforcement.md): The `asb-agent` guard, Orca's `Command` override, and the limits of what it protects.

## Read this first

- The container is the boundary. The guard is **not** a security boundary; it
  prevents accidental execution outside the sandbox.
- Attached mode is **unverified** — it has never run end to end.
- **Never restart a sandbox with `podman pod start`.** The netns is recreated
  and the nftables rules are lost; the agent comes back with unrestricted
  egress. Use `agent-sandbox resume` — see [Lifecycle](./lifecycle.md).
- Every allowlist entry exists because something broke without it. Add domains
  only against an observed `TCP_DENIED`, never preemptively.
