# Authentication Architecture

This document describes authentication workflows and credential management within `agent-sandbox`.

## Overview

AI coding agents (`claude`, `codex`, `gemini`) require authentication credentials to communicate with upstream provider APIs. Because `agent-sandbox` runs ephemeral containers per workspace, credentials must be baked into a derivative image named `agent-sandbox-auth` rather than passed via host home mounts or manual re-authentication.

## Device Auth vs Browser Callback

The CLI subcommands use device auth flows:

- `claude /login`
- `codex login --device-auth`
- `gemini auth`

### Why Device Auth is Mandatory

Standard OAuth browser flows attempt to open a local HTTP listener on a loopback port in the container and direct the host browser to `http://localhost:<callback-port>`. In container environments without host port forward mapping for arbitrary callback listeners, the browser cannot reach the callback server, causing authentication to hang indefinitely.

The device-code authentication flow provides a URL and a short alphanumeric code to enter on another device or host browser, completing authentication out-of-band via the provider's API.

## Credentials Persistence

All agent CLI credentials are saved under the unprivileged `agent` user home directory (`/home/agent`), ensuring that:
1. File permissions match the runtime user (`agent`, uid 1000).
2. Host user home directory (`$HOME`) is never mounted into the container.
3. The derivative image `agent-sandbox-auth` commits `/home/agent` with all auth tokens.

## Build and Commit Process

Running:

```bash
./cli/agent-sandbox auth
```

1. Starts an interactive helper container from `agent-sandbox-base`.
2. Prompts the human operator to complete device-auth commands in another terminal.
3. Asserts authentication status by checking exit codes (never regex-matching strings like `"logged in"`).
4. Commits container state to `agent-sandbox-auth` with the entrypoint explicitly reset to `/usr/local/bin/entrypoint.sh`.
