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
    await page.route("https://fonts.googleapis.com/**", (route) =>
      route.fulfill({ body: "", contentType: "text/css" }),
    );
    await page.route("**/data/league/members.json", (route) =>
      route.fulfill({ json: publication }),
    );
    await page.goto("/league/members");
    const copy = MESSAGES[language].leagueMembers;
    await expect(page.getByText(copy.movementNote)).toBeVisible();
    for (const [index, expected] of [
      "↑ 1",
      "↓ 3",
      copy.movementLabel("same", 0),
      copy.noPreviousRank,
    ].entries()) {
      const row = page
        .getByRole("row")
        .filter({ has: page.getByRole("link", { name: `Movement member ${index}`, exact: true }) });
      await expect(row.locator("td").last()).toHaveText(expected);
    }
    expect(await page.locator("main").textContent()).not.toMatch(AS_A_CHANCE);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath("movement-desktop.png"), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await page.locator("#league-member-list").evaluate((table) => {
      const wrapper = table.parentElement!;
      wrapper.scrollLeft = wrapper.scrollWidth;
    });
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
