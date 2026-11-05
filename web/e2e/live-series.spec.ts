import { expect, test } from "@playwright/test";
import { installLeagueMocks } from "./leagueMocks";
import AxeBuilder from "@axe-core/playwright";
import { atRest } from "./atRest";
import { mockSuggestionOverview } from "../src/fixtures/weeklySuggestionOverview";
import type { Scoreboard } from "../src/features/league/types";
import { MESSAGES } from "../src/i18n/messages";

// What the card draws for a figure its document leaves empty.
const NO_FIGURE = "\u2014";

for (const language of ["en", "tr"] as const) {
  test(`the weekly scoreboard draws its five columns and fits a 390 px phone in ${language}`, async ({
    page,
  }) => {
    const history = mockSuggestionOverview();
    history.payload.weeks = history.payload.weeks.slice(0, 2);
    const view: Scoreboard = {
      season: history.payload.season,
      league_id: 352490,
      source_snapshot_id: history.payload.as_of_snapshot_id,
      captured_at_utc: history.generated_at_utc,
      cohort_snapshot_id: null,
      cohort_picks_snapshot_id: null,
      gameweeks: history.payload.weeks.map((week) => ({
        gameweek: week.gameweek,
        deadline_utc: week.deadline_utc!,
        finished: true,
        data_checked: true,
        average_entry_score: null,
        highest_score: null,
        ours: {
          net: 26,
          xi: 26,
          hits: 0,
          projected: 50,
          scoring_basis:
            week.gameweek === 4 ? "named_eleven_no_autosubs" : "official_autosub_captain_v2",
          vice_captain_named: week.gameweek !== 4,
        },
        top100: null,
        members: [
          {
            entry_id: 101,
            points: week.actual!.gross_points,
            net: week.actual!.net_points,
            hit_cost: week.actual!.transfer_hit_points,
            total_points: week.actual!.net_points,
          },
        ],
        members_mean_net: week.actual!.net_points,
        members_counted: 1,
      })),
      cumulative: {
        through_gameweek: 5,
        gameweeks: [4, 5],
        members_mean_total_points: null,
        members_counted: 1,
        average_entry_score: null,
      },
    };
    await page.addInitScript((value) => localStorage.setItem("squadopt.language", value), language);
    await installLeagueMocks(page);
    await page.route("**/data/league/scoreboard.json", (route) =>
      route.fulfill({
        json: {
          contract_version: "provisional_league_ui_v1",
          generated_at_utc: history.generated_at_utc,
          source_kind: "live",
          payload: view,
        },
      }),
    );
    await page.goto("/league/352490");
    const copy = MESSAGES[language];
    const scoreboard = page.getByRole("table", { name: copy.leagueScoreboard.caption });
    await expect(scoreboard.getByRole("columnheader")).toHaveText([
      copy.leagueScoreboard.gameweek,
      copy.leagueScoreboard.members,
      copy.leagueScoreboard.top100,
      copy.leagueScoreboard.average,
      copy.leagueScoreboard.highest,
    ]);
    await expect(scoreboard.getByRole("rowheader")).toHaveText([
      "4",
      "5",
      copy.leagueScoreboard.cumulative(5),
    ]);
    await expect(scoreboard.locator("tbody tr").first().locator("td")).toHaveText([
      language === "tr" ? "22,0" : "22.0",
      NO_FIGURE,
      NO_FIGURE,
      NO_FIGURE,
    ]);
    await atRest(page);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await page.setViewportSize({ width: 390, height: 844 });
    const scrollRegion = page.getByRole("region", { name: copy.leagueScoreboard.caption });
    // Resizing returns before the responsive layout and focus scrolling settle.
    await scrollRegion.scrollIntoViewIfNeeded();
    await expect(scrollRegion).toBeInViewport();
    await expect
      .poll(() => scrollRegion.evaluate((region) => region.scrollWidth - region.clientWidth))
      .toBe(0);
    await expect(scoreboard.getByRole("columnheader").last()).toBeInViewport();
    await atRest(page);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  });
}
