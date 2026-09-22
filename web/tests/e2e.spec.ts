// web/tests/e2e.spec.ts — the one Playwright smoke e2e (spec §13.2).
// Starts the real daemon (`asb-server serve --fixture <path>`) serving
// the real `web/dist` build, opens it with the token URL fragment exactly as
// `asb-agent ui` does, and checks the tree renders and refreshes. Uses both
// fixtures in `server/fixtures/`: the healthy tree (all eight labels of spec
// §9.2) and the registry-failure tree (the 503 banner path).
//
// Two hazards this file works around:
// - `--fixture` resolves its path against the daemon's CWD at launch, not
//   the repo root, so `startDaemon` below always passes an absolute path.
// - `read_at` is fixed under `--fixture` (it comes from the fixture file,
//   not the clock), so the refresh assertion checks that a new `/api/tree`
//   request goes out and succeeds, never that a displayed timestamp changed.
//
// `--fixture` does not disable authentication, so every test here goes
// through the real token exchange: read the token the daemon wrote to
// its (per-test, isolated) `ASB_CONFIG_ROOT`, then navigate to
// `#token=<token>`, exactly the fragment `asb-agent ui` would open.
import { test, expect, type Page } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, "..", "..");
const ASB_SERVER_BIN = join(REPO_ROOT, ".venv", "bin", "asb-server");
const HEALTHY_FIXTURE = join(REPO_ROOT, "server", "fixtures", "healthy-tree.json");
const FAILURE_FIXTURE = join(REPO_ROOT, "server", "fixtures", "registry-failure.json");

interface Daemon {
  readonly baseUrl: string;
  readonly token: string;
  stop(): Promise<void>;
}

/** An OS-assigned free TCP port, so parallel test files never collide. */
function freePort(): Promise<number> {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => {
        if (address && typeof address === "object") resolvePort(address.port);
        else reject(new Error("could not allocate a port"));
      });
    });
  });
}

/** Polls `/api/health` (no auth required) until the daemon answers or the
 * process exits early. */
async function waitForHealth(baseUrl: string, child: ChildProcess, stderr: { text: string }): Promise<void> {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`asb-server exited early (code ${child.exitCode}):\n${stderr.text}`);
    }
    try {
      const response = await fetch(`${baseUrl}/api/health`);
      if (response.ok) return;
    } catch {
      // Not listening yet.
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error(`daemon at ${baseUrl} did not answer /api/health in time:\n${stderr.text}`);
}

/** Starts `asb-server serve --fixture <fixturePath>` on a free port, with
 * its own isolated `ASB_CONFIG_ROOT` (so its token/session-key files never
 * collide with a developer's real daemon or another test run). */
async function startDaemon(fixturePath: string): Promise<Daemon> {
  const port = await freePort();
  const configRoot = mkdtempSync(join(tmpdir(), "asb-e2e-"));
  const baseUrl = `http://127.0.0.1:${port}`;

  const child = spawn(
    ASB_SERVER_BIN,
    ["serve", "--port", String(port), "--fixture", fixturePath],
    { cwd: REPO_ROOT, env: { ...process.env, ASB_CONFIG_ROOT: configRoot } },
  );
  const stderr = { text: "" };
  child.stderr?.on("data", (chunk: Buffer) => {
    stderr.text += chunk.toString();
  });

  await waitForHealth(baseUrl, child, stderr);
  // `AuthManager.load` (server/asb_server/auth.py) writes this file before
  // `_serve` ever calls `uvicorn.run`, so by the time /api/health answers
  // it is guaranteed to exist.
  const token = readFileSync(join(configRoot, "server-token"), "utf8").trim();

  return {
    baseUrl,
    token,
    async stop() {
      child.kill("SIGTERM");
      await new Promise<void>((resolveStop) => {
        if (child.exitCode !== null) {
          resolveStop();
          return;
        }
        child.once("exit", () => resolveStop());
      });
      rmSync(configRoot, { recursive: true, force: true });
    },
  };
}

/** Opens the app the way `asb-agent ui` does: the token in the URL
 * fragment, never a query string (AuthGate reads only `#token=`). */
async function openAuthenticated(page: Page, daemon: Daemon): Promise<void> {
  await page.goto(`${daemon.baseUrl}/#token=${daemon.token}`);
}

test.describe("healthy tree fixture", () => {
  let daemon: Daemon;

  test.beforeAll(async () => {
    daemon = await startDaemon(HEALTHY_FIXTURE);
  });

  test.afterAll(async () => {
    await daemon.stop();
  });

  test("renders the fixture tree and refresh re-reads it", async ({ page }) => {
    await openAuthenticated(page, daemon);

    const tree = page.getByRole("tree", { name: "Projects" });
    await expect(tree).toBeVisible();

    // Projects, checkouts and sessions match the fixture.
    await expect(tree.getByText("agent-sandbox", { exact: true })).toBeVisible();
    await expect(tree.getByText("flaky-project", { exact: true })).toBeVisible();
    await expect(tree.getByText("docs-site", { exact: true })).toBeVisible();
    await expect(tree.getByText("review PR #42")).toBeVisible();

    // A representative spread of the eight labels spec §9.2 mandates —
    // `healthy-tree.json` reaches all of them; component-level coverage of
    // every one already lives in `ProjectTree.test.tsx` (spec §13.2), so
    // this smoke test spot-checks rather than re-enumerating them.
    await expect(tree.getByText("merged / cleanup available")).toBeVisible();
    await expect(tree.getByText("merged / cleanup pending")).toBeVisible();
    await expect(tree.getByText("missing", { exact: true }).first()).toBeVisible();
    await expect(tree.getByText("unregistered", { exact: true })).toBeVisible();
    await expect(tree.getByText("prunable", { exact: true })).toBeVisible();
    await expect(tree.getByText("(detached main) (host)")).toBeVisible();
    await expect(tree.getByText("!! reconcile failed")).toBeVisible();
    await expect(tree.getByText("!! discover failed: workspace root not found")).toBeVisible();

    // Refresh: a real second read goes out and succeeds. `read_at` is
    // fixed under `--fixture`, so this checks the request
    // fires and the tree stays rendered, never a timestamp change.
    const refreshed = page.waitForResponse(
      (response) => response.url().endsWith("/api/tree") && response.request().method() === "GET",
    );
    await page.getByRole("button", { name: "Refresh" }).click();
    const response = await refreshed;
    expect(response.status()).toBe(200);
    await expect(tree.getByText("agent-sandbox", { exact: true })).toBeVisible();
  });
});

test.describe("registry-failure fixture", () => {
  let daemon: Daemon;

  test.beforeAll(async () => {
    daemon = await startDaemon(FAILURE_FIXTURE);
  });

  test.afterAll(async () => {
    await daemon.stop();
  });

  test("shows the 503 banner", async ({ page }) => {
    await openAuthenticated(page, daemon);

    await expect(page.getByRole("alert")).toContainText(
      "Registry unavailable: registry file is corrupt: unexpected EOF",
    );
  });
});
