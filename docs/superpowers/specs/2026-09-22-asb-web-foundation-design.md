# Design: Web interface for agent-sandbox — program and foundation (item 1)

**Date:** 2026-09-22
**Status:** approved in brainstorming, pending written review
**Supersedes:** §8 (TUI technology) of
`2026-09-17-agent-sandbox-tui-design.md`. Everything else in that spec
(domain model, managers, drivers, session continuity, worktree creation,
finish and cleanup, security) stays in force and is consumed unchanged.

---

## 1. Context

`asb-agent tui` (curses, `cli/asb/interfaces/tui.py`) is a single tree of
projects, checkouts and sessions with manual refresh and one full-screen
tmux attach at a time. It was piloted and merged on 2026-09-21. The
operator uses Orca daily and wants the same daily-driver quality on top of
the sandbox: a fluid interface, several agent terminals visible at once,
live agent state, worktrees created from GitHub issues, diff review, and
the providers' remaining usage.

Orca is Electron + React with xterm.js terminals whose PTYs live in a
separate daemon. Reproducing that experience in a terminal UI was
evaluated and rejected: a per-worktree pane tree on top of tmux
(`break-pane`/`join-pane` juggling), nested tmux, and diff review in a
45-column sidebar are exactly the kind of code that is fragile to
maintain. A browser front end over a Python daemon is the medium where
every requested feature is natural, and the sandbox already owns the
property that makes it safe: every terminal is a tmux session inside the
workspace, so the daemon can restart at will without losing anything.

The "pure standard library" promise of the 2026-09-17 spec applied to that
plan only. The CLI, the guards, the recipes and `doctor` remain standard
library; the daemon and the front end are new packages with their own
dependencies.

---

## 2. Goals

The program as a whole:

- one interface, opened as an app window, that shows every project,
  checkout and session and lets the operator run agents and shells side by
  side per worktree;
- everything the curses TUI does, then more, without duplicating any rule
  that already lives in `asb`;
- a monorepo that a maintainer can hold in their head: three packages,
  one dependency direction, one generated contract, one command per
  check;
- every feature verified by tests that run without Podman wherever the
  feature allows it.

Item 1, this spec's deliverable:

- the monorepo skeleton (uv workspace, pnpm package), the daemon with
  authentication and a systemd user unit, the front end reading the tree,
  `asb-agent install-server`, `asb-agent ui`, `doctor` checks, the two
  domain packs, the `asb-dev-stack` skill and CI;
- read-only parity with the TUI tree: the interface shows what the TUI
  shows, with the same labels and the same per-node errors.

---

## 3. Non-goals

Item 1 does not include: terminals in the browser, starting or stopping
sessions, worktree creation or finish, live agent state, GitHub
integration, diff review, usage panels, keybinding remapping, or a Podman
based CI job. Each of those is a later item (§4). The program as a whole
does not include an embedded editor, an embedded browser, remote Git
actions, or a mobile client.

---

## 4. Program decomposition

Each item is its own spec, plan and execution, and each ships something
the operator uses the next day. Dependencies are listed; order within the
same dependency level is the operator's choice.

| Item | Deliverable | Depends on |
| :--- | :--- | :--- |
| 1 | **Foundation.** Monorepo, daemon, auth, unit, `install-server`, `ui`, `doctor`, tree read-only, domain packs, skill, CI. | — |
| 2 | **Terminal workbench.** `shell` session kind; start, stop and attach sessions from the interface; pty ↔ WebSocket ↔ xterm.js bridge; per-worktree pane tree with splits; persisted layout; automatic reconnection. Adds the `contract-drift-auditor` subagent. | 1 |
| 3 | **Worktrees on the web.** Create with preview, finish and cleanup with the explicit toggles, register a project. Reaches parity with the curses TUI, which is removed. Adds the `ui-flow-check` skill. | 2 |
| 4 | **Live agent state.** working / needs you / done / idle per session from the pane's OSC title and provider hooks; events over WebSocket; a dashboard summary. Introduces background refresh. | 2 |
| 5 | **GitHub issue → worktree.** Issue picker via `gh`, branch named from number and title, feeding item 3's create flow. | 3 |
| 6 | **Diff review.** Side-by-side diff of a worktree, line comments, "send to agent" into a chosen session. | 2, 4 |
| 7 | **Provider usage.** Remaining usage windows for Claude and Codex, probed inside a running workspace (never with a token on the host), `GET /api/usage`, a sidebar footer like Orca's. | 1 |

