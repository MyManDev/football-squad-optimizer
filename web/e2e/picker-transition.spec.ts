import { expect, test, type Browser } from "@playwright/test";

import { MESSAGES } from "../src/i18n/messages";
import { installLeagueMocks } from "./leagueMocks";

// The step from "Sen kimsin?" to the page (#1131) in a real browser: with motion the page
// change runs as one view transition, and with the reduced-motion preference it runs none;
// either way the visitor lands on the same page in the same state, and the page throws
// nothing, an unhandled rejection from a skipped transition included.
async function confirmIn(
  browser: Browser,
  reducedMotion: "reduce" | "no-preference",
  presses: 1 | 2 = 1,
) {
  const page = await browser.newPage();
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
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
  const confirm = page.getByRole("button", { name: copy.confirm });
  if (presses === 1) {
    await confirm.click();
  } else {
    // Two presses inside one frame, before the first transition's update has run.
    await confirm.evaluate((button: HTMLButtonElement) => {
      button.click();
      button.click();
    });
  }
  await expect(page.getByRole("group", { name: copy.legend })).toHaveCount(0);
  await page.evaluate(() => Promise.all(document.getAnimations().map((motion) => motion.finished)));
  const state = {
    url: page.url(),
    heading: await page.getByRole("heading", { level: 1 }).first().textContent(),
    transitions: await page.evaluate(
      () => (window as unknown as { transitions: number }).transitions,
    ),
    errors,
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
  expect(moving.errors).toEqual([]);
  expect(still.errors).toEqual([]);
});

test("a second Onayla in the same frame starts no second transition", async ({ browser }) => {
  const once = await confirmIn(browser, "no-preference");
  const twice = await confirmIn(browser, "no-preference", 2);
  expect(twice.transitions).toBe(1);
  expect(twice.url).toBe(once.url);
  expect(twice.heading).toBe(once.heading);
  expect(twice.errors).toEqual([]);
});
