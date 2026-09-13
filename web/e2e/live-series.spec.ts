import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mockSuggestionOverview } from "../src/fixtures/weeklySuggestionOverview";
import type { Scoreboard } from "../src/features/league/types";
import { MESSAGES } from "../src/i18n/messages";

for (const language of ["en", "tr"] as const) {
  test(`the live series groups member weeks and names the basis in ${language}`, async ({
    page,
  }, testInfo) => {
    const history = mockSuggestionOverview();
    history.payload.weeks = history.payload.weeks.slice(0, 2);
    const view: Scoreboard = {
      season: history.payload.season,
      league_id: 352490,
      source_snapshot_id: history.payload.as_of_snapshot_id,
      captured_at_utc: history.generated_at_utc,
      cohort_snapshot_id: null,
      cohort_picks_snapshot_id: null,
      registered_members: 1,
      histories_held: 1,
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
          mode: "live",
          scoring_basis:
            week.gameweek === 4 ? "named_eleven_no_autosubs" : "official_autosub_captain_v2",
          vice_captain_named: week.gameweek !== 4,
          diagnostics: {
            zero_minute_starters: 0,
            minutes_shortfall: -12,
            captain_shortfall: 2.5,
            autosub_recovery: week.gameweek === 4 ? null : 3,
          },
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
        ours_net: 52,
        ours_gameweeks: [4, 5],
        members_mean_total_points: null,
        members_gameweeks: [4, 5],
        members_counted: 1,
        average_entry_score: null,
      },
    };
    await page.addInitScript((value) => localStorage.setItem("squadopt.language", value), language);
    await page.route("https://fonts.googleapis.com/**", (route) =>
      route.fulfill({ body: "", contentType: "text/css" }),
    );
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
    await page.route("**/data/league/history/101.json", (route) =>
      route.fulfill({ json: history }),
    );
    await page.route("**/data/league/series-horizon.json", (route) =>
      route.fulfill({ status: 404 }),
    );
    await page.goto("/league");
    const copy = MESSAGES[language];
    await expect(page.getByText(copy.liveSeries.accumulated(2, 2))).toBeVisible();
    await expect(page.getByText(copy.liveSeries.unknown)).toBeVisible();
    await expect(page.getByText(copy.leagueScoreboard.mixedBases)).toBeVisible();
    await expect(page.getByText(copy.scoreboardComparisons.missing)).toBeVisible();
    const scoreboard = page.getByRole("table", { name: copy.leagueScoreboard.caption });
    await expect(scoreboard.getByRole("columnheader")).toHaveCount(10);
    const card = page
      .locator("section")
      .filter({ has: page.getByRole("heading", { name: copy.liveSeries.title, exact: true }) });
    await expect(card.getByRole("link", { name: "101", exact: true })).toHaveCount(2);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await card.screenshot({ path: testInfo.outputPath("series-desktop.png") });
    await page.setViewportSize({ width: 390, height: 844 });
    const summaryWidth = await card
      .getByRole("table")
      .first()
      .evaluate((table) => table.getBoundingClientRect().width);
    expect(summaryWidth).toBeLessThan(390);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await card.screenshot({ path: testInfo.outputPath("series-mobile.png") });
    await page.route("**/data/league/series-horizon.json", (route) =>
      route.fulfill({
        json: {
          contract_version: "member_week_horizon_v1",
          season: view.season,
          league_id: 352490,
          scoring_basis: "official_autosub_captain_v2",
          population: "recorded_member_suggestions_vs_actual",
          measurement_artifact: "docs/member_week_measurement.json",
          within_week_correlation: 0.3,
          required_week_clusters: 12,
          member_week_keys: history.payload.weeks.map(
            (week) => `101:${week.gameweek}:${week.advice_sha256}:${week.outcome_snapshot_id}`,
          ),
        },
      }),
    );
    await page.reload();
    await expect(page.getByText(copy.liveSeries.remaining(10))).toBeVisible();
    for (const week of view.gameweeks) delete week.ours!.diagnostics;
    await page.reload();
    await expect(page.getByText(copy.scoreboardComparisons.missing)).toBeVisible();
    for (const row of await scoreboard.locator("tbody tr, tfoot tr").all()) {
      const cells = await row.locator("td").allTextContents();
      expect(cells.slice(-4)).toEqual(["—", "—", "—", "—"]);
    }
    await page.setViewportSize({ width: 1280, height: 900 });
    await scoreboard
      .locator("..")
      .screenshot({ path: testInfo.outputPath("scoreboard-missing.png") });
  });
}
