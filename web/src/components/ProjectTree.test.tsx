// `ProjectTree` renders the fixture with every label (spec §9.2, amendment
// §B/§H); keyboard navigation and folding (spec §9.3). Tested through what
// a user sees and types, never through component internals.
import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ProjectTree } from "./ProjectTree";
import { healthyTreeFixture } from "../test/fixtures";
import { sessionKey as makeSessionKey } from "../lib/tree";

/** A minimal controlled parent, exactly the state `AppShell` really holds
 * (collapsed set, selected key) — not a mock of `ProjectTree` itself. */
function Harness() {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  return (
    <ProjectTree
      projects={healthyTreeFixture.projects}
      collapsed={collapsed}
      selectedKey={selectedKey}
      onSelectRow={setSelectedKey}
      onToggleFold={(key) =>
        setCollapsed((prev) => {
          const next = new Set(prev);
          if (next.has(key)) {
            next.delete(key);
          } else {
            next.add(key);
          }
          return next;
        })
      }
    />
  );
}

describe("ProjectTree — labels", () => {
  it("renders all eight labels from spec §9.2 against the fixture", () => {
    render(<Harness />);

    expect(screen.getByText("merged / cleanup available")).toBeInTheDocument();
    expect(screen.getByText("merged / cleanup pending")).toBeInTheDocument();
    expect(screen.getAllByText("missing").length).toBeGreaterThan(0);
    expect(screen.getByText("unregistered")).toBeInTheDocument();
    expect(screen.getByText("prunable")).toBeInTheDocument();
    // `(host)` and `(detached …)` both come from the docs-site primary
    // checkout (detached=true, host_branch=true, branch="main"): one
    // combined string, asserted exactly rather than as two substrings.
    expect(screen.getByText("(detached main) (host)")).toBeInTheDocument();
    // `!! <error>`: once from a checkout error, once from a project error.
    expect(screen.getByText("!! reconcile failed")).toBeInTheDocument();
    expect(
      screen.getByText("!! discover failed: workspace root not found"),
    ).toBeInTheDocument();
  });

  it("shows 'missing' and the merged label together on the same row", () => {
    // c-merged-pending: missing=true AND merged=true — additive, not an
    // either/or (tui_model.py's `_checkout_text` appends both).
    render(<Harness />);
    const row = screen.getByText("merged / cleanup pending").closest("li")!;
    expect(within(row).getByText("missing")).toBeInTheDocument();
  });
});

describe("ProjectTree — folding", () => {
  it("collapses a project on click, hiding its checkouts", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    expect(screen.getByText("merged / cleanup available")).toBeInTheDocument();

    const projectRow = screen.getByText("agent-sandbox").closest("li")!;
    await user.click(within(projectRow).getByRole("button", { name: "Collapse" }));

    expect(screen.queryByText("merged / cleanup available")).not.toBeInTheDocument();
    expect(projectRow).toHaveAttribute("aria-expanded", "false");

    await user.click(within(projectRow).getByRole("button", { name: "Expand" }));
    expect(screen.getByText("merged / cleanup available")).toBeInTheDocument();
  });
});

describe("ProjectTree — keyboard navigation", () => {
  it("moves the selection with arrow keys and reverses with the opposite arrow", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    screen.getByRole("tree").focus();

    await user.keyboard("{ArrowDown}");
    const first = screen.getByRole("treeitem", { selected: true });
    await user.keyboard("{ArrowDown}");
    const second = screen.getByRole("treeitem", { selected: true });
    expect(second).not.toBe(first);

    await user.keyboard("{ArrowUp}");
    expect(screen.getByRole("treeitem", { selected: true })).toBe(first);
  });

  it("Enter folds/unfolds the selected project", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    screen.getByRole("tree").focus();

    await user.keyboard("{ArrowDown}");
    const projectRow = screen.getByRole("treeitem", { selected: true });
    expect(projectRow).toHaveTextContent("agent-sandbox");
    expect(projectRow).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{Enter}");
    expect(projectRow).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("merged / cleanup available")).not.toBeInTheDocument();

    await user.keyboard("{Enter}");
    expect(projectRow).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("merged / cleanup available")).toBeInTheDocument();
  });

  it("Enter on a session calls onSelectRow, not onToggleFold", async () => {
    const user = userEvent.setup();
    const onSelectRow = vi.fn();
    const onToggleFold = vi.fn();
    const key = makeSessionKey("s-claude-review");

    render(
      <ProjectTree
        projects={healthyTreeFixture.projects}
        collapsed={new Set()}
        selectedKey={key}
        onSelectRow={onSelectRow}
        onToggleFold={onToggleFold}
      />,
    );
    screen.getByRole("tree").focus();

    await user.keyboard("{Enter}");

    expect(onSelectRow).toHaveBeenCalledWith(key);
    expect(onToggleFold).not.toHaveBeenCalled();
  });
});
