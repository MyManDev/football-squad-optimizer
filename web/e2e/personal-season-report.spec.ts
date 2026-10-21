import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fixture from "../src/fixtures/weeklySuggestionHistory.json" with { type: "json" };
import { installLeagueMocks } from "./leagueMocks";
import { atRest } from "./atRest";

for (const language of ["tr", "en"] as const) {
  test(`the personal report shows two settled transfers on a phone in ${language}`, async ({
    page,
  }, testInfo) => {
    await installLeagueMocks(page);
    await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
    const history = structuredClone(fixture);
    history.payload.entry_id = 35249001;
    Object.assign(history.payload.weeks[0].actual, {
      details: {
        source_snapshot_id: "settled-capture",
        captain: { player_id: 8, name: "Captain", points: 3, multiplier: 2, counted_points: 6 },
        transfers: [
          {
            player_out: "Former one",
            player_in: {
              player_id: 1,
              name: "Arrival one",
              points: 5,
              multiplier: 1,
              counted_points: 5,
            },
          },
          {
            player_out: "Former two",
            player_in: {
              player_id: 2,
              name: "Arrival two",
              points: 2,
              multiplier: 0,
              counted_points: 0,
            },
          },
        ],
      },
    });
    await page.route("**/data/league/history/35249001.json", (route) =>
      route.fulfill({ json: history }),
    );
    await page.setViewportSize({ width: 360, height: 780 });
    await page.goto("/league/352490/members/35249001/history");
    const title = language === "tr" ? "Sezon raporum" : "My season report";
    await page.getByText(title, { exact: true }).click();
    const report = page
      .locator("details")
      .filter({ has: page.locator("summary", { hasText: title }) });
    await expect(report.getByRole("listitem")).toHaveCount(2);
    await expect(report).toContainText(/22[,.]0.*20[,.]0.*8[,.]0/);
    await expect(report).toContainText(/Captain.*6[,.]0/);
    await expect(report).toContainText(/Former two → Arrival two.*0[,.]0/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await atRest(page);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await report.screenshot({ path: testInfo.outputPath("personal-report-mobile.png") });
  });
}
