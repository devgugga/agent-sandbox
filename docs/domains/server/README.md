# Server Domain Pack

Single Source of Truth (SSoT) for `asb-server`, the FastAPI daemon behind
the `agent-sandbox` web interface, across all AI tools (Claude Code,
OpenAI Codex, Google Antigravity).

## Documentation Index

- [Conventions](./conventions.md): package layout, the worker-thread rule,
  the error model, authentication, how to add a route, how to regenerate
  the contract, and how to test with `create_app` and fixtures.

---

## 1. What the daemon is

`asb-server` is a small FastAPI process that reads the same project /
checkout / session tree the curses TUI (`asb-agent tui`) shows, and
serves it as JSON to a browser. It never mutates anything: there is no
route that starts a session, creates a worktree, or writes to the
registry — the interface is read-only end to end.

It reuses the TUI's own read path rather than a second implementation:
`cli/asb/interfaces/snapshot.py::read_snapshot` is the single function
both `TuiController.refresh` and the daemon call, so a project, checkout
or session shows the same way in both interfaces by construction, not by
convention.

## 2. Where it runs and how it's reached

- Binds `127.0.0.1` only, port `7420` by default (`ASB_SERVER_PORT` or
  `--port` to change it). There is no flag to bind anything else — see
  `conventions.md`'s auth section for why.
- Installed as a systemd **user** unit (`asb-server.service`) by
  `asb-agent install-server`, `Type=simple`, `Restart=on-failure`. The
  unit's `ExecStart` points at `<checkout>/.venv/bin/asb-server serve`;
  moving the checkout means re-running `install-server`, and
  `asb-agent doctor` detects the stale path.
- `asb-agent ui` is the front door: it checks `/api/health`, then opens
  `http://127.0.0.1:<port>/#token=<token>` in an app-mode browser window
  (falling back to `xdg-open`, then to just printing the URL). It never
  starts the daemon itself — if the unit is inactive, it names the
  `systemctl --user start` command and exits.
- `asb-agent doctor` carries the daemon's own checks: the binary exists,
  `web/dist/index.html` exists, the unit file and its `ExecStart` path
  exist, the unit is enabled and active, the token file is `0600`, and
  `/api/health` answers within 3 seconds. Each check is skipped, with a
  single informational line, on a host where the unit was never
  installed.

## 3. Package layout

```text
server/asb_server/
├── main.py       console entry: `asb-server serve [--port] [--dev] [--fixture PATH]`
│                 and `asb-server openapi`
├── app.py        create_app(settings, *, snapshot_reader) -> FastAPI
├── settings.py   host (fixed 127.0.0.1), port, token path, web dist path, dev origins
├── auth.py       token file, cookie session, Origin check
├── models.py     Pydantic response models: the wire contract
├── snapshot.py   SnapshotService: single-flight read on a worker thread
├── static.py     serves web/dist with SPA fallback for non-/api paths
└── api/
    ├── health.py
    ├── auth.py
    └── tree.py
```

`cli/asb/install.py` and `cli/asb/interfaces/ui.py` (outside `server/`)
own installing, starting and opening the daemon; they talk to it only
over HTTP or systemd, never by importing `asb_server` — see
`conventions.md` for why `cli/` cannot depend on it.

## 4. The API

| Method and path | Auth | Purpose |
| :--- | :--- | :--- |
| `GET /api/health` | none | `{version, started_at}`; polled by `asb-agent ui` and `doctor` before a session exists |
| `POST /api/auth/session` | Origin only | body `{token}`; on match sets the session cookie and returns 204; 401 otherwise |
| `GET /api/auth/me` | cookie | 204 when the cookie is valid; 401 otherwise |
| `GET /api/tree` | cookie | the full tree; 503 with `{detail}` only when the registry itself failed to read |

The wire shapes (`TreeResponse`, `ProjectNode`, `CheckoutNode`,
`SessionNode`, `UnregisteredNode`) are the Pydantic models in
`server/asb_server/models.py`; that file is the contract's source of
truth, and `web/src/api/schema.d.ts` is generated from it (see the web
pack).
