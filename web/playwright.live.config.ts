import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.LIVE_BASE_URL;
if (!baseURL || process.env.CI) throw new Error("Set LIVE_BASE_URL for this manual, non-CI check.");
if (!/^https?:$/.test(new URL(baseURL).protocol)) throw new Error("LIVE_BASE_URL must be HTTP(S).");

export default defineConfig({
  testDir: "./e2e",
  testMatch: "live-smoke.spec.ts",
  timeout: 60_000,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: { baseURL, trace: "retain-on-failure" },
  projects: [
    { name: "live-desktop", use: { ...devices["Desktop Chrome"] } },
    {
      name: "live-phone",
      use: { ...devices["Desktop Chrome"], viewport: { width: 375, height: 812 } },
    },
  ],
});
