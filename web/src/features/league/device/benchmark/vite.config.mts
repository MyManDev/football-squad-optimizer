import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";

export default defineConfig({
  root: fileURLToPath(new URL(".", import.meta.url)),
  publicDir: false,
  build: {
    target: "esnext",
    outDir: fileURLToPath(
      new URL("../../../../../../.codex-tmp/real-horizon-browser", import.meta.url),
    ),
    emptyOutDir: true,
  },
  worker: { format: "es" },
});
