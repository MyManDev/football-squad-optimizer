import { defineConfig, devices } from "@playwright/test";

import { rememberedLeague } from "./e2e/leagueState";

const baseURL = process.env.LIVE_BASE_URL;
if (!baseURL || process.env.CI) throw new Error("Set LIVE_BASE_URL for this manual, non-CI check.");
if (!/^https?:$/.test(new URL(baseURL).protocol)) throw new Error("LIVE_BASE_URL must be HTTP(S).");

export default defineConfig({
  testDir: "./e2e",
  testMatch: "live-smoke.spec.ts",
  timeout: 60_000,
  workers: 1,
  // A second attempt inside the same run, so the first one's trace is still on disk: the
  // rerun an operator typed by hand emptied test-results and took the failure with it. An
  // attempt that fails prints its journey and says so, and the summary counts it as flaky.
  retries: 1,
  reporter: "list",
  use: {
    baseURL,
    storageState: rememberedLeague(new URL(baseURL).origin),
    // Every attempt, not "on-first-retry": that traces only the retry, which is the attempt
    // that passes, and the one worth reading is the first.
    trace: "on",
  },
  projects: [
    { name: "live-desktop", use: { ...devices["Desktop Chrome"] } },
    {
      name: "live-phone",
      use: { ...devices["Desktop Chrome"], viewport: { width: 375, height: 812 } },
    },
  ],
});
