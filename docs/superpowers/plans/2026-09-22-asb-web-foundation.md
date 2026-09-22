# Plan: Web interface foundation (item 1)

**Date:** 2026-09-22  
**Spec:** [`docs/superpowers/specs/2026-09-22-asb-web-foundation-design.md`](../specs/2026-09-22-asb-web-foundation-design.md)  
**Outcome:** Foundation packages (Python daemon, React front end), domain packs, skill, CI, piloted on the operator's host.

---

## Overview

This plan implements the 11 tasks of item 1 in dependency order, each adding a working piece. Every task uses TDD: write tests first, make them pass, then commit. The tasks build toward read-only parity with the curses TUI, authenticated with a token file, served on loopback.

---

## Task 1: Monorepo skeleton and workspace setup

**Objective:** Create the uv workspace structure, Python packages, and Node package.json; verify all tools present.

**Changes:**
- Convert `pyproject.toml` to uv workspace root (`package = false`).
- Create `pyproject.toml` in `cli/` for package `asb` (no new deps).
- Create `pyproject.toml` in `server/` for package `asb_server` (deps: fastapi, uvicorn[standard], asb; dev: pytest, httpx).
- Create `web/package.json` (private; react, vite, typescript, tailwindcss, @tanstack/react-query, openapi-fetch, openapi-typescript, vitest, @testing-library/react, @playwright/test).
- Create `web/pnpm-lock.yaml` (stub or placeholder).
- Update `.gitignore` to add `.venv/`, `web/dist/`, `server/.venv` if any.
- Create empty `server/tests/` and `web/tests/` directories.

**Tests:**
- `tests/unit/test_workspace.py`: `import asb`, `from asb_server import app`, verify cli/asb-agent still runs without venv, no cycle.

**Acceptance:**
- `uv --version`, `node --version`, `pnpm --version` all present on PATH.
- `uv sync --frozen` succeeds at repository root.
- `pnpm install --frozen-lockfile` succeeds in `web/`.
- No circular dependency warnings.

---

## Task 2: Snapshot extraction from TUI controller

**Objective:** Extract the logic of `TuiController.refresh` into a pure function `read_snapshot`, preserving behavior.

**Changes:**
- Create `cli/asb/interfaces/snapshot.py` with `Snapshot` dataclass and `read_snapshot()` function.
- Update `cli/asb/interfaces/tui.py`: `TuiController.refresh` calls `read_snapshot`, copies fields, rebuilds rows.
- Move logic from refresh body into snapshot.py following the spec (§6).

**Tests:**
- `tests/unit/test_snapshot.py`: snapshot with real fakes (existing TestCheckoutManager, TestSessionServices), registry failure, store failure, one project failing, one checkout missing, merged evidence.
- `tests/unit/test_tui_controller.py` runs unchanged and all pass (proof of extraction).

**Acceptance:**
- `uv run pytest tests/unit/test_snapshot.py tests/unit/test_tui_controller.py` all green.
- `read_snapshot` never raises for per-project or checkout failure; errors land in model.
- Registry failure reported through `registry_error`.

---

## Task 3: Daemon app foundation (FastAPI, settings, models)

**Objective:** Create the FastAPI app, settings module, Pydantic contract models, error handling.

**Changes:**
- Create `server/asb_server/settings.py`: host (127.0.0.1), port, token_path, web_dist_path, dev_origins.
- Create `server/asb_server/models.py`: TreeResponse, ProjectNode, CheckoutNode, SessionNode, UnregisteredNode per spec (§7.3).
- Create `server/asb_server/app.py`: `create_app(settings, *, snapshot_reader) -> FastAPI`.
- Create `server/asb_server/main.py`: console entry `asb-server serve` and `asb-server openapi`.
- Enforce one dependency direction: server imports asb; asb never imports asb_server.

**Tests:**
- `server/tests/test_models.py`: models serialize and deserialize correctly; all required fields present; Snapshot converts to TreeResponse.

**Acceptance:**
- `uv run pytest server/tests/test_models.py` passes.
- `asb-server openapi` outputs valid JSON schema.
- No import cycles.

---

## Task 4: Daemon authentication (token file, session cookie)

