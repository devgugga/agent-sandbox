// Exercises the real hook (`useTree` -> `getTree` -> `openapi-fetch`) against
// a faked `global.fetch` — the network boundary — via `@testing-library/react`'s
// `renderHook`, not by mocking `../api/client` itself.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as ClientModule from "../api/client";

let mockFetch: ReturnType<typeof vi.fn>;
let client: typeof ClientModule;
let useTree: typeof import("./useTree").useTree;

beforeEach(async () => {
  vi.resetModules();
  mockFetch = vi.fn();
  vi.stubGlobal("fetch", mockFetch);
  client = await import("../api/client");
  ({ useTree } = await import("./useTree"));
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
  // A plain, default QueryClient — no `retry: false` override here. `useTree`
  // itself must disable retries (see useTree.ts); this proves that, rather
  // than proving something only the test harness provides.
  const queryClient = new QueryClient();
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useTree", () => {
  it("starts loading, then returns the tree on success", async () => {
    const tree = { read_at: "2026-09-22T00:00:00Z", projects: [] };
    mockFetch.mockResolvedValueOnce(jsonResponse(200, tree));

    const { result } = renderHook(() => useTree(), { wrapper });

    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(tree);
    expect(result.current.error).toBeNull();
  });

  it("surfaces a typed error on 401 without ever having had data", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(401, { detail: "Missing or invalid session cookie." }));

    const { result } = renderHook(() => useTree(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error).toBeInstanceOf(client.UnauthorizedError);
    expect(result.current.data).toBeUndefined();
  });

  it("keeps the last tree, marked stale via `error`, after a 503 on refetch", async () => {
    const tree = { read_at: "2026-09-22T00:00:00Z", projects: [] };
    mockFetch.mockResolvedValueOnce(jsonResponse(200, tree));

    const { result } = renderHook(() => useTree(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(tree);

    mockFetch.mockResolvedValueOnce(jsonResponse(503, { detail: "registry read failed" }));
    result.current.refetch();

    await waitFor(() => expect(result.current.isError).toBe(true));

    // The shape Task 8 depends on: the stale tree is still there, alongside
    // a typed error a caller can branch on.
    expect(result.current.data).toEqual(tree);
    expect(result.current.error).toBeInstanceOf(client.ServiceUnavailableError);
  });
});
