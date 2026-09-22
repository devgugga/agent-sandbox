# Server Conventions

Rules for working on `server/asb_server/`. Each rule that exists because
of a trap says what the trap is and, where one exists, names the test
that would catch a regression.

## 1. The daemon must never import `curses`

`cli/asb/interfaces/tui.py` does `import curses` at module level. The
daemon runs headless (as a systemd unit, with no controlling terminal),
so it must never import that module, directly or transitively — a
Python built without the `_curses` extension would then crash the daemon
at import time.

The daemon reads through `cli/asb/interfaces/snapshot.py` instead, which
is deliberately curses-free: `production_reader`
(`server/asb_server/snapshot.py`) composes
`asb.interfaces.sessions.session_services` and
`asb.interfaces.snapshot.default_checkouts` — never `tui.py`'s own
`default_checkouts`, which is a different function with the same name.

`server/tests/test_single_flight.py::TestDaemonNeverImportsCurses
.test_curses_never_gets_imported` proves this at runtime, in a separate
subprocess (a same-process check would depend on test execution order,
since other suites in the same `pytest` run do import `tui.py` and leave
`curses` in `sys.modules`): it imports every daemon module and asserts
`curses` never entered `sys.modules`. If you add an import to the daemon
that pulls in `tui.py`, this test fails.

## 2. `SnapshotService` is built eagerly in `create_app`

`app.state.snapshot_service = SnapshotService(snapshot_reader)` runs
inside `create_app`, synchronously, before the function returns — not
lazily inside a request dependency.

This is not a style preference. FastAPI resolves a plain `def`
dependency (as opposed to `async def`) via `run_in_threadpool`, so a
"build it on first use" version of that dependency runs on a *thread
pool thread*, once per request. Two `/api/tree` requests that both
arrive before either one has stored anything on `app.state` would each
observe nothing cached yet and each construct their own
`SnapshotService` — two independent single-flight instances, silently
defeating the one guarantee `SnapshotService` exists to provide, on
exactly the daemon's cold-start burst. Building the one shared instance
before any request can possibly exist removes the race window entirely.
`SnapshotService.__init__` only stores a reference (no I/O), so this
stays compatible with `asb-server openapi`'s side-effect-free contract
(§4 below).

`server/asb_server/api/tree.py::get_snapshot_service` is a pure accessor
for the same reason — it must read `request.app.state.snapshot_service`
back, never build one itself.

## 3. `SnapshotService`: worker thread, single-flight, no cache

A snapshot read runs Git, Podman and SSH per checkout and takes seconds.
`SnapshotService.read()`:

- Runs the reader on the event loop's default executor
  (`loop.run_in_executor(None, ...)`) — never on the event loop itself.
- Collapses concurrent callers: a caller that arrives while a read is
  already in flight awaits the *same* future and receives the *same*
  `read_at` timestamp, rather than triggering a second physical read. No
  lock is needed — the check-then-assign happens without an `await` in
  between, so nothing can interleave on the single-threaded event loop.
- Wraps the shared await in `asyncio.shield`. Without it, one caller's
  cancellation (a client disconnecting mid-request) would propagate into
  the task every other collapsed caller is waiting on, cancelling the
  read out from under all of them.
- Keeps no cache. Once the in-flight read completes, the next call starts
  a brand-new one — there is no background refresh and no polling. A
  refresh happens only when the operator asks for one, the same as the
  TUI's `r`.

## 4. Secrets: eager fail-fast at start, lazy everywhere else

Two `0600` files back authentication: `server-token` (posted once by
`asb-agent ui`) and `server-session-key` (signs the session cookie so a
session survives a daemon restart). Both live under the same
`~/.config/agent-sandbox/` convention `cli/asb/keyring.py` uses
(`ASB_CONFIG_ROOT`-aware).

- `create_app` never loads or creates either file. `asb-server openapi`
  calls `create_app` too, and must stay a pure, disk-write-free command —
  `pnpm check:api` diffs its output byte-for-byte (§5), so a command that
  wrote or read secrets as a side effect would be wrong at the wrong
  layer.
- `main.py::_serve` calls `AuthManager.load(settings)` eagerly, before
  `uvicorn.run`, purely to fail fast: a secret file with a mode looser
  than `0600` must refuse the daemon a port, not surface as a 500 on the
  first request.
- Every other consumer loads lazily, on the first request that needs it,
  through `auth.py::get_auth_manager`, which caches the result on
  `app.state`.
- Both files are created with `os.open(path, os.O_CREAT | os.O_EXCL |
  os.O_WRONLY, 0o600)` — the mode is set atomically at creation, not by a
  `chmod` afterward. Create-then-`chmod` leaves a window where the file
  is briefly observable at the process umask's mode; `os.open` with the
  mode argument does not.
- Every comparison against a secret — the token, the session signature —
  goes through `hmac.compare_digest`, never `==`, which is a timing
  oracle on the secret.