Every spec carries a fixed "Agents and skills" section (§14) stating what
that item adds under the repository's agent-authoring rules.

---

## 5. Repository layout and packaging

```text
agent-sandbox/
├── pyproject.toml            uv workspace root: members cli, server;
│                             package = false; pytest and ruff config
├── uv.lock                   versioned
├── cli/
│   ├── pyproject.toml        package `asb`; requires-python >= 3.11; no deps
│   ├── asb-agent, asb-guard  unchanged: still run from the checkout without a venv
│   └── asb/                  unchanged except §6
├── server/
│   ├── pyproject.toml        package `asb_server`; deps: fastapi, uvicorn[standard],
│   │                         asb (workspace source); dev: pytest, httpx;
│   │                         console script `asb-server`
│   ├── asb_server/
│   └── tests/
├── web/
│   ├── package.json          `asb-web`, private; react, vite, typescript, tailwindcss,
│   │                         @tanstack/react-query, openapi-fetch, openapi-typescript,
│   │                         vitest, @testing-library/react, @playwright/test
│   ├── pnpm-lock.yaml        versioned
│   ├── src/api/schema.d.ts   GENERATED from the daemon's OpenAPI, versioned
│   ├── src/
│   └── tests/
├── docs/domains/server/      new domain pack
├── docs/domains/web/         new domain pack
├── .claude/skills/asb-dev-stack/   new skill, mirrored by sync-skills.mjs
└── .github/workflows/ci.yml
```

Rules:

- **One dependency direction.** `server` imports `asb`. `asb` never
  imports `asb_server` and never learns the daemon exists. Guards,
  recipes and `doctor` never depend on uv, Node or the venv.
- **Packaging `cli/` serves the workspace, not the CLI.** `server` declares
  `asb` as a workspace dependency, so inside `.venv` `import asb` works
  without `PYTHONPATH`. `cli/asb-agent` keeps its `sys.path.insert` and
  runs exactly as before.
- **One Python test runner: pytest.** It discovers the existing
  `unittest.TestCase` suites unchanged. Canonical command:
  `uv run pytest tests/unit server/tests`. `tests/integration` and
  `tests/test-*.sh` keep their documented invocations.
- **One contract, generated and versioned.** `asb-server openapi` prints
  the schema. `pnpm gen:api` regenerates `web/src/api/schema.d.ts`;
  `pnpm check:api` regenerates into a temporary file and fails on any
  difference. Versioning the generated file makes a contract change
  visible in the same diff as the code change.
- **Build products live in the checkout and are ignored.** `.venv/`
  (already ignored) and `web/dist/` (added to `.gitignore`) are produced
  by `asb-agent install-server`.
- **Ruff is scoped to `server/`.** `cli/` is not reformatted.
- **Python floor stays 3.11** for both packages; the host today runs
  3.14 and `uv.lock` pins what was tested.

---

## 6. Snapshot extraction (the only change to existing code)

`TuiController.refresh` already computes everything the web needs
(projects, one `CheckoutView` per checkout with status, branch, kind,
`missing` and `merged`, the reconciled sessions, unregistered worktrees,
per-project errors), then stores it on the controller and flattens it
into text rows.

The body of `refresh` moves to `cli/asb/interfaces/snapshot.py`:

```python
@dataclass(frozen=True)
class Snapshot:
    projects: tuple[Project, ...]
    checkouts: tuple[CheckoutView, ...]
    sessions: tuple[AgentSession, ...]
    unregistered: tuple[UnregisteredView, ...]
    project_errors: Mapping[ProjectId, str]
    registry_error: str | None      # set when the registry itself failed

def read_snapshot(services: SessionServices, checkouts: CheckoutManager,
                  read_branch: Callable[[Path], BranchInfo | None]) -> Snapshot: ...
```

