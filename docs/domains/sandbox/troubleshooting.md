# Sandbox Troubleshooting & Ecosystem Guide

This document captures operational lessons, edge cases, and ecosystem-specific configurations discovered during testing and hardening of `agent-sandbox`.

## 1. OpenSSH Environment Variable Propagation

### Symptom
When running commands over SSH (e.g. `ssh agent@127.0.0.1 'echo $HTTPS_PROXY'`), environment variables set on the container (such as `HTTPS_PROXY` or `GEMINI_SANDBOX`) were empty.

### Cause
OpenSSH scrubs parent process environment variables when creating a session for an authenticated user. Variables passed to `podman run -e ...` belong to the `sshd` daemon process and are not automatically passed to user shell sessions.

### Resolution
In `image/entrypoint.sh`, relevant variables (`HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY`, `PATH`) are written to `/etc/environment` (loaded by PAM `pam_env.so`) and `/etc/profile.d/agent-sandbox.sh` (sourced by login shells).

## 2. Squid ACL Redundancy Rules (`dstdomain`)

### Symptom
Squid failed to start with:
```
ERROR: '.github.com' is a subdomain of 'github.com'
FATAL: Bungled /etc/squid/squid.conf line ...
```

### Cause
In Squid configuration, `.domain.com` matches `domain.com` and all subdomains. Declaring both `.domain.com` and `domain.com` in the same `dstdomain` ACL triggers a fatal configuration error.

### Resolution
`cli/lib/render_squid.py` includes a `normalize_domains` function that prunes redundant child and exact duplicate entries when merging the base allowlist with project-specific rules.

## 3. Temporary Configuration File Permissions

### Symptom
Squid exited immediately with:
```
FATAL: Unable to open configuration file: /etc/squid/squid.conf: (13) Permission denied
```

### Cause
`mktemp` creates temporary files on the host with `0600` permissions. Squid runs inside the container as an unprivileged user (uid 900) and cannot read the mounted volume.

### Resolution
`cli/lib/pod.sh` explicitly applies `chmod 0644 "$squidconf"` prior to mounting the configuration file into the Squid container.

## 4. Claude Code Subprocess Isolation & Bubblewrap

### Symptom
Running `claude` failed with:
```
error: bubblewrap is required for subprocess env scrubbing and isolation. Install with: sudo apt-get install -y bubblewrap...
```

### Cause
## Never set `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` in the image

It came from the original spec, where it protected subprocesses **on the host**.
Inside the container it protects nothing — the container is already the boundary
— and Claude Code responds to it by **forcing the permission mode to default**,
which cancels the `--dangerously-skip-permissions` that Orca applies.

The symptom is a banner at startup:

```
Permission mode forced to default — CLAUDE_CODE_SUBPROCESS_ENV_SCRUB is set
```

The sandbox exists to make autonomous mode safe. A hardening flag that silently
disables autonomous mode defeats the purpose, and it went unnoticed because no
test asserted the agent's effective permission mode.

### Resolution
`bubblewrap` is pre-installed in `image/Containerfile`. For non-interactive invocations (such as `-p "..."`), redirecting stdin from `/dev/null` (`< /dev/null`) prevents Claude from pausing to wait for standard input.

## 5. Network Package Registries

### Ecosystem Requirements
- **Node / npm**: Requires `registry.npmjs.org` in `image/squid/allowlist-base.txt` or project `.agent-sandbox.toml`.
- **Python**: Requires `pypi.org` and `files.pythonhosted.org`.
- **Java / Maven**: Requires `repo.maven.apache.org`.

---

# Failure Modes Learned in Production

Each entry below was a real failure. They are recorded because the symptom
rarely points at the cause.

## Firewall silently absent

**Symptom:** everything appears blocked, tests pass, no isolation exists.
**Cause:** the init container ran as root under `keep-id`, `nft` returned
`Operation not permitted`, and the ruleset never applied.
**Check:** `podman run --rm --pod <pod> --user 1000 --cap-add NET_ADMIN
agent-sandbox-net nft list ruleset` must show the `inet asb` table.

## `Error: requires at least 1 arg(s), only received 0`

**Cause:** a comment placed in the middle of a command with line continuations.
In bash the `#` ends the logical line together with the backslash, so the
remaining arguments — including the image name — are orphaned.
**Why it is dangerous:** `bash -n` accepts it. The whole test suite stays green
and the failure only appears at runtime. **Never** put a comment between
continued lines.

## Pods leaking after `destroy`

**Symptom:** `orca vm recipe doctor --provision` reports
`Destroy action ran successfully` while a pod keeps running.
**Cause:** the workspace name was derived from `$$`, which `destroy` cannot
reproduce. Names are now derived deterministically from the repository path.
**Related:** inside an Orca session `ORCA_WORKSPACE_ID` is a worktree id
(`<uuid>::/path`) containing `:` and `/`; it must be sanitized, never used raw.

## Agent cannot write to its workspace

**Cause:** missing `--userns=keep-id` — see [Architecture](./architecture.md).
**Check:** `stat -c %u /home/agent/workspace` inside the container must return
`1000`, not `0`.

## Recipe does not appear in the picker

Two independent causes, in order of likelihood:

1. **Settings → Experimental → "Cloud VM"** is disabled. Without it the
   **Run on** selector is not rendered at all.
2. `orca.yaml` is not committed on the project's **primary branch**. An
   untracked file does not count, even though `doctor` validates it fine from
   the working copy.

## False greens in security assertions

A negative assertion ("X is blocked") passes for free when the container never
came up: the command fails and the test concludes "blocked". Every blocking
assertion must be paired with a positive control — `require` in
`tests/assert.sh` aborts the suite when the environment does not respond, rather
than reporting green.

The same class of error bites when parsing command output. `dig +short` writes
its errors to **stdout**, so matching "any output" reports a DNS leak that does
not exist. Match the shape of a real answer, not the presence of text.

## Sandbox came back after a reboot with no isolation

**Symptom.** After the machine restarts, the Orca workspace fails to connect;
starting the pod by hand brings the agent up but Squid is dead. Inside the
sandbox, `curl https://example.com` returns 200 and DNS resolves.

**Cause.** Two failures at once: the pod's network namespace is recreated on
every start (losing the nftables ruleset), and the Squid config used to be
written with `mktemp` into `/tmp`, which is tmpfs and is erased by the reboot.
`podman pod start` fails on Squid only and starts the agent regardless.

**Resolution.** `agent-sandbox resume --workspace <id>`, which applies the
firewall before any user container and verifies it applied. Install
`agent-sandbox install-autostart` so the boot path is automatic — Orca marks the
runtime `running` in its own registry and never re-runs `create` after a reboot.
Full account: [lifecycle.md](./lifecycle.md).
