# Web Conventions

Rules for working on `web/`. Each rule that exists because of a trap says
what the trap is and, where one exists, names the test that would catch a
regression.

## 1. The label vocabulary is copied, not shared, with the TUI

`web/src/lib/labels.ts` reproduces the exact strings
`cli/asb/interfaces/tui_model.py` produces (`_branch_label`,
`_status_label`, `_checkout_text`, `_unregistered_text`):
`merged / cleanup available`, `merged / cleanup pending`, `missing`,
`unregistered`, `prunable`, `(host)`, `(detached …)`, `!! <error>`.

`tui_model.py` is the source of truth for this vocabulary. The two files
are **not mechanically linked** — nothing regenerates `labels.ts` from
`tui_model.py`, and nothing fails a build when they drift. If you change
a label in one, change it in the other by hand, and update
`ProjectTree.test.tsx`'s "renders all eight labels" test, which asserts
every one of them against the shared fixture
(`server/fixtures/healthy-tree.json`).

A checkout's `missing` flag and its merged label are independent: a
checkout can be both `missing` and `merged / cleanup pending` at once
(`mergedLabel` in `labels.ts` returns only the merged half; the caller
renders `missing` separately whenever `checkout.missing` is true,
regardless of `merged`).

## 2. Row ordering is a front-end responsibility

`GET /api/tree` does not sort. `models.py::tree_response` walks
`Snapshot.projects`/`checkouts`/`sessions` in whatever order the registry
and Git returned them — the daemon carries no ordering guarantee of its
own.

Ordering lives in the view layer in this repository, the same way it
does in the curses TUI: `tui_model.build_tree` applies its sort keys at
render time over the same unsorted data. `web/src/lib/tree.ts::buildRows`
applies the identical keys on the web side, so the on-screen order
matches the TUI's regardless of what order the wire payload arrives in:

- project: primary path, then id
- checkout: primary before worktree, then path, then id
- session: title, then id
- unregistered worktree: path

`buildRows`, `ProjectTree`, `DetailPanel` and `CommandPalette` all walk
this one structure rather than four independent traversals that could
order things differently from each other.

## 3. Sorting uses raw comparisons, not `localeCompare`

`tree.ts::cmp` compares strings with plain `<`/`>`, never
`String.prototype.localeCompare`. Python's `sorted()` — what
`tui_model.build_tree` uses — is code-point ordering; `localeCompare`
applies locale-aware collation, which orders punctuation, case and
non-ASCII characters differently. Using `localeCompare` here would make
the web tree's order diverge from the TUI's on exactly the paths and
branch names most likely to contain the characters where the two
orderings disagree.

## 4. Server state: `useTree` never intercepts errors

See the web README §5 for the mechanism. The rule to preserve: `useTree`
must not catch, transform, or swallow `getTree`'s thrown errors — it
passes them straight to TanStack Query so `data` (the last good tree) and
`error` (the latest failure) stay independent. A version of `useTree`
that caught the error to, say, return `null` on failure would silently
make `AppShell`'s "keep the last tree, mark it stale" behavior
impossible, because the last tree would already be gone.

## 5. The command-palette principle and reserved keys

Every reachable action is reachable through `Ctrl+K`
(`components/CommandPalette.tsx`); keyboard shortcuts are a convenience
layered on top, never a second, exclusive path to something the palette
cannot also do. This interface takes **no** keybindings from the curses
TUI — `j`/`k`/`n`/`w`/`f`/`d` mean nothing here.

- `Ctrl+K` and `Alt+R` are handled in `App.tsx`, above the tree, since
  neither is scoped to one component.
- Arrow keys and `Enter` are handled inside `ProjectTree.tsx` itself:
  arrows move the selection among currently visible (unfolded,
  selectable) rows; `Enter` folds/unfolds a project or checkout, or
  confirms a session/unregistered-worktree row as the selection.
- `Ctrl+R` is deliberately unbound — it is the browser's own reload in
  app mode, and no handler in this codebase intercepts it.
- `Alt+1..9` (worktree jump) and `Alt+N` (new terminal) are **reserved
  and unbound**. A future terminal-workbench pane owns them; binding them
  to anything else now would have to be un-bound later, breaking whoever
  learned the new binding in between.

## 6. Testing with Testing Library and the fixture daemon

- `vite.config.ts`'s `test.include` is scoped to `src/**/*.{test,spec}
  .{ts,tsx}` — Playwright specs live under `web/tests/` with their own
  `playwright.config.ts`, and vitest's default include pattern would
  otherwise also try to collect those.
- `test/setup.ts` registers Testing Library's `cleanup()` in an
  `afterEach` by hand. `vite.config.ts`'s `test` block does not set
  `globals: true`, so Testing Library's own auto-cleanup — which only
  fires when it finds a *global* `afterEach` — never runs on its own;
  without this file, one test's rendered DOM leaks into the next.
- `test/fixtures.ts` loads `server/fixtures/healthy-tree.json` with
  plain `node:fs.readFileSync`, resolved against `process.cwd()` — never
  a Vite import specifier (`?raw` or similar). `web/` is its own
  Vite/pnpm project root and its dev-server module graph refuses to
  serve or transform any path outside it; a runtime `readFileSync` never
  asks Vite to resolve the path as a module, so that boundary does not
  apply. `process.cwd()` is used rather than `import.meta.url` because
  under Vitest's transform, `import.meta.url` for a test-adjacent module
  is not reliably a `file:` URL.
- Components are tested through a minimal controlled harness that holds
  the same state `AppShell` really holds (a `collapsed` set, a
  `selectedKey`), not through a mock of the component under test —
  `ProjectTree.test.tsx`'s `Harness` is the pattern to copy.
- `api/client.ts` reads `window.location.origin` at module load, so it
  is browser/jsdom-only; every test that imports it (directly or via a
  component) needs the `jsdom` environment `vite.config.ts` already sets
  as the default. A test file that opted into `environment: "node"`
  would fail to import this module at all.
- `useFold`'s `localStorage` persistence is the **only** thing this
  application puts in browser storage — the session lives in the
  `HttpOnly` cookie the daemon sets (server pack §7), never in
  `localStorage` or `sessionStorage`. Don't add a second thing there
  without a reason as deliberate as fold state's.
