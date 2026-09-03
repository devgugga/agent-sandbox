# Credentials & Security Boundaries

## Non-Negotiable Invariants

1. **Host Home Isolation**: The host user's home directory (`$HOME`) is never mounted into any container.
2. **Git Credentials**: No host SSH keys, Git credentials, PATs, or GitHub CLI tokens are mounted into or stored inside the sandbox.
3. **No Container Escapes**: The host Docker socket (`/var/run/docker.sock`) is never mounted, and `sudo` is absent from the container.

## SSH Authentication Contract

- **Host Keys**: Generated at container build time (`ssh-keygen -A` inside `image/Containerfile`). This guarantees stable host keys across ephemeral workspace instances on `127.0.0.1`, eliminating `known_hosts` collisions.
- **Client Key Pair**: Generated on demand under `${XDG_CONFIG_HOME:-$HOME/.config}/agent-sandbox/id_ed25519` on the host. The public key is injected via `ORCA_SSH_PUBLIC_KEY` into `/home/agent/.ssh/authorized_keys` upon container startup.
- **sshd Policy**:
  - `PermitRootLogin no`
  - `PasswordAuthentication no`
  - `PubkeyAuthentication yes`
  - `AuthorizedKeysFile /home/agent/.ssh/authorized_keys`

## Agent Model Authentication

Agent API tokens for Claude Code, Codex, and Gemini are managed in a derivative container image `agent-sandbox-auth`. The interactive authentication script (`agent-sandbox auth`) guides the operator through device-code authentication, persisting tokens exclusively inside `/home/agent` of the container image.
