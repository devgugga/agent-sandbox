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
