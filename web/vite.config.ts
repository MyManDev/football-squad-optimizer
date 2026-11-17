/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

import { firstTurn } from "./vite/firstTurn.ts";
import { pagesNotFound } from "./vite/pagesNotFound.ts";
import { sitePolicy } from "./vite/sitePolicy.ts";

// https://vite.dev/config/
export default defineConfig({
  // sitePolicy comes before pagesNotFound, so the preview's 404 pages carry the headers too.
  plugins: [react(), sitePolicy(), pagesNotFound(), firstTurn()],
  // Hosting-agnostic: set VITE_BASE_PATH (e.g. "/football-squad-optimizer/") for a
  // sub-path deployment such as GitHub Pages; "/" for a root domain.
  base: process.env.VITE_BASE_PATH ?? "/",
  build: {
    sourcemap: false,
    rollupOptions: {
      output: {
        // Only vendor code is grouped by hand. Application modules follow their lazy()
        // routes, so index.html preloads the shell and vendor code and no page's chunk.
        manualChunks(id) {
          // The speed measurements of ADR 0015 are imported only when the usage record is on,
          // after the page has drawn; kept out of vendor, they cost the first visit nothing.
          if (id.includes("node_modules/web-vitals")) return undefined;
          if (id.includes("node_modules")) return "vendor";
          return undefined;
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "scripts/**/*.test.mjs", "vite/**/*.test.ts"],
    css: { modules: { classNameStrategy: "non-scoped" } },
  },
});
