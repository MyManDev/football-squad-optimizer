import { defineConfig, devices } from "@playwright/test";

import { rememberedLeague } from "./e2e/leagueState";

const baseURL = process.env.LIVE_BASE_URL;
if (!baseURL || process.env.CI) throw new Error("Set LIVE_BASE_URL for this manual, non-CI check.");
if (!/^https?:$/.test(new URL(baseURL).protocol)) throw new Error("LIVE_BASE_URL must be HTTP(S).");

export default defineConfig({
  testDir: "./e2e",
  testMatch: "live-*.spec.ts",
  timeout: 60_000,
  globalTimeout: 300_000,
  workers: 1,
  // Retain each redacted journey in the same run and mark a successful retry as flaky.
  retries: 1,
  reporter: "list",
  use: {
    baseURL,
    serviceWorkers: "block",
    storageState: rememberedLeague(new URL(baseURL).origin),
    // Live response bodies and DOM captures can retain private comparison identities.
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  projects: [
    {
      name: "live-desktop",
      testMatch: "live-smoke.spec.ts",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "live-phone",
      testMatch: "live-smoke.spec.ts",
      use: { ...devices["Desktop Chrome"], viewport: { width: 375, height: 812 } },
    },
    ...(["tr", "en"] as const).flatMap((language) =>
      [
        { name: "desktop", viewport: { width: 1280, height: 720 } },
        { name: "phone", viewport: { width: 360, height: 800 } },
      ].map(({ name, viewport }) => ({
        name: `live-tour-${name}-${language}`,
        testMatch: "live-tour.spec.ts",
        metadata: { language },
        use: {
          ...devices["Desktop Chrome"],
          viewport,
          locale: language === "tr" ? "tr-TR" : "en-GB",
          serviceWorkers: "block" as const,
          // A trace or screenshot can retain private comparison identities from a response.
          trace: "off" as const,
          screenshot: "off" as const,
          video: "off" as const,
        },
      })),
    ),
  ],
});
