# Sandbox Troubleshooting & Ecosystem Guide

This document captures operational lessons, edge cases, and ecosystem-specific configurations discovered during testing and hardening of `agent-sandbox`.

## 1. OpenSSH Environment Variable Propagation

### Symptom
When running commands over SSH (e.g. `ssh agent@127.0.0.1 'echo $HTTPS_PROXY'`), environment variables set on the container (such as `HTTPS_PROXY` or `GEMINI_SANDBOX`) were empty.

### Cause
OpenSSH scrubs parent process environment variables when creating a session for an authenticated user. Variables passed to `podman run -e ...` belong to the `sshd` daemon process and are not automatically passed to user shell sessions.

### Resolution
In `image/entrypoint.sh`, relevant variables (`HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY`, `GEMINI_SANDBOX`, `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`, `PATH`) are written to `/etc/environment` (loaded by PAM `pam_env.so`) and `/etc/profile.d/agent-sandbox.sh` (sourced by login shells).

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
When `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` is set, Claude Code expects `/usr/bin/bwrap` to be present on the system.

### Resolution
`bubblewrap` is pre-installed in `image/Containerfile`. For non-interactive invocations (such as `-p "..."`), redirecting stdin from `/dev/null` (`< /dev/null`) prevents Claude from pausing to wait for standard input.

## 5. Network Package Registries

### Ecosystem Requirements
- **Node / npm**: Requires `registry.npmjs.org` in `image/squid/allowlist-base.txt` or project `.agent-sandbox.toml`.
- **Python**: Requires `pypi.org` and `files.pythonhosted.org`.
- **Java / Maven**: Requires `repo.maven.apache.org`.
