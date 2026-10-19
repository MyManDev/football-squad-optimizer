import { defineConfig, devices } from "@playwright/test";

import base from "./playwright.config";

// The device spec on the three browser engines a member may bring (#981 step 4): the same
// server, mocks and timeouts as the main config, with WebKit and Firefox beside Chromium.
// Each test prints its device timings as one JSON line, so one run per engine compares them.
export default defineConfig({
  ...base,
  testIgnore: undefined,
  testMatch: ["**/device-plan.spec.ts"],
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
  ],
});
