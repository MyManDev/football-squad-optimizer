import { defineConfig, devices } from "@playwright/test";

const context = JSON.parse(process.env.SQUADOPT_BROWSER_CONTEXT ?? "null");
if (!context) throw new Error("Run this smoke through tests/integration/test_advice_browser.py.");
const output = `node_modules/.cache/${context.buildName}`;

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/advice-backend.spec.ts",
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: "list",
  outputDir: "test-results/backend",
  use: { baseURL: context.webOrigin, trace: "retain-on-failure" },
  webServer: {
    // Vite substitutes the API origin during the build. Keep this test bundle
    // separate from dist, which may subsequently be published as the static site.
    command:
      "npm run build:analysis && " +
      `npx vite build --outDir ${output} && ` +
      `npx vite preview --outDir ${output} ` +
      `--host 127.0.0.1 --port ${context.webPort} --strictPort`,
    url: context.webOrigin,
    env: { VITE_ADVICE_API_ORIGIN: context.apiOrigin, VITE_BASE_PATH: "/" },
    reuseExistingServer: false,
    timeout: 90_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