## 5. `asb-server openapi` must be byte-stable

`pnpm check:api` runs `uv run --project .. asb-server openapi` and diffs
it against the checked-in `web/src/api/schema.d.ts` (via
`openapi-typescript --check`). Two runs of `openapi` on the same checkout
must therefore produce byte-identical JSON:

- `main.py::_openapi` dumps with `sort_keys=True`, so no dict's insertion
  order leaks into the output.
- `HealthResponse`'s `version` and `started_at` are resolved once, at
  *import* time (`_VERSION` from package metadata, `_STARTED_AT` at
  process start) — never per request, and never from anything that
  varies between two invocations of the same checkout (no build
  timestamp, no git SHA).

To regenerate the contract after changing a route or a model: from
`web/`, run `pnpm gen:api` (writes `schema.d.ts`); `pnpm check:api` is
the read-only version CI (and the `asb-dev-stack` skill) runs to catch a
forgotten regeneration.

## 6. The error model

- A per-project or per-checkout failure is **data**, carried as an
  `error` field on that node (`ProjectNode.error`, `CheckoutNode.error`),
  never an HTTP error. One broken checkout must never hide the others —
  the response is still 200 with everything else intact.
- A registry failure (`Snapshot.registry_error` is set) is the one
  condition that becomes an HTTP error: `GET /api/tree` returns 503 with
  `{detail: <sanitized reason>}`.
- An unexpected exception becomes a generic 500 (`_unhandled_exception`
  in `app.py`); the traceback goes to the journal via `logger.exception`,
  never into the response body.
- One log line per request, to stdout (journald picks it up):
  `_log_requests` in `app.py` logs the method, the path (never the query
  string — a misbehaving client's secret could land there), the status
  code, and whatever the route stashed on `request.state.log_extra`.
  `api/tree.py` uses this to log `read_at` on every request, so two
  requests that collapsed onto the same physical read show the *same*
  `read_at` in the journal — that is how single-flight is observable from
  the log without a dedicated line for it.

## 7. Authentication rules

- The bind address (`127.0.0.1`) has no flag and no environment variable.
  It is fixed in `Settings`, never constructed from external input.
- Every route except `health` and `auth/session` requires the session
  cookie (`auth.py::require_session`).
- Every `POST` route (and, later, every WebSocket upgrade) additionally
  requires an `Origin` header equal to the daemon's own origin, or — only
  with `--dev` — the Vite dev origin (`http://localhost:5173`, fixed in
  `settings.py::DEV_ORIGIN`; nothing pins that number, it is Vite's own
  default). A missing or foreign origin is 403, which is deliberately
  distinct from 401 (missing/invalid cookie) — the two failures mean
  different things to a client.
- The token travels only in the POST body of `/api/auth/session` and in
  the URL fragment `asb-agent ui` opens once. A URL fragment is never
  sent in a request line, so it never reaches a server log. Nothing in
  this codebase puts it in a header, a query string, or a printed line
  next to other output.
- The session cookie is `HttpOnly`, `SameSite=Strict`, `Path=/`: its
  value is `<session id>.<hmac>`, verified with `AuthManager
  .verify_session_value` in constant time. Because the signing key is a
  file (not in-memory-only state), a session survives a daemon restart —
  a second `AuthManager.load` with the same key verifies the same
  cookie.

## 8. `static.py`: mount order matters, not just the guard

`static_api`'s catch-all route (`GET /{full_path:path}`) is included
**last** in `create_app`, after every `/api` router. Starlette matches
routes in registration order, so this ordering is what makes a concrete
route like `/api/tree` win over the catch-all in the first place.

The `full_path == "api" or full_path.startswith("api/")` guard inside
`static.py::spa` is a second, narrower safeguard: it only guarantees that
an *unmatched* `/api` path (one no `/api` router claims) 404s instead of
silently serving `index.html`. It does not make the mount order
irrelevant — if the catch-all were ever registered first, it would
intercept every `/api/...` request before an `/api` router saw it, and
this guard would turn each of them into a 404 too. That fails loudly
rather than silently serving HTML, but it still breaks the API. Keep the
`app.include_router(static_api)` call last.

When `web/dist` is missing entirely (front end never built), `/` and
every non-`/api` path answer 503 naming `asb-agent install-server`;
`/api/*` keeps working regardless, since `static.py`'s router never
claims an `/api` path either way.

## 9. `--fixture` is a testability hook, not a bypass

`asb-server serve --fixture <path.json>` (`snapshot.py::fixture_reader`)
swaps only *what* `create_app` reads. It changes nothing else: auth still
runs (`_serve` still calls `AuthManager.load` first), the bind address is
untouched, and secrets are not created any differently.

The path is parsed against `path.read_text()`, which resolves a relative
path against the daemon's **current working directory at launch** — not
the repository root. `server/fixtures/healthy-tree.json` only resolves
from a shell already `cd`'d into the repository root (or with an
absolute path); running `asb-server serve --fixture server/fixtures/...`
from `server/` itself would look for `server/server/fixtures/...` and
fail.

