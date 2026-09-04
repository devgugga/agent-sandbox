# Authentication Workflow

`agent-sandbox auth` builds the derivative image `agent-sandbox-auth` from the
base image. The operator performs the interactive logins; the script verifies
them and only then commits.

## Running it

```bash
agent-sandbox auth
```

It starts the container with the **real entrypoint** — not `--entrypoint sleep`
— because the entrypoint is what starts D-Bus, unlocks the keyring and populates
`/etc/profile.d`. With `sleep` none of that happens and `agy` silently falls back
to storing its credential in a plaintext file instead of the encrypted keyring.

This is also why the image must not hardcode a proxy: the auth container runs
outside the pod, where no Squid exists, so the entrypoint exports
`HTTPS_PROXY`/`HTTP_PROXY` only when they are actually provided.

## The three logins

```bash
podman exec -it -u agent asb-auth bash -lc 'claude /login'
podman exec -it -u agent asb-auth bash -lc 'codex login --device-auth'
podman exec -it -u agent asb-auth bash -lc agy
```

Three details that each cost a debugging round:

- **`bash -lc` is not decoration.** Without a login shell, `agy` is not on the
  `PATH` and `DBUS_SESSION_BUS_ADDRESS` is absent — which is exactly how a
  credential ends up in plaintext instead of the keyring.
- **`agy` has no `login` subcommand.** Running bare `agy` opens the TUI, which
  triggers authentication on first use. `agy login` fails with
  `unexpected argument "login"`.
- **Always use device-auth flows.** The default OAuth login starts a callback
  server on a container port the host browser cannot reach, and hangs.

## Verification before commit

Authentication is verified by **exit code**, never by grepping for
`logged in` — that string also matches "**not** logged in" and would commit an
unauthenticated image. If any agent fails, the script aborts rather than
producing a broken image.

## Expiry

Baked credentials expire. The symptom is the agent reporting that it is not
logged in inside a freshly created workspace. The fix is to re-run
`agent-sandbox auth`. Re-running starts from the base image, so all three logins
are redone; to preserve existing ones, layer the new scripts onto the current
authenticated image instead of rebuilding it from scratch.

## SSH detection in Antigravity

`agy` detects an SSH session and treats it as a **new remote login**, ignoring
its cached credential and demanding device-auth every time. Orca connects to the
recipe container over SSH, so this makes the agent unusable in the sandbox.

The guard `asb-agy` unsets `SSH_CONNECTION`, `SSH_CLIENT` and `SSH_TTY` before
`exec`, scoped to `agy` alone — Claude and Codex work fine over SSH. A
consequence worth knowing: if the Orca `Command` field is reverted to plain
`agy`, this bug returns.
