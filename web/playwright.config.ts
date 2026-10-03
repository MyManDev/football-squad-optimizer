import { defineConfig, devices } from "@playwright/test";

import { rememberedLeague } from "./e2e/leagueState";

const baseURL = "http://127.0.0.1:4173";

export default defineConfig({
  testDir: "./e2e",
  testIgnore: ["**/advice-backend.spec.ts", "**/live-smoke.spec.ts"], // separate opt-in configs
  timeout: 30_000,
  fullyParallel: true,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL,
    // Every league address sits behind the league number; the specs open it already given.
    storageState: rememberedLeague(baseURL),
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run preview -- --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
