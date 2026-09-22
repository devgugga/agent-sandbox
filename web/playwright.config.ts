import { defineConfig } from "@playwright/test";

// End-to-end tests land in later tasks alongside the components they
// exercise; item 1 only wires the runner so `pnpm test:e2e` is callable.
export default defineConfig({
  testDir: "./tests",
});
