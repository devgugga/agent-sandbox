// Flattening, ordering and key derivation for the project tree (spec §9.2,
// §9.4). One shared module so `ProjectTree`, `AppShell`, `DetailPanel` and
// `CommandPalette` all walk the same structure the same way, instead of
// four independent traversals that could drift apart.
//
// `GET /api/tree` (`server/asb_server/models.py::tree_response`) does not
// sort — it walks `Snapshot.projects`/`checkouts`/`sessions` in whatever
// order the registry and Git returned them. The curses TUI's ordering
// comes entirely from `tui_model.build_tree`'s sort keys, applied at
// render time on the same unsorted data. The daemon response therefore
// carries no ordering guarantee of its own; `buildRows` below applies
// `build_tree`'s exact sort keys (project by primary path then id;
// checkout by kind-then-path-then-id, primary first; session by title
// then id; unregistered by path) so the web tree's on-screen order matches
// the TUI's regardless of what order the wire payload arrives in. This is
// a front-end-only fix for a daemon-side gap — see the task report.
import type { CheckoutNode, ProjectNode, SessionNode, UnregisteredNode } from "../types/tree";

export const projectKey = (id: string): string => `p:${id}`;
export const checkoutKey = (id: string): string => `c:${id}`;
export const sessionKey = (id: string): string => `s:${id}`;
export const unregisteredKey = (projectId: string, path: string): string =>
  `u:${projectId}:${path}`;
export const noteKey = (projectId: string): string => `n:${projectId}`;

/** `tui_model.build_tree`'s placeholder text for a project with neither
 * checkouts nor unregistered worktrees (`RowKind.NOTE`). */
export const NO_CHECKOUTS_LABEL = "(no checkouts)";

export type Row =
  | { kind: "project"; key: string; project: ProjectNode }
  | { kind: "checkout"; key: string; project: ProjectNode; checkout: CheckoutNode }
  | {
      kind: "session";
      key: string;
      project: ProjectNode;
      checkout: CheckoutNode;
      session: SessionNode;
    }
  | {
      kind: "unregistered";
      key: string;
      project: ProjectNode;
      unregistered: UnregisteredNode;
    }
  | { kind: "note"; key: string; project: ProjectNode };

/** Rows that fold/unfold; only these can appear in the collapsed set. */
export type FoldableRow = Extract<Row, { kind: "project" | "checkout" }>;

function cmp(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function sortedProjects(projects: readonly ProjectNode[]): ProjectNode[] {
  return [...projects].sort(
    (a, b) => cmp(a.primary_path, b.primary_path) || cmp(a.id, b.id),
  );
}

function sortedCheckouts(checkouts: readonly CheckoutNode[]): CheckoutNode[] {
  return [...checkouts].sort((a, b) => {
    const kindRank = (kind: CheckoutNode["kind"]) => (kind === "primary" ? 0 : 1);
    return (
      kindRank(a.kind) - kindRank(b.kind) ||
      cmp(a.path, b.path) ||
      cmp(a.id, b.id)
    );
  });
}

function sortedSessions(sessions: readonly SessionNode[]): SessionNode[] {
  return [...sessions].sort((a, b) => cmp(a.title, b.title) || cmp(a.id, b.id));
}

function sortedUnregistered(entries: readonly UnregisteredNode[]): UnregisteredNode[] {
  return [...entries].sort((a, b) => cmp(a.path, b.path));
}

/** Every row, in the TUI's display order, regardless of fold state. */
export function buildRows(projects: readonly ProjectNode[]): Row[] {
  const rows: Row[] = [];
  for (const project of sortedProjects(projects)) {
    rows.push({ kind: "project", key: projectKey(project.id), project });
    // `tui_model.build_tree`: a project with neither checkouts nor
    // unregistered worktrees gets a `(no checkouts)` placeholder row
    // instead of silently rendering as a childless project.
    if (project.checkouts.length === 0 && project.unregistered.length === 0) {
      rows.push({ kind: "note", key: noteKey(project.id), project });
      continue;
    }
    for (const checkout of sortedCheckouts(project.checkouts)) {
      rows.push({ kind: "checkout", key: checkoutKey(checkout.id), project, checkout });
      for (const session of sortedSessions(checkout.sessions)) {
        rows.push({
          kind: "session",
          key: sessionKey(session.id),
          project,
          checkout,
          session,
        });
      }
    }
    for (const unregistered of sortedUnregistered(project.unregistered)) {
      rows.push({
        kind: "unregistered",
        key: unregisteredKey(project.id, unregistered.path),
        project,
        unregistered,
      });
    }
  }
  return rows;
}

/** `rows` filtered to what a viewer sees given `collapsed` fold state. */
export function visibleRows(rows: readonly Row[], collapsed: ReadonlySet<string>): Row[] {
  return rows.filter((row) => {
    if (row.kind === "project") return true;
    if (collapsed.has(projectKey(row.project.id))) return false;
    if (row.kind === "session") return !collapsed.has(checkoutKey(row.checkout.id));
    return true; // checkout, unregistered: visible whenever their project is
  });
}

export function findRow(rows: readonly Row[], key: string | null): Row | null {
  if (key === null) return null;
  return rows.find((row) => row.key === key) ?? null;
}

export function isFoldable(row: Row): row is FoldableRow {
  return row.kind === "project" || row.kind === "checkout";
}

/** `TreeRow.selectable` (tui_model.py): every row kind except `NOTE`. */
export function isSelectable(row: Row): boolean {
  return row.kind !== "note";
}

/** Fold keys that must be unfolded for `row` to be visible in the tree —
 * used to expand ancestors when the command palette jumps to a node. */
export function ancestorKeys(row: Row): string[] {
  switch (row.kind) {
    case "project":
      return [];
    case "checkout":
    case "unregistered":
    case "note":
      return [projectKey(row.project.id)];
    case "session":
      return [projectKey(row.project.id), checkoutKey(row.checkout.id)];
  }
}