`TuiController.refresh` becomes: call `read_snapshot`, copy the fields,
rebuild rows. The existing `tests/unit/test_tui_controller.py` runs
unchanged and passing; that is the proof the extraction preserved
behavior. `read_snapshot` never raises for a per-project or per-checkout
failure (it lands in the model, as today's `!!`); only a registry failure
is reported through `registry_error`, matching the controller's current
early return. `read_branch` stays injectable for tests.

`tui_model.sanitize` is reused by the daemon when serializing (§7.3).

---

## 7. The daemon (`asb_server`)

### 7.1 Package layout

```text
server/asb_server/
├── main.py       console entry: `asb-server serve [--port] [--dev] [--fixture PATH]`
│                 and `asb-server openapi`
├── app.py        create_app(settings, *, snapshot_reader) -> FastAPI
├── settings.py   host (fixed 127.0.0.1), port, token path, web dist path, dev origins
├── auth.py       token file, cookie session, Origin check
├── models.py     Pydantic response models: the contract
├── snapshot.py   SnapshotService: single-flight read on a worker thread
├── static.py     serve web/dist with SPA fallback for non-/api paths
└── api/
    ├── health.py
    ├── auth.py
    └── tree.py
```

### 7.2 API (item 1)

| Method and path | Purpose |
| :--- | :--- |
| `GET /api/health` | `{version, started_at}`; no auth. Used by `asb-agent ui` and `doctor`. |
| `POST /api/auth/session` | body `{token}`; on match sets the session cookie and returns 204; 401 otherwise. |
| `GET /api/auth/me` | 204 when the cookie is valid; 401 otherwise. |
| `GET /api/tree` | the full tree (`TreeResponse`); 503 with `{detail}` only when `registry_error` is set. |

Every route except `health` and `auth/session` requires the cookie.
`POST` routes additionally require an `Origin` header equal to the
daemon's own origin (or, with `--dev`, the Vite origin). The same rule
will apply to WebSocket upgrades in item 2.

### 7.3 Contract (`models.py`)

```text
TreeResponse
  read_at: datetime
  projects: list[ProjectNode]
ProjectNode
  id, name, primary_path, integration_branch, error: str | None
  checkouts: list[CheckoutNode]
  unregistered: list[UnregisteredNode]
CheckoutNode
  id, kind (primary | worktree), path, workspace
  status (ready | absent | unavailable), reason: str | None
  branch: str | None, detached, host_branch, missing, merged, error: str | None
  sessions: list[SessionNode]
SessionNode
  id, agent (codex | claude | antigravity), state, title, cwd
  terminal_id: str | None, started_at, ended_at, last_healthy_at
UnregisteredNode
  path, branch: str | None, detached, missing, prunable
```

All operator- or Git-sourced strings (titles, branches, paths, reasons,
errors) pass through `tui_model.sanitize` when the node is built. React
escapes HTML; it does not neutralize bidi overrides or control
characters, and the contract must be clean for any future client.

### 7.4 Reading is slow and never blocks the loop

A snapshot runs Git, Podman and SSH per checkout and takes seconds.
`SnapshotService.read()` builds the services the same way the CLI does
(`interfaces.sessions.session_services()` and `tui.default_checkouts()`),
fresh on every read so a registry edited on disk is seen, runs
`read_snapshot` on a worker thread, and is single-flight: concurrent callers await the read already in progress and
receive its result. There is no cache and no background refresh in item 1
(parity with the TUI's `r`); item 4 introduces both.

### 7.5 Authentication

- Bind is `127.0.0.1` only, never configurable. Port default 7420,
  overridable by `--port` and `ASB_SERVER_PORT`.
- Token: 32 random bytes, hex, in `~/.config/agent-sandbox/server-token`
  (honors `ASB_CONFIG_ROOT` like `keyring.CONFIG`), created with mode
  `0600` on first start. A token file with a looser mode is refused at
  start with the exact `chmod` to run.
- `asb-agent ui` opens `http://127.0.0.1:<port>/#token=<token>` once. The
  front end posts it to `/api/auth/session`, receives an `HttpOnly`,
  `SameSite=Strict`, `Path=/` cookie carrying a signed session value, and
  replaces the URL fragment. The fragment is never sent to the server in a
  request line, so it never reaches logs.
- The cookie value is an HMAC-signed session id. The signing key is a
  second `0600` file next to the token (`server-session-key`), created the
  same way, so sessions survive daemon restarts. Rotating either is
  deleting the file and restarting the unit; no flag for it.

### 7.6 Errors

- A per-project or per-checkout failure is data (`error` fields), never
  an HTTP error: one broken checkout never hides the others.
- Registry failure → 503 with the sanitized reason; the front end shows a
  banner and keeps the last tree it had, marked stale.
- Unexpected exceptions → 500 with a generic detail; the traceback goes to
  the journal only.
- Logs: one line per request to stdout (journald), never including the
  token, the cookie, or provider output.

---

## 8. Installation, unit, `ui`, `doctor`

### 8.1 `asb-agent install-server`

New subcommand in the standard-library CLI (`cli/asb/install.py`). Steps,
each reported, each stopping the command on failure with the exact fix:

1. `uv --version`, `node --version`, `pnpm --version` present.
2. `uv sync --frozen` at the repository root.
3. `pnpm install --frozen-lockfile` and `pnpm build` in `web/`.
4. Render `~/.config/systemd/user/asb-server.service` through
   `supervisor.render_unit`-style helpers (atomic write, escaped
   arguments):
   `ExecStart=<checkout>/.venv/bin/asb-server serve`,
   `Restart=on-failure`, `RestartSec=2`, `WantedBy=default.target`.
5. `systemctl --user daemon-reload`, `enable --now asb-server.service`.
6. Wait up to 10 s for `GET /api/health`, then print the URL.

Re-running is idempotent. Moving the checkout requires re-running it;
`doctor` detects the stale `ExecStart`.

### 8.2 `asb-agent ui`

Reads the port and token, checks `health` (if the unit is inactive, says
so and names `systemctl --user start asb-server.service`), then opens the
URL in app mode with the first of `chromium`, `google-chrome-stable`,
`brave` found on `PATH` (`--app=<url>`), falling back to `xdg-open`.
`--print-url` prints the URL instead of opening anything.

### 8.3 `doctor`

New checks in `cli/asb/diagnostics/checks.py`, each a `CheckResult` with
the fix command:

- `.venv/bin/asb-server` exists → `asb-agent install-server`;
- `web/dist/index.html` exists → `asb-agent install-server`;
- unit file present and its `ExecStart` path exists → `asb-agent install-server`;
- unit enabled and active → `systemctl --user enable --now asb-server.service`;
- token file mode is `0600` → the `chmod`;
- `GET /api/health` answers within 3 s → `journalctl --user -u asb-server.service`.

All of them are skipped with a single informational line when the unit
was never installed, so `doctor` on a host that does not use the web
interface stays green.

---

## 9. The front end (`web/`)

### 9.1 Stack

React 19, Vite, TypeScript `strict`, pnpm. Tailwind v4 for styling, dark
theme by default with `prefers-color-scheme` respected; the visual
identity follows Orca's "monochrome and quiet" style guide as taste, not
as copied tokens. TanStack Query owns server state (the tree: loading,
error, refetch). No zustand and no router in item 1; both arrive with the
pane tree in item 2. The API client is `openapi-fetch` typed by the
generated `schema.d.ts`, so a contract change that the front end does not
follow fails `tsc`, not the user.

### 9.2 Screen

- **Top bar:** refresh button, "read at" time, an in-progress indicator
  while a read runs, the stale marker after a 503.
- **Sidebar (left):** the tree, project → checkouts → sessions, plus
  unregistered worktrees, with the TUI's labels kept verbatim:
  `merged / cleanup available`, `merged / cleanup pending`, `missing`,
  `unregistered`, `prunable`, `(host)`, `(detached …)`, `!! <error>`.
  Fold state per node persists in `localStorage`.
- **Detail panel (right):** everything a tree row cannot hold for the
  selected node: full path, workspace id, status and reason, branch and
  where it was read (sandbox or host), sessions with state and
  timestamps. This area becomes the terminal workbench in item 2.
- **Error banner** for the registry 503.

### 9.3 Keyboard

No inheritance from the TUI. Principle: everything is reachable through
the palette; shortcuts are a complement.

| Key | Action |
| :--- | :--- |
| `Ctrl+K` | command palette: jump to project, checkout or session; run "refresh" |
| arrows | move in the tree |
| Enter | fold or unfold a project or checkout; select a session |
| `Alt+R` | refresh (`Ctrl+R` is the browser's reload in app mode and is left alone) |

`Alt+1..9` (worktree jump) and `Alt+N` (new terminal) are reserved for
item 2. Remapping is a later item, when it hurts.

### 9.4 Components

`App`, `AuthGate` (token exchange and URL cleanup), `TopBar`,
`ProjectTree` with `CheckoutRow` and `SessionRow`, `DetailPanel`,
`ErrorBanner`, `CommandPalette`. One file per component under
`src/components/`, hooks under `src/hooks/`, the client under `src/api/`.

### 9.5 Development loop

`pnpm dev` runs Vite with `/api` proxied to the daemon; the daemon is
started with `uv run asb-server serve --dev`, which accepts the Vite
origin. Both commands live in the `asb-dev-stack` skill.

---

## 10. Testability hooks

`create_app` takes the snapshot reader as a dependency.
`asb-server serve --fixture <path.json>` builds the reader from a JSON
file with the `TreeResponse` shape, so a real daemon serving the real
`web/dist` can run anywhere without Podman, Git or SSH. This is the base
of the item 1 smoke e2e and of the `ui-flow-check` skill later.

---

## 11. Security

- The daemon listens on loopback only; there is no flag to change it.
- Every non-health route needs the session cookie; every mutation and
  every future WebSocket upgrade also needs a matching `Origin`. Together
  with `SameSite=Strict` this closes CSRF from any other tab or site
  against a daemon that will open terminals with credentials.
- The token appears only in the URL fragment `asb-agent ui` opens, never
  in a query string, a log line or a response body.
- No provider credential is ever read by the daemon (item 7 keeps that
  rule: usage is probed inside the workspace, and only numbers cross the
  boundary).
- The unit runs as the operator's user, like every other unit the sandbox
  installs; it needs nothing more.

---

## 12. Failure handling

| Situation | Behavior |
| :--- | :--- |
| Unit inactive when `asb-agent ui` runs | message with the `systemctl` command; nothing opened |
| Token file missing at daemon start | generated with `0600`; logged once |
| Token file mode too open | daemon refuses to start; log names the `chmod` |
| Registry unreadable | `GET /api/tree` → 503; UI banner + stale tree |
| One project's runtime discovery fails | `ProjectNode.error`; the other projects render |
| One checkout's SSH/Git read fails | `CheckoutNode.error`; the row renders with `!!` |
| Session store unreadable | every checkout carries the `sessions: …` error, as the TUI does today |
| `web/dist` missing | `/` answers 503 with "run asb-agent install-server"; `/api` still works |
| Browser binary not found | `xdg-open`; if that fails too, the URL is printed |

---

## 13. Test strategy

### 13.1 Python

- `tests/unit/test_snapshot.py`: `read_snapshot` with the fakes the
  controller tests already use; registry failure, store failure, one
  project failing discovery, one checkout missing, merged evidence.
- `tests/unit/test_tui_controller.py`: unchanged and passing (proof of
  extraction).
- `server/tests/test_auth.py`: no cookie → 401; wrong token → 401; right
  token → cookie set; `GET /api/auth/me` with and without cookie; `POST`
  with a foreign `Origin` → 403; `--dev` accepts the Vite origin.
- `server/tests/test_tree.py`: fixture snapshot serialized exactly,
  including every error field and every sanitized string; registry
  failure → 503.
- `server/tests/test_single_flight.py`: two concurrent requests, one
  reader invocation, both receive the same `read_at`.
- `server/tests/test_static.py`: `/`, `/anything` → `index.html`;
  `/api/unknown` → 404, never `index.html`; missing dist → 503.
- `server/tests/test_openapi.py`: the `openapi` command output is a valid
  schema and is byte-stable across two runs.
- `tests/unit/test_install_server.py`: unit rendering (escaped paths,
  `Restart`, `WantedBy`), idempotent re-run, each prerequisite failure
  naming its fix; `ui` browser selection and fallback; `doctor` checks
  with a fake filesystem and a fake `systemctl`.

### 13.2 Web

- vitest + Testing Library: `ProjectTree` renders the fixture with every
  label; keyboard navigation and folding; `AuthGate` exchanges the token
  and clears the fragment; `DetailPanel` for each node kind;
  `ErrorBanner` on 503 with the stale tree still visible;
  `CommandPalette` filtering and jump.
- One Playwright smoke e2e: daemon with `--fixture` serving `web/dist`,
  open with the token URL, tree visible, refresh works. Runs in CI with
  `playwright install chromium`.

### 13.3 Not automated

`install-server` end to end on the real host (unit installed, enabled,
health answering after a re-login) is a piloted step recorded in
`docs/validation/2026-09-22-asb-web-foundation.md`, in the format the
repository already uses.

---

## 14. Agents and skills

- **Domain pack `docs/domains/server/`:** `README.md` (what the daemon is,
  where it runs, how it is reached) and `conventions.md` (package layout,
  the worker-thread rule for anything that touches Git/Podman/SSH, the
  error model of §7.6, the auth rules of §7.5, how to add a route and
  regenerate the contract, how to test with `create_app` and fixtures).
- **Domain pack `docs/domains/web/`:** `README.md` and `conventions.md`
  (components and file layout, server state via TanStack Query, the typed
  client, the label vocabulary shared with the TUI, testing with Testing
  Library and the fixture daemon, the keyboard principle of §9.3).
- **Skill `asb-dev-stack`** (`.claude/skills/asb-dev-stack/SKILL.md`,
  mirrored by `node scripts/sync-skills.mjs`): start the daemon in dev,
  start Vite, regenerate the contract, run every check exactly as CI runs
  it. Thin: it points at the two domain packs for rules.
- No new subagent in item 1. `regression-sentinel`, `test-shape-auditor`
  and `claim-verifier` apply as they are to Python and TypeScript.

---

## 15. CI

`.github/workflows/ci.yml`, on push and pull request, two jobs:

- **python:** `uv sync --frozen`, `uv run ruff check server`,
  `uv run pytest tests/unit server/tests`, `node scripts/sync-skills.mjs --check`.
- **web:** `uv sync --frozen` (so `pnpm check:api` can run
  `asb-server openapi`), `pnpm install --frozen-lockfile`, `pnpm check:api`,
  `pnpm lint`, `pnpm test`, `pnpm build`, `pnpm exec playwright install chromium`,
  `pnpm test:e2e`.

`tests/integration` and `tests/test-*.sh` stay local (Podman rootless and
systemd user session); a Podman-capable job is a follow-up, not a
blocker.

---

## 16. Documentation touched

- `README.md`: the web interface section (install, open, requirements:
  uv, Node and pnpm, all optional and only for the interface).
- `docs/domains/sandbox/lifecycle.md` §6: the curses TUI is frozen (no
  new features) until item 3 removes it.
- `AGENTS.md` §2: nothing in item 1 (no new subagent); the two domain
  packs are listed in `docs/domains/README.md`.

---

## 17. Acceptance criteria

1. `uv run pytest tests/unit server/tests` passes; `pnpm test`,
   `pnpm test:e2e`, `pnpm check:api`, `pnpm build` and
   `node scripts/sync-skills.mjs --check` pass; CI is green on the branch.
2. `cli/asb-agent doctor`, guards and recipes behave exactly as before on
   a host without uv or Node.
3. `asb-agent install-server` on the operator's host leaves
   `asb-server.service` enabled and active; after logout and login the
   unit is active and `GET /api/health` answers.
4. `asb-agent ui` opens an app-mode window showing the same projects,
   checkouts and sessions as `asb-agent tui`, with identical labels,
   including a checkout with an error and an unregistered worktree.
5. A second browser tab without the cookie gets 401 on `/api/tree`; a
   `POST /api/auth/session` from a foreign origin gets 403.
6. Two simultaneous refresh clicks produce one snapshot read (visible in
   the journal as one log line).
7. The token never appears in the journal or in any response body.

---

## 18. Risks and follow-ups

- **Snapshot latency.** Seconds per read is acceptable for a manual
  refresh and is what the TUI does; item 4 owns background refresh and a
  cache.
- **Checkout moves** require `asb-agent install-server` again; `doctor`
  says so.
- **App-mode browser detection** is a `PATH` probe; a host with none of
  the three binaries falls back to `xdg-open`.
- **Podman-capable CI** for the integration and shell suites is a
  follow-up item of its own.
- **Item 7 sequencing:** it depends only on item 1 and can run before
  item 2 if the operator wants an early, visible result.
