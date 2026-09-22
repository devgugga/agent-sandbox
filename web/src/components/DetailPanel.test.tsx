// `DetailPanel` for each node kind (spec §9.2, §9.4): full
// path, workspace, status/reason, branch and where it was read, sessions
// with state and timestamps.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DetailPanel } from "./DetailPanel";
import { healthyTreeFixture } from "../test/fixtures";
import type { Row } from "../lib/tree";
import type { ProjectNode } from "../types/tree";

function project(name: string): ProjectNode {
  const found = healthyTreeFixture.projects.find((p) => p.name === name);
  if (!found) throw new Error(`fixture project not found: ${name}`);
  return found;
}

function checkout(projectName: string, workspace: string) {
  const found = project(projectName).checkouts.find((c) => c.workspace === workspace);
  if (!found) throw new Error(`fixture checkout not found: ${projectName}/${workspace}`);
  return found;
}

const agentSandbox = project("agent-sandbox");
const docsSite = project("docs-site");
const primaryCheckout = checkout("agent-sandbox", "main"); // c-primary, with s-claude-review
const unavailableCheckout = checkout("agent-sandbox", "feature-x"); // host-read, has error
const session = primaryCheckout.sessions[0];
const unregistered = agentSandbox.unregistered[0];

/** The `dd` text for the field whose `dt` label is exactly `label`. */
function fieldValue(label: string): string | null {
  return screen.getByText(label, { selector: "dt" }).nextElementSibling?.textContent ?? null;
}

describe("DetailPanel", () => {
  it("shows a placeholder when nothing is selected", () => {
    render(<DetailPanel selection={null} />);
    expect(screen.getByLabelText("Details")).toHaveTextContent(/select a project/i);
  });

  it("shows project fields", () => {
    const selection: Row = { kind: "project", key: "p:x", project: agentSandbox };
    render(<DetailPanel selection={selection} />);

    expect(fieldValue("Project")).toBe("agent-sandbox");
    expect(fieldValue("Primary path")).toBe("/home/demo/agent-sandbox");
    expect(fieldValue("Integration branch")).toBe("main");
  });

  it("shows checkout fields: full path, workspace, status/reason, branch, and read-from", () => {
    const selection: Row = {
      kind: "checkout",
      key: "c:x",
      project: agentSandbox,
      checkout: unavailableCheckout,
    };
    render(<DetailPanel selection={selection} />);

    expect(fieldValue("Full path")).toBe("/home/demo/agent-sandbox-worktrees/feature-x");
    expect(fieldValue("Workspace")).toBe("feature-x");
    expect(fieldValue("Status")).toBe("unavailable: podman down");
    expect(fieldValue("Branch")).toBe("feature-x");
    expect(fieldValue("Error")).toBe("reconcile failed");
    // host_branch=false on this checkout: read from the sandbox.
    expect(fieldValue("Read from")).toBe("sandbox");
  });

  it("shows 'host' as the read-from location for a host-read checkout", () => {
    const selection: Row = {
      kind: "checkout",
      key: "c:docs",
      project: docsSite,
      checkout: docsSite.checkouts[0],
    };
    render(<DetailPanel selection={selection} />);
    expect(fieldValue("Read from")).toBe("host");
    expect(fieldValue("Branch")).toBe("(detached main) (host)");
  });

  it("shows session fields: agent, state, title and timestamps", () => {
    const selection: Row = {
      kind: "session",
      key: "s:x",
      project: agentSandbox,
      checkout: primaryCheckout,
      session,
    };
    render(<DetailPanel selection={selection} />);

    expect(fieldValue("Agent")).toBe("claude");
    expect(fieldValue("State")).toBe("running");
    expect(fieldValue("Title")).toBe("review PR #42");
    expect(fieldValue("Ended at")).toBe("—"); // ended_at is null
  });

  it("shows unregistered-worktree fields: path, branch, missing, prunable", () => {
    const selection: Row = {
      kind: "unregistered",
      key: "u:x",
      project: agentSandbox,
      unregistered,
    };
    render(<DetailPanel selection={selection} />);

    expect(fieldValue("Path")).toBe("/home/demo/agent-sandbox-worktrees/scratch");
    expect(fieldValue("Branch")).toBe("wip-scratch");
    expect(fieldValue("Missing")).toBe("no");
    expect(fieldValue("Prunable")).toBe("yes");
  });
});