The fixture file must already have the wire `TreeResponse` shape (the far
side of `models.tree_response`'s conversion), not a `Snapshot`'s.
Reconstructing a `Snapshot` from that shape would be lossy —
`asb.projects.model.Project` needs fields (`worktree_root`,
`git_common_dir`) a `TreeResponse` never carries, and `ProjectNode.name`
is an independent field where production instead derives the name from
the primary checkout's last path segment. So `fixture_reader` bypasses
`tree_response`/`sanitize` for the healthy case and returns the parsed
`TreeResponse` as-is. The one shape that genuinely *is* a `Snapshot`
concept is `{"registry_error": "<reason>"}`, which drives the same 503
branch a real registry failure takes.

`server/fixtures/healthy-tree.json` and `server/fixtures/registry-
failure.json` are the two fixtures in the repository; the web test suite
loads the first one too (see the web pack), so a front-end label test and
the `--fixture` daemon exercise the same data rather than two
hand-maintained copies that could drift.

## 10. Sanitization: broader than "strip control characters"

Every operator- or Git-sourced string that reaches a response —
titles, branches, paths, reasons, errors, and the registry's own
free-text `workspace` field — passes through
`asb.interfaces.tui_model.sanitize` in `models.py`, even when the source
already looks clean. `sanitize` also strips bidi overrides and other
invisible formatting characters that neither a narrower control-character
filter nor React's own HTML escaping catches. Internally generated ids
and closed enum vocabularies (`kind`, `status`, `agent`, `state`) are not
operator text and are left as-is; the enum fields reuse `asb`'s own
`StrEnum`s rather than duplicating their literal values, so the
vocabulary has one definition, not two that can drift apart.

## 11. `cli/` cannot import `server/`

`cli/asb/install.py` (the `install-server`/`ui`/`doctor` support code)
duplicates the daemon's port-resolution logic (`server_port()`) rather
than importing `server/asb_server/settings.py::port_from_env`. This is
deliberate: `cli/` is standard-library-only so the guard scripts
(`asb-claude`, `asb-codex`, `asb-agy`) work without a virtual
environment, and importing `asb_server` would require one. `uv`, `node`
and `pnpm` are invoked from `cli/` as subprocesses, never imported as
libraries.

## 12. Adding a route

1. Add the Pydantic response model(s) to `models.py` (or extend an
   existing one), including any new error responses in the route's
   `responses=` mapping (`ErrorDetail`-shaped) — the generated client
   needs a typed shape for every non-2xx response it can see.
2. Add the route module under `api/`, following `health.py`/`tree.py`'s
   pattern: a router with a `prefix`, `Depends(require_session)` (and
   `Depends(require_origin)` for a `POST`) unless the route is
   deliberately unauthenticated like `health`.
3. Wire the router in `app.py::create_app`, before
   `app.include_router(static_api)` (§8).
4. Regenerate the contract from `web/`: `pnpm gen:api`.
5. Add tests under `server/tests/`, following §13 below.

## 13. Testing with `create_app` and fixtures

Every server test builds a real app with `create_app(settings,
snapshot_reader=...)` and drives it through `fastapi.testclient
.TestClient` — no route is tested by calling its function directly.

- `Settings` in a test always gets explicit `token_path`/`session_key_path`
  pointed at a temporary directory (`Path(self.enterContext(
  tempfile.TemporaryDirectory()))`); `CONFIG_ROOT` in `settings.py` is
  resolved once, at **import** time, from `ASB_CONFIG_ROOT` or `$HOME`,
  so setting the environment variable after the module has already been
  imported has no effect. Pass the paths into `Settings(...)` instead.
- A stub `snapshot_reader` (a plain function or lambda returning a
  `Snapshot`) replaces the real Git/Podman/SSH reads; nothing under
  `server/tests/` touches a real workspace.
- Several `server/tests/*.py` files share a basename with an unrelated
  file under `tests/unit/` (`test_auth.py`, `test_tree.py`,
  `test_single_flight.py`). This is intentional and works because
  `pyproject.toml` sets `--import-mode=importlib`, which does not require
  globally unique test module names the way the default "prepend" mode
  does.
- `TestDaemonNeverImportsCurses` (§1) and the single-flight proofs in
  `test_single_flight.py` run against a real, entered `TestClient` from
  two OS threads calling it concurrently — `TestClient` entered as a
  context manager keeps one `anyio` blocking portal running one event
  loop, so two threads calling `client.get(...)` on it really do submit
  concurrent requests onto the same loop, the same way two browser tabs
  would under `uvicorn`.
- To test against the fixture path instead of stubs directly, build the
  app with `snapshot_reader=fixture_reader(path)` exactly as
  `serve --fixture` does (`server/tests/test_static.py` does this over
  the two files in `server/fixtures/`).
