# Provider Authentication

How Claude Code, OpenAI Codex and Google Antigravity (`agy`) authenticate,
where each credential lives, and how to tell an account problem from a network
or infrastructure problem. Contracts were characterized against the pinned CLI
versions in
[`docs/validation/2026-09-07-provider-auth-contracts.md`](../../validation/2026-09-07-provider-auth-contracts.md)
and validated live in
[`docs/validation/startup-auth-pilot.md`](../../validation/startup-auth-pilot.md) §5.
The image no longer pins those versions: it installs each CLI at mise
`latest` at build time and records what it got in `/opt/asb-mise/versions`
(see [`configuration.md`](./configuration.md) §3). A rebuild can therefore
change a contract characterized here; re-check it against that file.

---

## 1. Three Separate Questions

| Question | Tool | Never does |
| :--- | :--- | :--- |
| Is the **account** authenticated? | `asb-agent auth status --workspace <id> [--agent X] [--json]` | log in, log out, or send a prompt |
| Does the provider **accept** the credential right now? | `asb-agent auth verify --workspace <id> [--agent X] [--json]` | retry; it makes exactly one real call per provider, inside the running workspace, through its proxy |
| Is the **infrastructure** healthy (network, proxy, keyring, containers)? | `asb-agent doctor` | touch accounts |

A network or infrastructure failure is reported as `unreachable` or
`provider_error`, never as logged out. Logging in again does not repair
infrastructure, and deleting a credential is never a recovery step.

### States

| State | Meaning | Next step |
| :--- | :--- | :--- |
| `authenticated` | Status command (or, for `verify`, a real call) says the account works | — |
| `unauthenticated` | The provider itself reported no valid credential | `asb-agent login --agent <provider>` |
| `unknown` | No trustworthy local answer; normal for `agy`, which has no status command | `asb-agent auth verify --workspace <id> --agent agy` |
| `pending` | Reported by `login` for `agy`, which a fresh client cannot check without a real call | `asb-agent auth verify --workspace <id> --agent agy` |
| `unreachable` | Network or proxy failed before or during the call; the call is not counted | `asb-agent doctor` |
| `provider_error` | Rate limit (429) or provider service error (5xx) | wait; do not repeat the call now |

`verify` classifies provider output against a fixed list of known markers and
records only canned evidence text, never raw output, where tokens would appear.

---

## 2. Where Credentials Live

One login per provider serves every workspace. Credentials are shared; session
history is not.

| Provider | Credential | Storage | Encrypted at rest | Readable by agent processes |
| :--- | :--- | :--- | :--- | :--- |
| Claude Code | `~/.claude/.credentials.json` (regular file, `0600`) | `claude/` subpath of volume `asb-credentials`, mounted as the **directory** `~/.claude` | no (plain JSON) | yes, in every workspace |
| OpenAI Codex | `~/.codex/auth.json` (regular file) | `codex/` subpath of `asb-credentials`, mounted as the directory `~/.codex` | no (plain JSON) | yes, in every workspace |
| Antigravity (`agy`) | entries in GNOME Keyring via the Secret Service D-Bus API | volume `asb-keyring-data`, mounted **only** in `asb-keyring` | yes, with `~/.config/agent-sandbox/keyring.pass` | through the D-Bus socket (`/run/asb-keyring/bus`), not as files |

- **Directories, never files or symlinks.** Provider writers replace
  credentials atomically; a symlink is replaced by a regular file (link lost),
  a single-file bind mount fails with `EBUSY`, and Claude refuses symlinks
  outright ([R2](./known-regressions.md)).
- **Per-workspace session state.** Volume `asb-<ws>-session` is mounted over
  `~/.claude/projects`, `~/.claude/todos`, `~/.claude/shell-snapshots` and
  `~/.codex/sessions`, so workspaces share the login but not transcripts. `down`
  keeps it; `purge` removes it.
- **Legacy root files.** The pre-A3 layout kept `codex-auth.json`,
  `claude.json` and similar at the root of `asb-credentials`. The CLI warns when
  any remain; they are unused but readable by agent containers. Remove them
  only after a new login is confirmed.
- **Claude first-run state is not a credential.** Claude Code keeps its
  "onboarding done" flag in `~/.claude.json`, which sits in each workspace
  container's writable layer, not in `asb-credentials`. Without it, a new
  workspace showed "Select login method" although the credential was valid.
  The image entrypoint now runs `asb-seed-claude-state` at every container
  start, as the unprivileged user: it sets only `hasCompletedOnboarding: true`,
  keeps every other key, and leaves an unparseable or non-regular file
  untouched with a warning. It never reads or writes `~/.claude/`, so the
  credential itself is untouched. Only workspaces created from an image built
  with the helper get it; an existing container keeps its original image.
- **Renewal.** Refresh tokens are written in place by the provider CLI.
  Observed for Claude on 2026-09-17: the file was rewritten with a new expiry
  and stayed `authenticated`.

---

## 3. Logging In

```bash
asb-agent login                 # all providers, one at a time
asb-agent login --agent codex   # only one
```

- Requires an interactive terminal (device-auth reads a code from the
  operator); without a TTY it exits 2 with guidance.
- Each provider runs in its own short-lived client container, under its own
  lock, and the result is checked again in a **fresh** client, so a provider
  that fails does not take the others with it and a login is never reported
  from the same process that performed it.
- Native flows: `claude auth login`, `codex login --device-auth`, and the
  interactive `agy` TUI. `claude /login` exits 0 without logging in on 2.1.x
  ([R3](./known-regressions.md)).
- `agy` inside SSH sessions: the `asb-agy` wrapper unsets `SSH_CONNECTION`,
  `SSH_CLIENT` and `SSH_TTY`, which otherwise force a new device-auth flow.
