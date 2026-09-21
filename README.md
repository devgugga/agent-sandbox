# agent-sandbox

An isolated execution environment for AI coding agents (Claude Code, OpenAI
Codex, Google Antigravity), built on rootless Podman and systemd.

## The problem

Running an AI coding agent directly on your machine means it can read your
SSH keys, your other projects, your shell history, and reach the open
internet with whatever credentials happen to be lying around. `agent-sandbox`
gives each agent its own workspace instead: its own container, its own
network namespace with an egress allowlist, its own SSH-published port, and
access only to the one project checkout it was started for. Credentials are
shared across workspaces through a single Secret Service singleton
(`asb-keyring`) that agent containers reach only as D-Bus clients — never as
holders of the underlying keyring data.

A workspace survives host reboots (everything is a systemd user unit), keeps
working across `agent-sandbox` checkout moves, and is torn down or purged
explicitly — never garbage-collected behind your back.

## Requirements

- Linux with a systemd **user** session (`systemctl --user`)
- Rootless Podman >= 4.0
- Python >= 3.11 (the CLI is pure standard library — nothing to `pip
  install`)
- `git`
- `jq`, only if you use the Orca integration scripts under `recipes/`

Check all of the above at once, plus everything else the sandbox needs, with:

```bash
cli/asb-agent doctor
```

Every failing line names the exact command to fix it.

## Getting started

The CLI runs straight from the checkout — no install step, no build
tooling of its own:

```bash
# 1. Build the base image (mirrors your host user/uid inside the container)
cli/asb-agent build

# 2. Put `asb-agent` (and the provider guards) on your PATH
cli/asb-agent install-guards

# 3. Log in to the providers you'll use (interactive device-auth;
#    run this from a real terminal, not a pipe or `ssh -T`)
asb-agent login

# 4. Bring up a workspace for a project checkout
asb-agent up --workspace demo --repo /path/to/your/project
```

`up` prints one JSON line (`workspace`, `port`, `user`, `project_root`)
once the workspace is actually reachable — SSH, the egress proxy and
`mise install` inside the container all have to succeed first. From there:

```bash
asb-agent connect --workspace demo   # SSH shell into the workspace
asb-agent suspend --workspace demo   # stop it, keep the files
asb-agent resume  --workspace demo   # bring it back
asb-agent down    --workspace demo   # remove containers/network, keep files
asb-agent purge   --workspace demo --yes   # remove the files too
```

## Commands

| Command | What it does |
| :--- | :--- |
| `build` | builds the base image, mirroring your host user |
| `login [--agent claude\|codex\|agy\|all]` | authenticates a provider, or all of them, once per machine |
| `auth status\|verify --workspace <id> [--agent ...] [--json]` | account status per provider; `verify` makes one real call to prove the server accepted the credential |
| `up --workspace <id> --repo <path>` | creates the network, clone, containers and systemd units; prints the connection |
| `suspend --workspace <id>` | stops the workspace and takes it out of the login auto-start |
| `resume --workspace <id>` | brings it back through systemd |
| `pull --workspace <id>` | fetches the workspace's branch into the primary checkout (no merge) |
| `connect --workspace <id>` | opens an SSH shell into a workspace that is already running |
| `reload-allowlist --workspace <id>` | re-renders the egress allowlist and restarts the proxy, without touching the agent |
| `down --workspace <id>` | removes containers and network; **keeps the workspace's files** |
| `purge --workspace <id> --yes` | removes the files too — irreversible |
| `doctor [--json]` | diagnoses the environment and names the exact fix for each problem |
| `list` | lists known workspaces and their status |
| `install-guards` | symlinks `asb-agent` and the provider guards (`asb-claude`, `asb-codex`, `asb-agy`) into `~/.local/bin` |
| `install-broker` | installs the read-only Docker API broker (requires `sudo`, opt-in) |
| `project add --repo <path> [--integration-branch <b>] [--worktree-root <dir>]` | registers a project and its primary checkout — never creates a workspace |
| `session list\|start\|attach\|stop\|resume` | persistent agent sessions (tmux inside the workspace), survive closing the terminal |
| `tui` | a terminal UI over projects, checkouts and sessions, with worktree creation and merge-back |

Run `cli/asb-agent <command> --help` for a command's exact flags — this table
matches `build_parser()` in `cli/asb-agent` at the time of writing, but that
file is the source of truth if the two ever disagree.

## Configuring a project

Each sandboxed project can carry an optional `.agent-sandbox.toml` at its
root: extra egress domains, host ports the agent may reach or publish,
whether it gets a nested rootless Podman of its own, and background service
containers (Postgres, Redis, ...). Every field defaults closed — an absent
file means no host access beyond the base allowlist. Full schema and worked
examples: [`docs/domains/sandbox/configuration.md`](./docs/domains/sandbox/configuration.md).

## Orca integration

`recipes/` holds the lifecycle hooks an external orchestrator (Orca) calls
to create, resume, suspend and destroy a workspace over SSH, plus
`shim.template.sh` for wiring them up. They are thin wrappers around
`cli/asb-agent up`/`resume`/`suspend`/`down` that print the one JSON line
Orca expects.

## If something's wrong

```bash
cli/asb-agent doctor
```

checks Podman, Python, git, the image, the credential/toolcache volumes,
the keyring service, leftover legacy `podman-restart` drop-ins, the
network wait unit, third-party producers of the rootless network
namespace at boot, the installed guards, host/image tool drift, and every
workspace's egress, and tells you the exact command to run for each thing
it finds. Account problems (logged out, provider errors) are diagnosed
separately with `asb-agent auth status`/`auth verify`, since a network or
infrastructure failure is never the same thing as being logged out.

## Testing

```bash
PYTHONPATH=cli python3 -m unittest discover -s tests/unit
PYTHONPATH=cli python3 -m unittest discover -s tests/integration   # needs real Podman
for t in tests/test-*.sh; do bash "$t"; done                       # needs real Podman + systemd
```

The shell suites under `tests/` (`test-lifecycle.sh`, `test-auth.sh`,
`test-network.sh`, `test-keyring-service.sh`, and more) exercise real
containers, volumes and systemd units end to end; the unit suite does not
touch any of them.

## Project layout and where to go next

```
cli/asb-agent          the host entry point
cli/asb/               the CLI's Python implementation
cli/asb-guard          the wrapper the provider guards run through
image/                 the sandbox and proxy container images
recipes/               Orca lifecycle hooks
profiles/              the provisioning profile every workspace is staged with
docs/domains/sandbox/  architecture, configuration, auth, security, failure modes
docs/architecture/     Graphify knowledge-graph reference
```

For anything past this quick tour:

- [`docs/domains/sandbox/README.md`](./docs/domains/sandbox/README.md) —
  the sandbox domain pack: system topology, container roles, filesystem
  layout, and what to do on failure.
- [`docs/domains/sandbox/lifecycle.md`](./docs/domains/sandbox/lifecycle.md)
  — the systemd runtime, command semantics, recovery, persistent agent
  sessions, the TUI, worktree creation and finish/cleanup.
- [`docs/domains/sandbox/authentication.md`](./docs/domains/sandbox/authentication.md)
  — how account, network and infrastructure problems are told apart.
- [`docs/domains/sandbox/security.md`](./docs/domains/sandbox/security.md) —
  the explicit security boundaries, and what the sandbox does not protect
  against.
- [`AGENTS.md`](./AGENTS.md) — engineering guidelines and workflow for
  anyone (human or AI agent) contributing to this repository.
