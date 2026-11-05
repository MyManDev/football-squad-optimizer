import { expect, test } from "@playwright/test";
import { installLeagueMocks } from "./leagueMocks";
import AxeBuilder from "@axe-core/playwright";
import { atRest } from "./atRest";
import { mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";
import { AS_A_CHANCE } from "../src/testSupport/honesty";

/** The dash the table prints for a figure it does not know. */
const UNKNOWN = "\u2014";

for (const language of ["en", "tr"] as const) {
  test(`captured movement keeps missing and unchanged ranks distinct in ${language}`, async ({
    page,
  }, testInfo) => {
    const publication = structuredClone(mockLeagueMembersEnvelope);
    const human = publication.payload.members.find((member) => member.member_kind === "human")!;
    const states = [
      { movement: "up", movement_places: 1 },
      { movement: "down", movement_places: 3 },
      { movement: "same", movement_places: 0 },
      { movement: "unknown", movement_places: null },
    ] as const;
    publication.payload.members = states.map((state, index) => ({
      ...human,
      entry_id: 101 + index,
      rank: index + 1,
      manager_name: `Movement member ${index}`,
      ...state,
    }));
    await page.addInitScript((value) => localStorage.setItem("squadopt.language", value), language);
    // The visitor has said they are a member this list serves.
    await installLeagueMocks(page, {
      claim: {
        leagueId: publication.payload.league_id,
        entryId: 101,
        managerName: "Movement member 0",
        teamName: human.team_name,
        leagueName: publication.payload.league_name,
      },
    });
    await page.route("**/data/league/members.json", (route) =>
      route.fulfill({ json: publication }),
    );
    await page.goto("/league/352490/members");
    const copy = MESSAGES[language].leagueMembers;
    // Movement is the second column, after the rank.
    const movement = (index: number) =>
      page
        .getByRole("row")
        .filter({ has: page.getByRole("link", { name: `Movement member ${index}`, exact: true }) })
        .getByRole("cell")
        .nth(1);
    for (const [index, [words, mark]] of [
      [copy.movementLabel("up", 1), "1"],
      [copy.movementLabel("down", 3), "3"],
      [copy.movementLabel("same", 0), "="],
    ].entries()) {
      // The words are the cell's name and the eye reads an arrow and the places, or '='.
      const cell = movement(index);
      await expect(cell).toHaveAccessibleName(words!);
      await expect(cell.locator('[aria-hidden="true"]').first()).toHaveText(mark!);
    }
    // A rank with nothing to compare it to is a dash, for the eye and a screen reader alike.
    await expect(movement(3)).toHaveAccessibleName(UNKNOWN);
    await expect(movement(3)).toHaveText(UNKNOWN);
    expect(await page.locator("main").textContent()).not.toMatch(AS_A_CHANCE);
    await atRest(page);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath("movement-desktop.png"), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    // The shell takes its phone layout once the resize reaches it; measure the page then.
    await expect(page.locator('[data-layout="phone"]')).toHaveCount(1);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    // The table itself fits the phone: nothing in it scrolls sideways.
    const fit = await page.locator("#league-member-list").evaluate((table) => ({
      table: table.scrollWidth,
      column: table.parentElement!.clientWidth,
      overflow: getComputedStyle(table.parentElement!).overflowX,
    }));
    expect(fit.table).toBeLessThanOrEqual(fit.column);
    expect(fit.overflow).toBe("visible");
    await movement(3).scrollIntoViewIfNeeded();
    await expect(movement(3)).toBeInViewport();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: testInfo.outputPath("movement-mobile.png"), fullPage: true });
  });
}
