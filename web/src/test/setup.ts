// Vitest setup (spec §13.2). Registers `@testing-library/jest-dom`'s
// matchers (`toBeInTheDocument`, `toHaveAttribute`, ...) and runs Testing
// Library's DOM cleanup after every test. `vite.config.ts`'s `test` block
// does not set `globals: true`, so Testing Library's own auto-cleanup
// (which only fires when it finds a global `afterEach`) never runs on its
// own — without this, elements from one test's `render()` leak into the
// next.
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

afterEach(() => {
  cleanup();
});
