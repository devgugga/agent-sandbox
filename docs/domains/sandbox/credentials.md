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

Credentials for Claude Code, Codex and Antigravity live in the derivative image
`agent-sandbox-auth`, produced by `agent-sandbox auth` after the operator
completes the interactive logins. Nothing is copied from the host home.

The three agents do not store credentials the same way:

| Agent | Storage | Protection |
| :--- | :--- | :--- |
| Claude Code | file under `/home/agent` | plaintext inside the image |
| Codex | `/home/agent/.codex/auth.json` | plaintext inside the image |
| Antigravity (`agy`) | Secret Service (`login.keyring`) | **encrypted**; useless without the host passphrase |

### The keyring, and why the passphrase is not baked

`agy` stores its credential in the Secret Service, not in a file. The image ships
`gnome-keyring` and `dbus`; the entrypoint unlocks the keyring at container start
using `ASB_KEYRING_PASS`, injected at **runtime** from
`~/.config/agent-sandbox/keyring.pass` on the host (32 random bytes, mode 0600).

Because the passphrase is never written into the image, a copy of
`agent-sandbox-auth` carries an encrypted keyring that does not open. This was
verified directly: booting the same image with a wrong passphrase makes `agy`
fail with `authentication failed or timed out` while `claude` still answers,
proving the failure is specific to the keyring rather than a general breakage.

`agy` therefore has a **better** posture than the other two, and the same
treatment could be extended to them.

## Agent configuration persistence

Durable configuration does not use a shared `/home/agent` volume. A full-home
volume would mix mutable state and credentials between unrelated workspaces.
Instead, `profiles/provision.toml` is an explicit allowlist copied on every
`up`:

- Claude and Codex settings, plugins and skills;
- Antigravity settings, `config.json`, `hooks.json`, `mcp_config.json`, import
  manifest, plugins and skills.

Session history, conversations, projects, SSH material and known credential
files are denied recursively. Symlinks are materialized in staging so skills
remain usable without mounting the host home, but only when their resolved
targets stay inside the declared tree, `~/.agents/skills`, or Omarchy's system
skill directory. Any other external target is rejected rather than followed.

Inside the container, provisioning removes destination leaves through a
root-owned no-follow installer. Parent components that the agent replaced by
symlinks are unlinked and recreated as directories; they are never traversed.
SSHD is gated by a unique per-start token until this process finishes, closing
both the symlink TOCTOU window and Orca's reconnect race.

Changes made only inside a workspace remain disposable. Make intended durable
changes in the host source of truth; a real stopped-to-running `resume`
synchronizes the manifest automatically. An already-running `resume` validates
firewall/proxy and returns idempotently without rewriting live configuration.

### Known leak

`ASB_KEYRING_PASS` is passed with `podman run -e`, so it stays in the
container's stored environment and is visible to `podman exec`. It is correctly
absent from SSH sessions and from `/etc/environment`, so the agent does not see
it — but anyone who can run `podman exec` on the host can read it. Since that
person can already read the passphrase file itself, this does not widen the
blast radius, but it is not the tight boundary the runtime-injection design
implies.
