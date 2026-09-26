import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";
import { AS_A_CHANCE } from "../src/testSupport/honesty";

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
    await page.route("**/data/league/members.json", (route) =>
      route.fulfill({ json: publication }),
    );
    await page.goto("/league/members");
    const copy = MESSAGES[language].leagueMembers;
    // How the table reads is one click away, in its closed "About this table".
    await page.locator("main details summary", { hasText: copy.aboutTable }).click();
    await expect(page.getByText(copy.movementNote)).toBeVisible();
    for (const [index, [words, mark]] of [
      [copy.movementLabel("up", 1), "1"],
      [copy.movementLabel("down", 3), "3"],
      [copy.movementLabel("same", 0), "="],
      [copy.noPreviousRank, "—"],
    ].entries()) {
      const row = page
        .getByRole("row")
        .filter({ has: page.getByRole("link", { name: `Movement member ${index}`, exact: true }) });
      // Movement is the second column, after the rank: the words are the cell's name and
      // the eye reads an arrow and the places, '=' or a dash.
      const cell = row.getByRole("cell").nth(1);
      await expect(cell).toHaveAccessibleName(words!);
      await expect(cell.locator('[aria-hidden="true"]').first()).toHaveText(mark!);
    }
    expect(await page.locator("main").textContent()).not.toMatch(AS_A_CHANCE);
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
    await page
      .getByRole("cell", { name: copy.noPreviousRank, exact: true })
      .scrollIntoViewIfNeeded();
    await expect(
      page.getByRole("cell", { name: copy.noPreviousRank, exact: true }),
    ).toBeInViewport();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: testInfo.outputPath("movement-mobile.png"), fullPage: true });
  });
}
