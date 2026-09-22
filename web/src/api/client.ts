// Typed wrappers around the daemon's four endpoints (spec §9.1, §9.4), built
// on `openapi-fetch` and the generated `schema.d.ts`. A contract change that
// this file does not follow fails `tsc`, not the user.
//
// The daemon carries the session in an `HttpOnly`, `SameSite=Strict` cookie
// (spec §7.5), so every request includes credentials; nothing here ever
// attaches a token to a header, a query string, or a log (spec §7.5, §17.7).
// The one exception is `createSession`, which sends the token exactly once,
// in the POST body, to exchange it for that cookie.
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type HealthResponse = components["schemas"]["HealthResponse"];
export type TreeResponse = components["schemas"]["TreeResponse"];

// Same-origin: the dev proxy and the production build both put `/api/*`
// behind the page's own origin, so `window.location.origin` is
// byte-for-byte equivalent to a relative baseUrl in both. It is also
// evaluated at module load, so this module is browser/jsdom-only (fine for
// item 1; relevant if a future test file runs under `environment: "node"`).
const client = createClient<paths>({ baseUrl: window.location.origin, credentials: "include" });

/** Thrown when the daemon rejects the session cookie (401): re-authentication is needed. */
export class UnauthorizedError extends Error {
  constructor(detail: string) {
    super(detail);
    this.name = "UnauthorizedError";
  }
}

/**
 * Thrown by `getTree` when the registry read failed (503, spec §7.6). The
 * caller should keep the last tree it had and mark it stale, not discard it.
 */
export class ServiceUnavailableError extends Error {
  constructor(detail: string) {
    super(detail);
    this.name = "ServiceUnavailableError";
  }
}

/** Thrown by `createSession` when the request's Origin was missing or foreign (403). */
export class ForbiddenError extends Error {
  constructor(detail: string) {
    super(detail);
    this.name = "ForbiddenError";
  }
}

/** Best-effort extraction of the daemon's `{detail}` error envelope; never throws. */
function errorDetail(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

/** `GET /api/health` — no auth required. */
export async function getHealth(): Promise<HealthResponse> {
  const { data, error, response } = await client.GET("/api/health");
  if (data) return data;
  throw new Error(errorDetail(error, `Health check failed (${response.status})`));
}

/** `POST /api/auth/session` — exchanges the one-time token for the session cookie. */
export async function createSession(token: string): Promise<void> {
  const { error, response } = await client.POST("/api/auth/session", {
    body: { token },
  });
  if (response.status === 204) return;
  if (response.status === 401) throw new UnauthorizedError(errorDetail(error, "Unauthorized"));
  if (response.status === 403) throw new ForbiddenError(errorDetail(error, "Forbidden"));
  throw new Error(errorDetail(error, `Unexpected response (${response.status})`));
}

/** `GET /api/auth/me` — 204 when the session cookie is valid, 401 otherwise. */
export async function getMe(): Promise<void> {
  const { error, response } = await client.GET("/api/auth/me");
  if (response.status === 204) return;
  if (response.status === 401) throw new UnauthorizedError(errorDetail(error, "Unauthorized"));
  throw new Error(errorDetail(error, `Unexpected response (${response.status})`));
}

/** Every error `getTree` can throw, so a caller can distinguish them with `instanceof`. */
export type TreeFetchError = UnauthorizedError | ServiceUnavailableError | Error;

/** `GET /api/tree` — the project/checkout/session tree. */
export async function getTree(): Promise<TreeResponse> {
  const { data, error, response } = await client.GET("/api/tree");
  if (data) return data;
  if (response.status === 401) throw new UnauthorizedError(errorDetail(error, "Unauthorized"));
  if (response.status === 503) throw new ServiceUnavailableError(errorDetail(error, "Registry unavailable"));
  throw new Error(errorDetail(error, `Unexpected response (${response.status})`));
}
