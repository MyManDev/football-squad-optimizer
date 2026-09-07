/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Hosting-agnostic: set VITE_BASE_PATH (e.g. "/football-squad-optimizer/") for a
  // sub-path deployment such as GitHub Pages; "/" for a root domain.
  base: process.env.VITE_BASE_PATH ?? "/",
  build: {
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules")) return "vendor";
          // Keep the two score views together: shared rendering compresses once.
          if (
            id.includes("/src/features/squad/") ||
            id.endsWith("/src/features/league/pages/LeaguePage.tsx")
          )
            return "scores";
          return undefined;
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "scripts/**/*.test.mjs"],
    css: { modules: { classNameStrategy: "non-scoped" } },
  },
});
