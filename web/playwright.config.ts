import { defineConfig, devices } from "@playwright/test";

import { refuseMismatchedBuild } from "./e2e/buildOrigin";
import { CSP_REPORT_FILE } from "./e2e/cspReport";
import { rememberedLeague } from "./e2e/leagueState";

refuseMismatchedBuild();

const baseURL = "http://127.0.0.1:4173";

export default defineConfig({
  testDir: "./e2e",
  testIgnore: ["**/advice-backend.spec.ts", "**/live-smoke.spec.ts"], // separate opt-in configs
  timeout: 30_000,
  // A genuine regression fails every attempt; one slow test under runner contention does
  // not (#797: a Python-only pull request went red on a 1.9 s test against a 30 s budget).
  // Locally there is no retry, so a flake is seen where it can be measured.
  retries: process.env.CI ? 2 : 0,
  fullyParallel: true,
  reporter: process.env.CI ? "github" : "list",
  // The preview sends the site's Content-Security-Policy and writes each refusal a browser
  // reports to CSP_REPORT_FILE; the run fails at its end on any the specs did not make.
  globalSetup: "./e2e/cspReport.setup.ts",
  globalTeardown: "./e2e/cspReport.teardown.ts",
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
    env: { SQUADOPT_CSP_REPORT_FILE: CSP_REPORT_FILE },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
