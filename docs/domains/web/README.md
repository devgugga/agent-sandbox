# Web Domain Pack

Single Source of Truth (SSoT) for `web/`, the React front end for the
`agent-sandbox` daemon (`asb-server`), across all AI tools (Claude Code,
OpenAI Codex, Google Antigravity).

## Documentation Index

- [Conventions](./conventions.md): component structure, server state
  management, the command-palette principle, and testing patterns.

---

## 1. What it is

A single-page React application that shows the same project / checkout /
session tree the curses TUI (`asb-agent tui`) shows, read over HTTP from
`asb-server`. It is read-only: there is no button in this interface that
starts a session, creates a worktree, or writes to the registry — those
stay TUI (or future item) actions.

## 2. Stack

React 19, Vite, TypeScript `strict`, pnpm. Tailwind v4 for styling, dark
theme by default, `prefers-color-scheme` respected. TanStack Query owns
server state (loading, error, refetch) for the one query this interface
has. No router and no client-side state library beyond React's own —
both are for a later, larger interface, not this one. The API client is
`openapi-fetch`, typed from a generated `schema.d.ts` (see §4).

## 3. Screen

- **Top bar** (`TopBar`): a refresh button, the last successful read's
  timestamp, an in-progress indicator while a read is running, and a
  stale marker after a failed read.
- **Sidebar** (`ProjectTree`): the tree — project, then checkouts and
  unregistered worktrees, then sessions per checkout — with labels kept
  verbatim from the TUI (see `conventions.md` §1). Fold state persists in
  `localStorage`.
- **Detail panel** (`DetailPanel`): everything a tree row cannot hold for
  the selected node — full path, workspace id, status and reason, branch
  and where it was read from, session timestamps.
- **Error banner** (`ErrorBanner`): shown on a registry failure, without
  hiding the tree underneath it (§5 below).

## 4. File layout

```text
web/src/
├── api/
│   ├── client.ts     typed wrappers around the four endpoints (openapi-fetch)
│   └── schema.d.ts    generated from the daemon's OpenAPI schema — never hand-edited
├── components/        one file per component: App, AuthGate, TopBar,
│                       ProjectTree, CheckoutRow, SessionRow, DetailPanel,
│                       ErrorBanner, CommandPalette
├── hooks/              useTree (TanStack Query), useFold (localStorage)
├── lib/
│   ├── labels.ts       the label vocabulary shared with the TUI
│   └── tree.ts         row flattening, sort order, key derivation
├── types/tree.ts        type aliases over the generated schema
└── test/                fixtures.ts, setup.ts (Testing Library)
```

`api/schema.d.ts` is regenerated with `pnpm gen:api` (from `web/`, needs
`uv` since it shells out to `asb-server openapi`); `pnpm check:api` is the
read-only check that fails when someone changed a route or a model
without regenerating it.

## 5. Server state: TanStack Query, no cache beyond the query itself

`useTree` (`hooks/useTree.ts`) wraps `GET /api/tree` in a `useQuery` with
`refetchOnWindowFocus`, `refetchOnReconnect` and `retry` all disabled.
Refresh is something the operator asks for — a button or `Alt+R` — not
something that happens on a timer or a focus event, matching the
daemon's own single-flight-per-request-burst read (no background refresh
either).

`getTree` (`api/client.ts`) throws on a non-2xx response rather than
returning an error value, so TanStack Query's own behavior takes over: on
a failed fetch, `error` is set but `data` keeps the **last successfully
fetched tree**. `AppShell` (`components/App.tsx`) uses that: it never
clears the tree on a 503, it marks it stale (`isStale = error !== null &&
data !== undefined`) and keeps rendering it underneath the error banner.

## 6. The command-palette principle

Everything the interface can do is reachable through `Ctrl+K` (the
command palette); every keyboard shortcut beyond that is a convenience on
top, never the only way to reach an action. `Alt+R` refreshes; `Ctrl+R`
is left alone (it is the browser's own reload in app mode). `Alt+1..9`
and `Alt+N` are reserved and unbound in this interface — see
`conventions.md` §5 for what reserves them and why that matters here.

## 7. Testing

vitest + Testing Library, driven through what a user sees and types, not
through component internals. `web/src/test/fixtures.ts` loads
`server/fixtures/healthy-tree.json` — the same fixture the `--fixture`
daemon and a future end-to-end test use — so a component test and a real
fixture-backed daemon exercise identical data. See `conventions.md` §6
for the setup details that make this work.