**Objective:** Implement authentication with token file and signed session cookie.

**Changes:**
- Create `server/asb_server/auth.py`: token file at `~/.config/agent-sandbox/server-token`, mode 0600, 32 random hex bytes.
- Session key file at `server-session-key`, same mode, persists across restarts.
- HMAC-signed session id in HttpOnly, SameSite=Strict, Path=/ cookie.
- Refuse daemon start if token file mode > 0600.
- `POST /api/auth/session` endpoint: body `{token}`, on match sets cookie and returns 204; 401 otherwise.
- `GET /api/auth/me` endpoint: 204 if cookie valid; 401 otherwise.
- Origin check: `POST` and future WebSocket routes require `Origin` header equal to daemon's origin (or Vite origin with `--dev`).

**Tests:**
- `server/tests/test_auth.py`: no cookie → 401; wrong token → 401; right token → cookie set and valid; `GET /api/auth/me` with and without cookie; `POST` with foreign `Origin` → 403; `--dev` accepts Vite origin; token file mode validation.

**Acceptance:**
- `uv run pytest server/tests/test_auth.py` passes.
- Token file created with mode 0600 on first start.
- Cookie signed and verified across daemon restarts.

---

## Task 5: Daemon API—health, tree, single-flight reader

**Objective:** Implement /api/health and /api/tree endpoints; single-flight snapshot reading on worker thread.

**Changes:**
- Create `server/asb_server/snapshot.py`: `SnapshotService` with single-flight reader on worker thread, no cache, no background refresh.
- `SnapshotService.read()` builds services fresh (like CLI does), runs `read_snapshot` on worker thread, returns same result to concurrent callers.
- Create `server/asb_server/api/health.py`: `GET /api/health` → `{version, started_at}`; no auth.
- Create `server/asb_server/api/auth.py`: POST and GET endpoints from task 4.
- Create `server/asb_server/api/tree.py`: `GET /api/tree` → full TreeResponse; requires cookie; 503 with `{detail}` only when `registry_error` is set.
- Per-project and checkout errors are data, never HTTP errors.
- Unexpected exceptions → 500 generic detail; traceback to journal only.

**Tests:**
- `server/tests/test_tree.py`: fixture snapshot serialized exactly with all error fields; registry failure → 503; one read invocation per request; concurrent requests receive same `read_at`.
- `server/tests/test_single_flight.py`: two concurrent requests yield one snapshot read; both get same result.
- `server/tests/test_health.py`: health answers before auth required; version and started_at present.

**Acceptance:**
- `uv run pytest server/tests/test_*.py` passes.
- Tree reads run on worker thread, never blocking FastAPI loop.
- Single-flight verified in logs or with mock reader.

---

## Task 6: Static serving and testability hooks

**Objective:** Serve the web frontend from /api; support fixture-based testing without real Git/Podman/SSH.

