import { defineConfig, devices } from "@playwright/test";

import base from "./playwright.config";

// Cover the device solver and the navigation into it on all three browser engines.
export default defineConfig({
  ...base,
  testIgnore: undefined,
  testMatch: [
    "**/device-plan.spec.ts",
    "**/what-if.spec.ts",
    "**/member-picker.spec.ts",
    "**/fixtures.spec.ts",
  ],
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
  ],
});
