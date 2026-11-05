import AxeBuilder from "@axe-core/playwright";
import { atRest } from "./atRest";
import { expect, test, type Locator, type Page, type Route } from "@playwright/test";

import { EXAMPLE_CLAIM } from "./identity";
import { installLeagueMocks } from "./leagueMocks";
import { mockEntrySquadEnvelopes, mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";

const copy = MESSAGES.tr.leagueMembers;
const humans = mockLeagueMembersEnvelope.payload.members.filter(
  (member) => member.member_kind === "human",
);
// The mocked visitor has said they are the first member (e2e/identity.ts).
const first = humans[0]!;
const second = humans[1]!;
// The league's last row, whose squad has no chips and who has no one behind them.
const last = humans.at(-1)!;
const LEAGUE_NAME = mockLeagueMembersEnvelope.payload.league_name;

function claimLast(page: Page) {
  return page.addInitScript(
    (claim) => sessionStorage.setItem("squadopt.member", JSON.stringify(claim)),
    {
      ...EXAMPLE_CLAIM,
      entryId: last.entry_id,
      managerName: last.manager_name,
      teamName: last.team_name,
    },
  );
}

/** Claims the last member and holds the read of their squad; the function returned ends it. */
async function holdLastSquad(page: Page, answer: (route: Route) => Promise<void>) {
  await claimLast(page);
  let release!: () => void;
  const released = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(
    new RegExp(`/data/league/entries/${last.entry_id}\\.json(?:\\?.*)?$`),
    async (route) => {
      await released;
      await answer(route);
    },
  );
  return release;
}

/** How much of the columns' width the table's own column leaves to the one beside it. */
function widthLeft(table: Locator) {
  return table.evaluate(
    (element) =>
      element.parentElement!.parentElement!.clientWidth - element.parentElement!.clientWidth,
  );
}

test.beforeEach(async ({ page }) => {
  await installLeagueMocks(page);
});

test("at 1440 the table and the viewer's chips share one screen", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/league/352490/members");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(LEAGUE_NAME);

  // The viewer's own row is the lime one, and the only one.
  const own = page.locator('#league-member-list tr[aria-current="true"]');
  await expect(own).toHaveCount(1);
  await expect(own).toContainText(first.team_name!);
  await expect(own.locator("td").first()).toHaveCSS("background-color", "rgb(198, 255, 61)");

  // The score bug is the viewer's published row.
  const bug = page.locator("main header dl");
  await expect(bug).toContainText(`1/${humans.length}`);
  await expect(bug).toContainText(String(first.total_points));

  // The system's record is gone from beside the table.
  await expect(page.locator('main [data-mark="karne"]')).toHaveCount(0);

  // The viewer's chips and the member right behind them, beside the table.
  const table = page.locator("#league-member-list");
  const chips = page.getByRole("heading", { name: MESSAGES.tr.memberResources.chipsTitle });
  await expect(chips).toBeVisible();
  const tableBox = (await table.boundingBox())!;
  const chipsBox = (await chips.boundingBox())!;
  expect(chipsBox.x).toBeGreaterThanOrEqual(tableBox.x + tableBox.width);
  expect(chipsBox.y).toBeLessThan(tableBox.y + tableBox.height);
  const chaser = page.getByText(copy.followerLabel);
  await expect(chaser).toContainText(second.manager_name!);
  await expect(chaser).toContainText(
    copy.followerBehind(String(first.total_points! - second.total_points!)),
  );

  expect(await page.locator("main").textContent()).not.toContain("%");
  await atRest(page);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

for (const width of [1280, 1440, 1920]) {
  test(`at ${width} the table takes the whole width when the viewer has nothing beside it`, async ({
    page,
  }) => {
    await claimLast(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/league/352490/members");
    const table = page.locator("#league-member-list");
    await expect(table.locator('tr[aria-current="true"]')).toContainText(last.team_name!);
    await expect(
      page.getByRole("heading", { name: MESSAGES.tr.memberResources.chipsTitle }),
    ).toHaveCount(0);
    await expect(page.getByText(copy.followerLabel)).toHaveCount(0);
    // Once the squad is read: until then the column beside the table waits for its chips.
    await expect.poll(() => widthLeft(table)).toBe(0);
  });
}

for (const width of [1280, 1440]) {
  test(`at ${width} the table keeps its width while the last member's squad is read`, async ({
    page,
  }) => {
    // The real last place has chips, though the mocked one does not.
    const squad = structuredClone(mockEntrySquadEnvelopes[last.entry_id!]!);
    squad.payload.chips = mockEntrySquadEnvelopes[first.entry_id!]!.payload.chips;
    const release = await holdLastSquad(page, (route) => route.fulfill({ json: squad }));
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/league/352490/members");
    const table = page.locator("#league-member-list");
    await expect(table.locator('tr[aria-current="true"]')).toContainText(last.team_name!);

    const held = await widthLeft(table);
    expect(held).toBeGreaterThan(0);
    release();
    await expect(
      page.getByRole("heading", { name: MESSAGES.tr.memberResources.chipsTitle }),
    ).toBeVisible();
    expect(await widthLeft(table)).toBe(held);
  });
}

for (const [ending, answer] of [
  ["finds no chips", (route: Route) => route.fallback()],
  ["fails", (route: Route) => route.fulfill({ status: 500, json: {} })],
] as const) {
  test(`the table takes the whole width once the last member's read ${ending}`, async ({
    page,
  }) => {
    const release = await holdLastSquad(page, answer);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/league/352490/members");
    const table = page.locator("#league-member-list");
    await expect(table.locator('tr[aria-current="true"]')).toContainText(last.team_name!);

    expect(await widthLeft(table)).toBeGreaterThan(0);
    release();
    await expect.poll(() => widthLeft(table)).toBe(0);
  });
}

for (const width of [390, 820, 1179]) {
  test(`at ${width} the table fits without scrolling sideways`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/league/352490/members");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(LEAGUE_NAME);
    // No row carries a control of its own: the table is names and figures.
    await expect(page.locator("#league-member-list button")).toHaveCount(0);
    // No sideways scroll, in the page or in the table: on a phone the gap to the leader
    // gives way instead.
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    const fit = await page.locator("#league-member-list").evaluate((table) => ({
      table: table.scrollWidth,
      column: table.parentElement!.clientWidth,
    }));
    expect(fit.table).toBeLessThanOrEqual(fit.column);
    await expect(page.getByRole("columnheader", { name: copy.leaderGap })).toHaveCount(
      width < 600 ? 0 : 1,
    );

    // A row opens the member's page.
    await page
      .getByRole("row")
      .filter({ has: page.getByRole("link", { name: second.manager_name!, exact: true }) })
      .getByRole("link", { name: second.manager_name!, exact: true })
      .click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(second.team_name!);
  });
}
