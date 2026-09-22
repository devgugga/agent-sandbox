// Loads `server/fixtures/healthy-tree.json` (Task 6) for component tests,
// so the front end's "every label" test exercises the same data the
// `--fixture` daemon and the Playwright smoke e2e use, rather than a
// second, hand-maintained copy that could drift from it.
//
// Read with plain `node:fs` rather than a Vite import specifier: `web/`
// is its own Vite/pnpm project root (its `pnpm-workspace.yaml` does not
// cover `server/`), so Vite's dev-server module graph refuses to serve or
// transform any path outside it, `?raw` included ("Denied ID"). A runtime
// `readFileSync` never asks Vite to resolve the path as a module, so that
// boundary does not apply — this only needs `@types/node` (devDependency)
// for `tsc --noEmit` to type-check the imports.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { TreeResponse } from "../api/client";

// Resolved against the test runner's working directory (`web/`, both for
// `pnpm test` and Vite's own root) rather than `import.meta.url`: under
// Vitest's transform, `import.meta.url` for a test-adjacent module is not
// reliably a `file:` URL, which breaks `fileURLToPath`.
const fixturePath = resolve(process.cwd(), "../server/fixtures/healthy-tree.json");

export const healthyTreeFixture: TreeResponse = JSON.parse(
  readFileSync(fixturePath, "utf-8"),
) as TreeResponse;