**Changes:**
- Create `server/asb_server/static.py`: serve `web/dist` with SPA fallback (/ and /anything → index.html; /api/* never fallback; missing dist → 503).
- Update `create_app` to mount static handler; add `snapshot_reader` parameter (dependency injection for testing).
- Support `asb-server serve --fixture <path.json>` flag: load TreeResponse from JSON, use it instead of real reader.
- Create fixture JSON file for testing (TreeResponse with example projects, checkouts, sessions, errors).
- `asb-server openapi` command outputs schema; byte-stable across runs.

**Tests:**
- `server/tests/test_static.py`: `/`, `/anything` → `index.html`; `/api/unknown` → 404 never index.html; missing dist → 503.
- `server/tests/test_openapi.py`: schema valid JSON; byte-stable across two runs.
- Create example fixture; daemon with `--fixture` serves it; tree endpoint returns fixture data.

**Acceptance:**
- `uv run pytest server/tests/test_static.py server/tests/test_openapi.py` passes.
- `asb-server serve --fixture <path>` starts and serves fixture without Git/Podman.
- Fixture verified in smoke e2e later (task 11).

---

## Task 7: CLI commands—install-server, ui, doctor

**Objective:** Add subcommands for installation, opening the interface, and diagnostics.

**Changes:**
- Create `cli/asb/commands/install.py`: `asb-agent install-server` (new subcommand).
  - Verify `uv`, `node`, `pnpm` present.
  - `uv sync --frozen` at repo root.
  - `pnpm install --frozen-lockfile` and `pnpm build` in `web/`.
  - Render systemd unit to `~/.config/systemd/user/asb-server.service` (ExecStart, Restart=on-failure, RestartSec=2, WantedBy=default.target).
  - `systemctl --user daemon-reload enable --now asb-server.service`.
  - Wait up to 10 s for `GET /api/health`; print URL.
  - Idempotent re-run.
- Create `cli/asb/commands/ui.py`: `asb-agent ui` subcommand.
  - Read port and token from config.
  - Check health; if unit inactive, say so and name command.
  - Open URL in app mode with first of chromium, google-chrome-stable, brave found; fallback to xdg-open.
  - `--print-url` prints instead of opening.
- Update `cli/asb/diagnostics/checks.py`: doctor checks (task 7 checks: unit file present, mode 0600, unit enabled and active, health answers).

**Tests:**
- `tests/unit/test_install_server.py`: unit rendering with escaped paths, idempotent re-run, each prerequisite failure names its fix; browser detection and fallback; doctor checks with fake filesystem and systemctl.

**Acceptance:**
- `uv run pytest tests/unit/test_install_server.py` passes.
- `asb-agent install-server --help` exists and describes steps.
- `asb-agent ui --print-url` prints the URL without opening.
- `doctor` lists all checks green after install; identifies stale unit path.

---

## Task 8: Web—React foundation, components, state management

**Objective:** Build the React/Vite app with components for tree, detail, and palette.

**Changes:**
- Create `web/src/` directory structure: `components/`, `hooks/`, `api/`, `types/`.
- Create `web/src/App.tsx`: main entry, `AuthGate`, `TopBar`, `ProjectTree`, `DetailPanel`, `ErrorBanner`, `CommandPalette`.
- Create `web/src/components/`:
  - `AuthGate.tsx`: token exchange, URL cleanup.
  - `TopBar.tsx`: refresh button, read-at time, in-progress indicator, stale marker.
  - `ProjectTree.tsx`, `CheckoutRow.tsx`, `SessionRow.tsx`: tree with fold state in localStorage.
  - `DetailPanel.tsx`: full path, workspace, status/reason, branch, sessions, timestamps per selected node.
  - `ErrorBanner.tsx`: registry 503, stale tree still visible.
  - `CommandPalette.tsx`: Ctrl+K filtering (project, checkout, session jump; refresh command).
- TanStack Query for server state (tree: loading, error, refetch).
- Tailwind v4, dark theme by default, prefers-color-scheme respected.
- No zustand, no router in item 1.

**Tests:**
- vitest + Testing Library: ProjectTree renders fixture with every label; keyboard nav and folding; AuthGate exchanges token and clears fragment; DetailPanel for each node kind; ErrorBanner on 503; CommandPalette filtering and jump.

**Acceptance:**
- `pnpm test` passes.
- All components render with fixture data.
- Keyboard navigation works (arrows, Enter, Ctrl+K).

---

## Task 9: Web—API client and TypeScript types

**Objective:** Generate and use typed OpenAPI client; connect tree query to daemon.

**Changes:**
- Create `web/src/api/schema.d.ts` (generated from daemon's OpenAPI; versioned in repo).
- Create `web/src/api/client.ts`: openapi-fetch client, type-safe wrappers for health, auth/session, auth/me, tree endpoints.
- Create `web/src/hooks/useTree.ts`: TanStack Query useQuery for /api/tree with refetch, error handling.
- Update components to use typed client: `useTree()` in ProjectTree; cookie set in AuthGate; health check in ui command.
- Add `web/pnpm gen:api` script: run `uv run asb-server openapi`, regenerate `schema.d.ts`.
- Add `web/pnpm check:api` script: regenerate to temp file, fail on diff.
- Update CI to run `pnpm check:api` and fail on contract drift.

**Tests:**
- `pnpm check:api` passes (contract stable).
- useTree hook returns loading/error/data states; refetch works.
- API methods match schema types exactly; tsc strict mode passes.

**Acceptance:**
- `pnpm test` passes; `tsc --noEmit` passes.
- `pnpm gen:api` produces byte-stable output.
- Client calls are fully typed; contract changes break tsc.

---

## Task 10: Domain packs and asb-dev-stack skill

**Objective:** Document daemon and web conventions; create the dev workflow skill.

**Changes:**
- Create `docs/domains/server/`:
  - `README.md`: what the daemon is, where it runs, how to reach it.
  - `conventions.md`: package layout, worker-thread rule, error model (§7.6), auth rules (§7.5), route addition, contract regeneration, testing with create_app and fixtures.
- Create `docs/domains/web/`:
  - `README.md`: React/Vite stack, components and file layout, TanStack Query, typed client, label vocabulary, testing with Testing Library and fixture daemon.
  - `conventions.md`: component structure, server state management, the Ctrl+K principle, testing patterns.
- Create `.claude/skills/asb-dev-stack/SKILL.md`:
  - `pnpm dev`: Vite on 5173, daemon on --dev mode.
  - `asb-dev verify`: run all checks as CI runs them (python lint, tests, web lint, tests, build, e2e; sync-skills check).
  - Points to the two domain packs for detailed rules.
- Run `node scripts/sync-skills.mjs` to generate `.agents/skills/` and `.codex/skills/` mirrors.

**Tests:**
- `node scripts/sync-skills.mjs --check` passes.
- Domain pack markdown is valid and references are consistent.

**Acceptance:**
- Domain packs explain the system without duplication.
- Skill mirrors in sync with source.
- `asb-dev verify` command exists and runs all checks.

---

## Task 11: CI, Playwright e2e, and piloted validation

**Objective:** Set up GitHub Actions CI and Playwright smoke test; pilot install-server and ui on the operator's host.

**Changes:**
- Create `.github/workflows/ci.yml`:
  - **python job:** `uv sync --frozen`, `uv run ruff check server`, `uv run pytest tests/unit server/tests`, `node scripts/sync-skills.mjs --check`.
  - **web job:** `uv sync --frozen`, `pnpm install --frozen-lockfile`, `pnpm check:api`, `pnpm lint`, `pnpm test`, `pnpm build`, `pnpm exec playwright install chromium`, `pnpm test:e2e`.
- Create `web/tests/e2e.spec.ts`: Playwright smoke test.
  - Start daemon with `--fixture <path>` serving `web/dist`.
  - Open URL with token fragment.
  - Verify tree visible (projects, checkouts, sessions match fixture).
  - Refresh button works; tree updates.
  - 503 banner appears on registry failure (fixture scenario).
- Create `docs/validation/2026-09-22-asb-web-foundation.md`:
  - Piloted on operator's host: `asb-agent install-server` run, unit enabled, health answers after re-login.
  - `asb-agent ui` opens app-mode window with tree from real workspace.
  - Same projects, checkouts, sessions as TUI; identical labels including errors.
  - Refresh works; stale marker appears.
  - Second browser tab without cookie gets 401 on /api/tree.
  - Token never in logs or response bodies.
  - Checklist format per existing validation docs.

**Tests:**
- `pnpm test:e2e` passes; Playwright installed.
- All CI jobs succeed on the branch.

**Acceptance (per spec §17):**
1. All test suites and checks pass; CI green.
2. CLI, guards, recipes unchanged on a host without uv or Node.
3. `asb-agent install-server` leaves unit enabled and active; health answers after logout/login.
4. `asb-agent ui` opens window with same tree as TUI; identical labels and errors.
5. Second tab without cookie gets 401; foreign `Origin` POST gets 403.
6. Concurrent refresh clicks produce one snapshot read (one log line).
7. Token never in journal or response bodies.

---

## Next steps

Once item 1 ships:
- **Item 2:** Terminal workbench (pty ↔ WebSocket bridge, start/stop sessions, pane tree).
- **Item 3:** Worktree creation and finish (removes curses TUI).
- **Item 4:** Live agent state (working/needs-you/done/idle from OSC title).
- **Item 7:** Provider usage sidebar (if prioritized early).
