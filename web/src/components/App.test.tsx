// `AppShell` integration tests: the 503 path (spec §7.6, §9.2) and the
// keyboard shortcuts that are not scoped to a single component
// (spec §9.3). Mocked at the network boundary, exactly like
// Task 9a's `useTree.test.tsx` — this exercises the real `useTree` hook
// through a real `QueryClientProvider`, not a mock of it.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { healthyTreeFixture } from "../test/fixtures";

let mockFetch: ReturnType<typeof vi.fn>;
let AppShell: typeof import("./App").AppShell;

beforeEach(async () => {
  vi.resetModules();
  mockFetch = vi.fn();
  vi.stubGlobal("fetch", mockFetch);
  ({ AppShell } = await import("./App"));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient();
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

function renderApp() {
  return render(<AppShell />, { wrapper });
}

async function loadInitialTree() {
  mockFetch.mockResolvedValueOnce(jsonResponse(200, healthyTreeFixture));
  renderApp();
  await waitFor(() => expect(screen.getByText("agent-sandbox")).toBeInTheDocument());
}

describe("AppShell — the 503 path keeps the stale tree", () => {
  it("keeps the last tree on screen, marked stale, alongside the error banner", async () => {
    await loadInitialTree();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    mockFetch.mockResolvedValueOnce(jsonResponse(503, { detail: "registry read failed" }));
    await userEvent.setup().click(screen.getByRole("button", { name: "Refresh" }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

    // Not a spinner, not an empty state, not a cleared tree: the tree that
    // was already on screen — including its labels — stays exactly where
    // it was, and the top bar marks it stale.
    expect(screen.getByText("agent-sandbox")).toBeInTheDocument();
    expect(screen.getByText("merged / cleanup available")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/registry unavailable/i);
    expect(screen.getByText("stale")).toBeInTheDocument();
  });
});

describe("AppShell — keyboard shortcuts (spec §9.3)", () => {
  it("Ctrl+K opens the command palette", async () => {
    await loadInitialTree();
    await userEvent.setup().keyboard("{Control>}k{/Control}");
    expect(screen.getByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
  });

  it("Alt+R triggers a refresh", async () => {
    await loadInitialTree();
    mockFetch.mockResolvedValueOnce(jsonResponse(200, healthyTreeFixture));

    await userEvent.setup().keyboard("{Alt>}r{/Alt}");

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
  });

  it("does not bind Ctrl+R, Alt+1 or Alt+N (browser reload / reserved for item 2)", async () => {
    await loadInitialTree();
    const user = userEvent.setup();

    await user.keyboard("{Control>}r{/Control}");
    await user.keyboard("{Alt>}1{/Alt}");
    await user.keyboard("{Alt>}n{/Alt}");

    // No refetch beyond the initial load, and the palette never opened.
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("Ctrl+K, filtering, and Enter jumps to a session and shows it in the detail panel", async () => {
    await loadInitialTree();
    const user = userEvent.setup();

    await user.keyboard("{Control>}k{/Control}");
    await user.type(screen.getByPlaceholderText(/jump to/i), "review PR");
    await user.keyboard("{Enter}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Details")).toHaveTextContent("review PR #42");
  });
});
