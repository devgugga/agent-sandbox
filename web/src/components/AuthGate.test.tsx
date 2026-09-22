// `AuthGate` exchanges the token and clears the fragment (spec §7.5,
// amendment §E/§H). Mocked at the network boundary (`global.fetch`), like
// Task 9a's own client tests — never by mocking `../api/client` itself.
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let mockFetch: ReturnType<typeof vi.fn>;
let AuthGate: typeof import("./AuthGate").AuthGate;

beforeEach(async () => {
  vi.resetModules();
  mockFetch = vi.fn();
  vi.stubGlobal("fetch", mockFetch);
  ({ AuthGate } = await import("./AuthGate"));
  window.history.replaceState(null, "", "/");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function noContentResponse(status: number): Response {
  return new Response(null, { status });
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("AuthGate — token in the URL fragment", () => {
  it("exchanges the token, then clears the fragment and renders children", async () => {
    window.location.hash = "#token=secret-token";
    mockFetch.mockResolvedValueOnce(noContentResponse(204));

    render(
      <AuthGate>
        <div>authenticated content</div>
      </AuthGate>,
    );

    await waitFor(() => expect(screen.getByText("authenticated content")).toBeInTheDocument());

    // The fragment never lingers, success or failure (amendment §E).
    expect(window.location.hash).toBe("");

    const [request] = mockFetch.mock.calls[0] as [Request];
    expect(request.method).toBe("POST");
    expect(request.url).not.toContain("secret-token");
    await expect(request.clone().json()).resolves.toEqual({ token: "secret-token" });
  });

  it("clears the fragment even when the exchange fails", async () => {
    window.location.hash = "#token=wrong-token";
    mockFetch.mockResolvedValueOnce(jsonResponse(401, { detail: "Token did not match." }));

    render(
      <AuthGate>
        <div>authenticated content</div>
      </AuthGate>,
    );

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

    expect(window.location.hash).toBe("");
    expect(screen.queryByText("authenticated content")).not.toBeInTheDocument();
  });
});

describe("AuthGate — no token in the URL", () => {
  it("renders children when the existing session cookie is still valid", async () => {
    mockFetch.mockResolvedValueOnce(noContentResponse(204)); // GET /api/auth/me

    render(
      <AuthGate>
        <div>authenticated content</div>
      </AuthGate>,
    );

    await waitFor(() => expect(screen.getByText("authenticated content")).toBeInTheDocument());
    const [request] = mockFetch.mock.calls[0] as [Request];
    expect(request.url).toContain("/api/auth/me");
  });

  it("shows an error when there is no valid session", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(401, { detail: "Missing or invalid session cookie." }));

    render(
      <AuthGate>
        <div>authenticated content</div>
      </AuthGate>,
    );

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.queryByText("authenticated content")).not.toBeInTheDocument();
  });
});
