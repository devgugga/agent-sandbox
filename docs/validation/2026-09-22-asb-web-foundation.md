# Web foundation — operator pilot checklist (NOT EXECUTED)

- **Plan:** `docs/superpowers/plans/2026-09-22-asb-web-foundation.md`, Task 11
- **Spec:** `docs/superpowers/specs/2026-09-22-asb-web-foundation-design.md`,
  §13.3 and §17
- **Status: NOT EXECUTED.** Every row below is **PENDING**. Nothing in this
  document has been run, observed, or otherwise verified by an agent or by
  any automated process. It is a checklist, not a report.
- **Who must run it:** the human operator, on their own host, because every
  scenario below needs things an agent in this environment does not have:
  a real `systemd --user` session to install and re-login against, a real
  browser window, and eyes to compare the rendered tree against
  `asb-agent tui` by inspection. See `.superpowers/sdd/2026-09-22-asb-web-foundation/task-11-amendments.md`
  §A.1 for why this pilot cannot be performed by the implementing agent.
- **What is already covered elsewhere, and is not this document's job:**
  `uv run pytest tests/unit server/tests` (1601 passed), the web unit/
  component suite (70 passed), and the Playwright smoke e2e
  (`web/tests/e2e.spec.ts`) are automated and their results belong in
  `.superpowers/sdd/2026-09-22-asb-web-foundation/task-11-report.md`, not
  here. This document exists only for spec §13.3's "not automated" step:
  `install-server` end to end on a real host.

## How to use this document

Work through the checklist in order. For each row, replace **PENDING**
under "Result" with **PASS** or **FAIL** plus a one-line observation, and
fill "Date / operator". Do not mark a row PASS without having performed
the action and looked at the actual output — a checkbox ticked from memory
or expectation defeats the only reason this document exists. If a row
fails, stop, record what happened, and open it as a defect rather than
continuing down the list.

## 0. Prerequisites

- [ ] `uv`, `node` and `pnpm` are on `PATH` (`uv --version`, `node --version`,
      `pnpm --version`).
- [ ] A real workspace exists with, at minimum: one checkout in an error
      state (e.g. `status=unavailable` with a `reason`, or a project-level
      discovery failure) and one unregistered worktree — §2 below needs
      both to compare labels against `asb-agent tui`. If the operator's
      current workspace has neither, create or find one before starting
      (do not fabricate labels in this document instead).
- [ ] `journalctl --user -u asb-server.service` is reachable (needed for
      §4 and §5's log inspection).

## 1. `install-server`, the unit, and health across a re-login (spec §17.3)

| # | Step | Expected | Result | Date / operator |
| :-- | :-- | :-- | :-- | :-- |
| 1.1 | Run `asb-agent install-server` from a clean checkout | Command completes; reports `uv sync`, `pnpm build`, unit render and `daemon-reload`/`enable --now`, each step named; prints the URL at the end | PENDING | |
| 1.2 | `systemctl --user status asb-server.service` | Unit is `enabled` and `active (running)` | PENDING | |
| 1.3 | `curl -s http://127.0.0.1:7420/api/health` (or the configured port) | 200, JSON body with `version` and `started_at` | PENDING | |
| 1.4 | Log out of the desktop session, then log back in | — (no assertion; this is the re-login the next row depends on) | PENDING | |
| 1.5 | After re-login, `systemctl --user status asb-server.service` | Still `active`, started by `default.target` without operator intervention | PENDING | |
| 1.6 | `curl -s http://127.0.0.1:7420/api/health` again | 200, same shape as 1.3 (a fresh `started_at` is expected if the unit restarted; that is not a failure by itself) | PENDING | |
| 1.7 | Re-run `asb-agent install-server` a second time | Idempotent: no error, no duplicate unit, ends in the same enabled/active state | PENDING | |

## 2. `asb-agent ui` vs. `asb-agent tui` (spec §17.4)

| # | Step | Expected | Result | Date / operator |
| :-- | :-- | :-- | :-- | :-- |
| 2.1 | Run `asb-agent tui` against the real workspace from §0; note every project, checkout and session row, including the error checkout and the unregistered worktree; quit | A reference snapshot of labels, written down or screenshotted for comparison below | PENDING | |
| 2.2 | Run `asb-agent ui` | An app-mode browser window opens automatically (or `asb-agent ui --print-url` prints a URL to open manually) | PENDING | |
| 2.3 | Compare the web tree against the §2.1 reference | Same projects, same checkouts, same sessions; every label matches verbatim, including the error checkout's `!! <error>` / `unavailable: <reason>` text and the unregistered worktree's `unregistered` (+ `prunable` if applicable) badges | PENDING | |
| 2.4 | Fold/unfold a project and a checkout in the web UI | Fold state persists across a page reload | PENDING | |

## 3. Session and origin enforcement (spec §17.5)

| # | Step | Expected | Result | Date / operator |
| :-- | :-- | :-- | :-- | :-- |
| 3.1 | Open a second browser tab at the daemon's origin, with no session cookie (e.g. a private/incognito window, or after clearing cookies for the origin) | Loading the app shows the "not signed in" state; a direct request confirms it: | PENDING | |
| 3.2 | From that second tab/window, `fetch('/api/tree')` (devtools console) or `curl` without the cookie | 401 | PENDING | |
| 3.3 | From an unrelated origin (e.g. `https://example.com` devtools console, or `curl -H "Origin: https://example.com"`), `POST /api/auth/session` with any token | 403 | PENDING | |

## 4. Concurrent refresh collapses to one read (spec §17.6)

| # | Step | Expected | Result | Date / operator |
| :-- | :-- | :-- | :-- | :-- |
| 4.1 | With the web UI open and authenticated, click Refresh twice in rapid succession (or trigger two near-simultaneous `GET /api/tree` requests) | Both requests succeed with the same `read_at` | PENDING | |
| 4.2 | `journalctl --user -u asb-server.service` for that window | Exactly **one** `GET /api/tree` log line's `read_at` is shared by both responses — i.e. one physical snapshot read served both, not two | PENDING | |

## 5. Token never leaks (spec §17.7)

| # | Step | Expected | Result | Date / operator |
| :-- | :-- | :-- | :-- | :-- |
| 5.1 | `journalctl --user -u asb-server.service \| grep -i <token>` (the real token from `~/.config/agent-sandbox/server-token`) | No match | PENDING | |
| 5.2 | Inspect the body of every `/api/*` response observed during §1–§4 (devtools Network tab) | The token string never appears in any response body | PENDING | |
| 5.3 | Confirm the URL bar no longer shows `#token=…` after the initial `asb-agent ui` open | Fragment is cleared (spec §7.5 / `AuthGate`) | PENDING | |

## 6. Guards, recipes and `doctor` unchanged without uv/Node (spec §17.2)

| # | Step | Expected | Result | Date / operator |
| :-- | :-- | :-- | :-- | :-- |
| 6.1 | On a host (or a shell with `PATH` scrubbed of `uv`/`node`/`pnpm`), run `asb-agent doctor` | Completes; the web-interface checks report a single informational "skipped, unit never installed" (or equivalent) line rather than erroring | PENDING | |
| 6.2 | On the same host, exercise a guard or a recipe (`recipes/*.sh` lifecycle hook, or any `asb-agent up`/`resume`/`suspend`/`down`) | Behaves exactly as before this plan — no dependency on `asb_server`, `uv`, or Node surfaces | PENDING | |

## Sign-off

- [ ] All rows above are PASS.
- [ ] Any FAIL rows have linked defect reports.
- **Overall result:** PENDING — not yet run.
