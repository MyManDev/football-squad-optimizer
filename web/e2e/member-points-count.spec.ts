import { expect, test, type Page } from "@playwright/test";

import { mockEntryAdviceEnvelope } from "../src/fixtures/league";
import { installLeagueMocks } from "./leagueMocks";

// #1131 step 3: the plan's net expected points count to the new plan's value when the member
// switches plans, and the reduced-motion preference shows the same final value at once.
const NET = { 3: 49, 5: 52.5 } as const;

async function servePlansWithNet(page: Page): Promise<void> {
  await page.route(/\/data\/league\/advice\/35249001\/saf-puan\/[35]\.json(?:\?.*)?$/, (route) => {
    const window = route.request().url().includes("/5.json") ? 5 : 3;
    const envelope = mockEntryAdviceEnvelope(35249001, "saf-puan", window);
    envelope.payload.lineup_expectation = {
      version: "expected_lineup_v1",
      expected_net_points: NET[window],
      starting_points: 43,
      autosub_points: 1,
      captain_bonus_points: 3,
      vice_bonus_points: 2,
      bench_boost_points: 0,
      assumptions: ["independent_player_week_appearances"],
    };
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(envelope) });
  });
}

/** Counts the animations started on counted figures, from the page's first script. */
async function countFigureAnimations(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const started = { count: 0 };
    (window as unknown as { __figureCounts: typeof started }).__figureCounts = started;
    const animate = Element.prototype.animate;
    Element.prototype.animate = function (this: Element, ...args: Parameters<typeof animate>) {
      if (this.hasAttribute("data-counting-number")) started.count += 1;
      return animate.apply(this, args);
    };
  });
}

for (const reducedMotion of ["no-preference", "reduce"] as const) {
  test(`the net expected points end on the new plan's value (${reducedMotion})`, async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion });
    await installLeagueMocks(page);
    await servePlansWithNet(page);
    await countFigureAnimations(page);
    await page.goto("/league/352490/members/35249001?window=3");
    const breakdown = page.getByTestId("lineup-expectation");
    await expect(breakdown).toContainText("Ceza sonrası beklenen puan: 49,0");

    await page.getByRole("radio", { name: /^5 / }).click();
    await expect(page).toHaveURL(/window=5/);
    await expect(breakdown).toContainText("Ceza sonrası beklenen puan: 52,5");
    await page.waitForFunction(() => document.getAnimations().length === 0);
    await expect(breakdown).toContainText("Ceza sonrası beklenen puan: 52,5");

    const started = await page.evaluate(
      () => (window as unknown as { __figureCounts: { count: number } }).__figureCounts.count,
    );
    expect(started).toBe(reducedMotion === "reduce" ? 0 : 1);
  });
}
