/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The daemon binds 127.0.0.1:7420 by default (spec section 7.5). `pnpm dev`
// proxies /api to it so the browser only ever talks to the Vite origin;
// `asb-server serve --dev` is what allows that origin in return.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // `server/asb_server/settings.py`'s DEV_ORIGIN pins :5173 as the
    // allowed dev Origin. Without strictPort, Vite silently moves to
    // :5174 when :5173 is taken, and the dev-mode token POST then fails
    // with a 403 the operator has no way to explain.
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:7420",
        changeOrigin: true,
      },
    },
  },
  test: {
    // Scoped to src/: web/tests/ holds Playwright specs (playwright.config.ts),
    // and vitest's default include pattern would otherwise also match those.
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    environment: "jsdom",
    passWithNoTests: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
