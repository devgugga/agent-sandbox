// Row ordering and the "(no checkouts)" placeholder (`tui_model.py`'s
// `build_tree`, lines ~205-212), against small synthetic fixtures rather
// than the full `healthy-tree.json` — each case isolates exactly one sort
// key or tie-break so a regression (e.g. an inverted `kindRank`) points at
// the right rule instead of a wall of unrelated fixture data.
import { describe, expect, it } from "vitest";
import { buildRows, checkoutKey, noteKey, projectKey, sessionKey, type Row } from "./tree";
import type { CheckoutNode, ProjectNode, SessionNode, UnregisteredNode } from "../types/tree";

function project(overrides: Partial<ProjectNode> & { id: string }): ProjectNode {
  return {
    name: overrides.id,
    primary_path: `/home/demo/${overrides.id}`,
    integration_branch: "main",
    error: null,
    checkouts: [],
    unregistered: [],
    ...overrides,
  };
}

function checkout(overrides: Partial<CheckoutNode> & { id: string }): CheckoutNode {
  return {
    kind: "worktree",
    path: `/home/demo/${overrides.id}`,
    workspace: overrides.id,
    status: "ready",
    reason: null,
    branch: "main",
    detached: false,
    host_branch: false,
    missing: false,
    merged: false,
    error: null,
    sessions: [],
    ...overrides,
  };
}

function session(overrides: Partial<SessionNode> & { id: string }): SessionNode {
  return {
    agent: "claude",
    state: "running",
    title: overrides.id,
    cwd: "/home/demo",
    terminal_id: null,
    started_at: null,
    ended_at: null,
    last_healthy_at: null,
    ...overrides,
  };
}

function unregistered(overrides: Partial<UnregisteredNode> & { path: string }): UnregisteredNode {
  return {
    branch: null,
    detached: false,
    missing: false,
    prunable: false,
    ...overrides,
  };
}

/** Row keys in order, for terse assertions on ordering. */
function keysOf(rows: readonly Row[]): string[] {
  return rows.map((row) => row.key);
}

describe("buildRows — project ordering", () => {
  it("orders projects by (primary_path, id), not input order", () => {
    const projects = [
      project({ id: "zeta", primary_path: "/home/demo/zeta" }),
      project({ id: "alpha", primary_path: "/home/demo/alpha" }),
      project({ id: "mid", primary_path: "/home/demo/mid" }),
    ];

    const rows = buildRows(projects);

    expect(keysOf(rows)).toEqual([
      projectKey("alpha"),
      noteKey("alpha"),
      projectKey("mid"),
      noteKey("mid"),
      projectKey("zeta"),
      noteKey("zeta"),
    ]);
  });

  it("breaks a tied primary_path by id", () => {
    const projects = [
      project({ id: "b", primary_path: "/home/demo/same" }),
      project({ id: "a", primary_path: "/home/demo/same" }),
    ];

    const rows = buildRows(projects);

    expect(keysOf(rows)).toEqual([
      projectKey("a"),
      noteKey("a"),
      projectKey("b"),
      noteKey("b"),
    ]);
  });
});

describe("buildRows — checkout ordering", () => {
  it("puts the primary checkout before worktree checkouts regardless of path", () => {
    // The worktree's path sorts before the primary's — proves the kind
    // rank wins the comparison, not a path tie-break.
    const proj = project({
      id: "p1",
      checkouts: [
        checkout({ id: "c-worktree", kind: "worktree", path: "/aaa-first" }),
        checkout({ id: "c-primary", kind: "primary", path: "/zzz-last" }),
      ],
    });

    const rows = buildRows([proj]);

    expect(keysOf(rows)).toEqual([
      projectKey("p1"),
      checkoutKey("c-primary"),
      checkoutKey("c-worktree"),
    ]);
  });

  it("breaks a tie between two worktrees by (path, id)", () => {
    const proj = project({
      id: "p1",
      checkouts: [
        checkout({ id: "c-z", kind: "worktree", path: "/home/demo/zeta" }),
        checkout({ id: "c-a", kind: "worktree", path: "/home/demo/alpha" }),
      ],
    });

    const rows = buildRows([proj]);

    expect(keysOf(rows)).toEqual([
      projectKey("p1"),
      checkoutKey("c-a"),
      checkoutKey("c-z"),
    ]);
  });

  it("breaks a same-path tie by checkout id", () => {
    const proj = project({
      id: "p1",
      checkouts: [
        checkout({ id: "c-b", kind: "worktree", path: "/home/demo/same" }),
        checkout({ id: "c-a", kind: "worktree", path: "/home/demo/same" }),
      ],
    });

    const rows = buildRows([proj]);

    expect(keysOf(rows)).toEqual([
      projectKey("p1"),
      checkoutKey("c-a"),
      checkoutKey("c-b"),
    ]);
  });
});

describe("buildRows — session ordering", () => {
  it("orders sessions within a checkout by (title, id)", () => {
    const proj = project({
      id: "p1",
      checkouts: [
        checkout({
          id: "c1",
          sessions: [
            session({ id: "s-z", title: "zeta task" }),
            session({ id: "s-a", title: "alpha task" }),
          ],
        }),
      ],
    });

    const rows = buildRows([proj]);

    expect(keysOf(rows)).toEqual([
      projectKey("p1"),
      checkoutKey("c1"),
      sessionKey("s-a"),
      sessionKey("s-z"),
    ]);
  });

  it("breaks a tied title by session id", () => {
    const proj = project({
      id: "p1",
      checkouts: [
        checkout({
          id: "c1",
          sessions: [
            session({ id: "s-b", title: "same title" }),
            session({ id: "s-a", title: "same title" }),
          ],
        }),
      ],
    });

    const rows = buildRows([proj]);

    expect(keysOf(rows)).toEqual([
      projectKey("p1"),
      checkoutKey("c1"),
      sessionKey("s-a"),
      sessionKey("s-b"),
    ]);
  });
});

describe("buildRows — unregistered ordering", () => {
  it("orders unregistered worktrees by path", () => {
    const proj = project({
      id: "p1",
      unregistered: [
        unregistered({ path: "/home/demo/zeta" }),
        unregistered({ path: "/home/demo/alpha" }),
      ],
    });

    const rows = buildRows([proj]);

    expect(rows.map((row) => (row.kind === "unregistered" ? row.unregistered.path : null))).toEqual([
      null, // the project row
      "/home/demo/alpha",
      "/home/demo/zeta",
    ]);
  });
});

describe("buildRows — the '(no checkouts)' placeholder", () => {
  it("emits it for a project with neither checkouts nor unregistered worktrees", () => {
    const proj = project({ id: "empty" });

    const rows = buildRows([proj]);

    expect(rows).toHaveLength(2);
    expect(rows[1]).toMatchObject({ kind: "note", key: noteKey("empty") });
  });

  it("does not emit it when the project has a checkout", () => {
    const proj = project({ id: "p1", checkouts: [checkout({ id: "c1" })] });
    const rows = buildRows([proj]);
    expect(rows.some((row) => row.kind === "note")).toBe(false);
  });

  it("does not emit it when the project has only an unregistered worktree", () => {
    const proj = project({
      id: "p1",
      unregistered: [unregistered({ path: "/home/demo/scratch" })],
    });
    const rows = buildRows([proj]);
    expect(rows.some((row) => row.kind === "note")).toBe(false);
  });
});
