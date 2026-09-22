// Exercises the real client code (request building, status branching, error
// parsing) against a faked `global.fetch` — the network boundary — never
// against a mock of the wrapper functions themselves.
//
// `client.ts` calls `createClient()` once at module load, capturing
// whatever `globalThis.fetch` is at that moment. Each test therefore stubs
// `fetch` and re-imports the module fresh, so the client under test is
// always bound to that test's stub.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as ClientModule from "./client";

let mockFetch: ReturnType<typeof vi.fn>;
let client: typeof ClientModule;

beforeEach(async () => {
  vi.resetModules();
  mockFetch = vi.fn();
  vi.stubGlobal("fetch", mockFetch);
  client = await import("./client");
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

function noContentResponse(status: number): Response {
  return new Response(null, { status });
}

describe("getTree", () => {
  it("returns the tree on 200", async () => {
    const tree = { read_at: "2026-09-22T00:00:00Z", projects: [] };
    mockFetch.mockResolvedValueOnce(jsonResponse(200, tree));

    await expect(client.getTree()).resolves.toEqual(tree);

    const [request] = mockFetch.mock.calls[0] as [Request];
    expect(request.url).toContain("/api/tree");
    expect(request.method).toBe("GET");
  });

  it("throws UnauthorizedError on 401, carrying the daemon's detail", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(401, { detail: "Missing or invalid session cookie." }));

    await expect(client.getTree()).rejects.toThrow(client.UnauthorizedError);
  });

  it("throws ServiceUnavailableError on 503, distinct from UnauthorizedError", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(503, { detail: "registry read failed" }));

    let caught: unknown;
    try {
      await client.getTree();
    } catch (err) {
      caught = err;
    }

    expect(caught).toBeInstanceOf(client.ServiceUnavailableError);
    expect(caught).not.toBeInstanceOf(client.UnauthorizedError);
    expect((caught as Error).message).toBe("registry read failed");
  });

  it("propagates a network failure as neither UnauthorizedError nor ServiceUnavailableError", async () => {
    mockFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    let caught: unknown;
    try {
      await client.getTree();
    } catch (err) {
      caught = err;
    }

    expect(caught).toBeInstanceOf(Error);
    expect(caught).not.toBeInstanceOf(client.UnauthorizedError);
    expect(caught).not.toBeInstanceOf(client.ServiceUnavailableError);
  });
});

describe("createSession", () => {
  it("sends the token in the POST body once, never in the URL", async () => {
    mockFetch.mockResolvedValueOnce(noContentResponse(204));

    await expect(client.createSession("secret-token")).resolves.toBeUndefined();

    const [request] = mockFetch.mock.calls[0] as [Request];
    expect(request.method).toBe("POST");
    expect(request.url).not.toContain("secret-token");
    await expect(request.clone().json()).resolves.toEqual({ token: "secret-token" });
  });

  it("throws UnauthorizedError on 401 (token did not match)", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(401, { detail: "Token did not match." }));
    await expect(client.createSession("wrong")).rejects.toThrow(client.UnauthorizedError);
  });

  it("throws ForbiddenError on 403 (bad origin), distinct from UnauthorizedError", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(403, { detail: "Origin not allowed." }));

    let caught: unknown;
    try {
      await client.createSession("t");
    } catch (err) {
      caught = err;
    }

    expect(caught).toBeInstanceOf(client.ForbiddenError);
    expect(caught).not.toBeInstanceOf(client.UnauthorizedError);
  });

  // Regression: openapi-fetch returns `error: undefined` for ANY empty-body
  // response, success or not (it keys off Content-Length/204, not `.ok`). A
  // wrapper that treats `!error` as success would silently accept a
  // 500-with-empty-body as a successful session exchange.
  it("does not treat a non-204 empty body as success", async () => {
    mockFetch.mockResolvedValueOnce(noContentResponse(500));
    await expect(client.createSession("t")).rejects.toThrow(/500/);
  });
});

describe("getMe", () => {
  it("resolves on 204", async () => {
    mockFetch.mockResolvedValueOnce(noContentResponse(204));
    await expect(client.getMe()).resolves.toBeUndefined();
  });

  it("throws UnauthorizedError on 401", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(401, { detail: "Missing or invalid session cookie." }));
    await expect(client.getMe()).rejects.toThrow(client.UnauthorizedError);
  });

  it("does not treat a non-204 empty body as success", async () => {
    mockFetch.mockResolvedValueOnce(noContentResponse(500));
    await expect(client.getMe()).rejects.toThrow(/500/);
  });
});

describe("getHealth", () => {
  it("returns the health payload on 200, unauthenticated", async () => {
    const health = { version: "0.0.0", started_at: "2026-09-22T00:00:00Z" };
    mockFetch.mockResolvedValueOnce(jsonResponse(200, health));

    await expect(client.getHealth()).resolves.toEqual(health);
  });
});
