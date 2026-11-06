import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fixture from "../src/fixtures/requestedSuggestionHistory.json" with { type: "json" };
import { MESSAGES } from "../src/i18n/messages";
import { installLeagueMocks } from "./leagueMocks";
import { atRest } from "./atRest";

const unrecorded = {
  ...fixture,
  payload: {
    ...fixture.payload,
    weeks: [
      {
        gameweek: 4,
        status: "unavailable",
        reason: "no_pre_deadline_record",
        deadline_utc: fixture.payload.weeks[0].deadline_utc,
        advice_snapshot_id: null,
        advice_captured_at_utc: null,
        advice_generated_at_utc: null,
        advice_sha256: null,
        outcome_snapshot_id: null,
        outcome_captured_at_utc: null,
        expected_own_points: null,
        suggested: null,
        actual: null,
        actual_reason: null,
        net_difference: null,
        players: [],
      },
    ],
  },
};

for (const [language, width, height] of [
  ["tr", 375, 812],
  ["en", 1280, 900],
] as const) {
  test(`requested server history renders the Python-scored result in ${language}`, async ({
    page,
  }, testInfo) => {
    await installLeagueMocks(page);
    await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
    await page.route("**/data/league/history/101.json", (route) => route.fulfill({ status: 404 }));
    await page.route("**/data/league/history/requested/101.json", (route) =>
      route.fulfill({ json: fixture }),
    );
    await page.setViewportSize({ width, height });
    await page.goto("/league/352490/members/101/history");
    const copy = MESSAGES[language].suggestionHistory;
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(copy.title);
    await expect(page.getByText(copy.requested)).toBeVisible();
    await page.getByRole("combobox", { name: copy.week }).selectOption("4");
    await expect(page.getByText(`${copy.difference}:`)).toContainText(/−2[,.]0/);
    await expect(page.getByRole("row", { name: /Player 8 MID/ })).toContainText(
      `${copy.captain} (x2)`,
    );
    expect(
      await page.locator("main").evaluate((node) => node.scrollWidth <= node.clientWidth),
    ).toBe(true);
    await atRest(page);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await page.screenshot({
      path: testInfo.outputPath(`requested-history-${language}.png`),
      fullPage: true,
    });
    await page.route("**/data/league/history/101.json", (route) =>
      route.fulfill({ json: unrecorded }),
    );
    await page.reload();
    await expect(page.getByText(copy.requested)).toBeVisible();
    await page.getByRole("combobox", { name: copy.week }).selectOption("4");
    await expect(page.getByText(`${copy.difference}:`)).toContainText(/−2[,.]0/);
  });
}
