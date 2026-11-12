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
    "**/navigation-viewport.spec.ts",
    "**/player-details.spec.ts",
    "**/forwarded-league.spec.ts",
    "**/member-live-score.spec.ts",
    "**/live-page.spec.ts",
    "**/live-motion-engines.spec.ts",
    "**/opening-signature.spec.ts",
  ],
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
  ],
});
