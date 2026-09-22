// `CommandPalette` filtering and jump (spec §9.3, §9.4): jump to a
// project, checkout or session, or run "refresh".
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CommandPalette } from "./CommandPalette";
import { healthyTreeFixture } from "../test/fixtures";

describe("CommandPalette", () => {
  it("lists every project, checkout and session, plus 'Refresh', unfiltered", () => {
    render(
      <CommandPalette
        projects={healthyTreeFixture.projects}
        onJump={vi.fn()}
        onRunRefresh={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("Refresh")).toBeInTheDocument();
    expect(screen.getByText("agent-sandbox")).toBeInTheDocument();
    expect(screen.getByText("agent-sandbox / main")).toBeInTheDocument();
    expect(screen.getByText("agent-sandbox / main / review PR #42")).toBeInTheDocument();
  });

  it("filters as the operator types", async () => {
    const user = userEvent.setup();
    render(
      <CommandPalette
        projects={healthyTreeFixture.projects}
        onJump={vi.fn()}
        onRunRefresh={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    await user.type(screen.getByPlaceholderText(/jump to/i), "docs-site");

    expect(screen.getByText("docs-site")).toBeInTheDocument();
    expect(screen.queryByText("agent-sandbox")).not.toBeInTheDocument();
    expect(screen.queryByText("Refresh")).not.toBeInTheDocument();
  });

  it("jumps to a matching row on click and closes", async () => {
    const user = userEvent.setup();
    const onJump = vi.fn();
    const onClose = vi.fn();

    render(
      <CommandPalette
        projects={healthyTreeFixture.projects}
        onJump={onJump}
        onRunRefresh={vi.fn()}
        onClose={onClose}
      />,
    );

    await user.click(screen.getByText(/review PR #42/));

    expect(onJump).toHaveBeenCalledTimes(1);
    expect(onJump.mock.calls[0][0]).toMatchObject({ kind: "session" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("runs refresh and closes when 'Refresh' is chosen via Enter", async () => {
    const user = userEvent.setup();
    const onRunRefresh = vi.fn();
    const onClose = vi.fn();

    render(
      <CommandPalette
        projects={healthyTreeFixture.projects}
        onJump={vi.fn()}
        onRunRefresh={onRunRefresh}
        onClose={onClose}
      />,
    );

    await user.type(screen.getByPlaceholderText(/jump to/i), "refresh");
    await user.keyboard("{Enter}");

    expect(onRunRefresh).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on Escape without jumping or refreshing", async () => {
    const user = userEvent.setup();
    const onJump = vi.fn();
    const onRunRefresh = vi.fn();
    const onClose = vi.fn();

    render(
      <CommandPalette
        projects={healthyTreeFixture.projects}
        onJump={onJump}
        onRunRefresh={onRunRefresh}
        onClose={onClose}
      />,
    );

    await user.click(screen.getByPlaceholderText(/jump to/i));
    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onJump).not.toHaveBeenCalled();
    expect(onRunRefresh).not.toHaveBeenCalled();
  });
});
