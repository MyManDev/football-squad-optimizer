import { expect, test, type Browser } from "@playwright/test";

import { MESSAGES } from "../src/i18n/messages";
import { installLeagueMocks } from "./leagueMocks";

// The step from "Sen kimsin?" to the page (#1131) in a real browser: with motion the page
// change runs as one view transition, and with the reduced-motion preference it runs none;
// either way the visitor lands on the same page in the same state.
async function confirmIn(browser: Browser, reducedMotion: "reduce" | "no-preference") {
  const page = await browser.newPage();
  await page.emulateMedia({ reducedMotion });
  await page.addInitScript(() => {
    const counted = window as unknown as { transitions: number };
    counted.transitions = 0;
    const start = document.startViewTransition?.bind(document);
    if (start) {
      document.startViewTransition = ((update: () => Promise<void>) => {
        counted.transitions += 1;
        return start(update);
      }) as typeof document.startViewTransition;
    }
  });
  await installLeagueMocks(page, { claim: null });
  await page.goto("/league/352490/members");
  const copy = MESSAGES.tr.memberPicker;
  const group = page.getByRole("group", { name: copy.legend });
  await group.getByRole("radio", { name: /Seda Kaya/ }).check();
  await page.getByRole("button", { name: copy.confirm }).click();
  await expect(page.getByRole("group", { name: copy.legend })).toHaveCount(0);
  await page.evaluate(() => Promise.all(document.getAnimations().map((motion) => motion.finished)));
  const state = {
    url: page.url(),
    heading: await page.getByRole("heading", { level: 1 }).first().textContent(),
    transitions: await page.evaluate(
      () => (window as unknown as { transitions: number }).transitions,
    ),
  };
  await page.close();
  return state;
}

test("the step to the page crossfades with motion and lands the same without it", async ({
  browser,
}) => {
  const moving = await confirmIn(browser, "no-preference");
  const still = await confirmIn(browser, "reduce");
  expect(moving.transitions).toBe(1);
  expect(still.transitions).toBe(0);
  expect(still.url).toBe(moving.url);
  expect(still.heading).toBe(moving.heading);
});
