import { defineConfig } from "@playwright/test";

// One Playwright smoke e2e (spec §13.2): `tests/e2e.spec.ts` starts the real
// daemon itself (`--fixture`, an isolated `ASB_CONFIG_ROOT` and a free
// port), so this config stays minimal — no `webServer`, no browser matrix.
export default defineConfig({
  testDir: "./tests",
});
