import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { installLeagueMocks } from "./leagueMocks";
import { mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";

const copy = MESSAGES.tr.leagueMembers;
const humans = mockLeagueMembersEnvelope.payload.members.filter(
  (member) => member.member_kind === "human",
);
const first = humans[0]!;
const second = humans[1]!;

test.beforeEach(async ({ page }) => {
  await installLeagueMocks(page);
});

/** Say "this is me" on the first member's row, then come back to the table in the same visit. */
async function claimFirstAndReturn(page: Page) {
  await page.goto("/league/members");
  await page
    .getByRole("row")
    .filter({ has: page.getByRole("link", { name: first.manager_name!, exact: true }) })
    .getByRole("button", { name: copy.viewerSelect })
    .click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(first.team_name!);
  await page.goBack();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(copy.title);
}

test("at 1440 the table, the system's record and the viewer's chips share one screen", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await claimFirstAndReturn(page);

  // The viewer's own row is the lime one, and the only one.
  const own = page.locator('#league-member-list tr[aria-current="true"]');
  await expect(own).toHaveCount(1);
  await expect(own).toContainText(first.team_name!);
  await expect(own.locator("td").first()).toHaveCSS("background-color", "rgb(198, 255, 61)");

  // The score bug is the viewer's published row.
  const bug = page.locator("main header dl");
  await expect(bug).toContainText(`1/${humans.length}`);
  await expect(bug).toContainText(String(first.total_points));

  // The system's record stands beside the table, with the full scoreboard closed.
  const table = page.locator("#league-member-list");
  const karne = page.getByRole("region", { name: copy.karneTitle });
  await expect(karne).toBeVisible();
  const tableBox = (await table.boundingBox())!;
  const karneBox = (await karne.boundingBox())!;
  expect(karneBox.x).toBeGreaterThanOrEqual(tableBox.x + tableBox.width);
  expect(karneBox.y).toBeLessThan(tableBox.y + tableBox.height);
  await expect(karne.getByText(copy.karneCaption)).toBeVisible();
  // The full scoreboard is a wide table: closed, and once opened it reads across both
  // columns without scrolling sideways instead of squeezing into the record's column.
  const full = page.locator("main details", { hasText: copy.karneFull });
  await expect(full).toHaveCount(1);
  await expect(full).not.toHaveAttribute("open");
  await full.locator("summary").click();
  const scoreboardTable = full.getByRole("table", {
    name: MESSAGES.tr.leagueScoreboard.caption,
  });
  await expect(scoreboardTable).toBeVisible();
  expect((await full.boundingBox())!.width).toBeGreaterThan(tableBox.width + karneBox.width);
  const region = await scoreboardTable.evaluate((element) => ({
    table: element.scrollWidth,
    column: element.parentElement!.clientWidth,
  }));
  expect(region.table).toBeLessThanOrEqual(region.column);
  await full.locator("summary").click();

  // The viewer's chips and the member right behind them.
  await expect(
    page.getByRole("heading", { name: MESSAGES.tr.memberResources.chipsTitle }),
  ).toBeVisible();
  const chaser = page.getByText(copy.followerLabel);
  await expect(chaser).toContainText(second.manager_name!);
  await expect(chaser).toContainText(
    copy.followerBehind(String(first.total_points! - second.total_points!)),
  );

  expect(await page.locator("main").textContent()).not.toContain("%");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test("a cold visitor sees no lime row, no score bug and no chips", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/league/members");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(copy.title);
  await expect(page.locator('#league-member-list tr[aria-current="true"]')).toHaveCount(0);
  await expect(page.locator("main header dl")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: MESSAGES.tr.memberResources.chipsTitle }),
  ).toHaveCount(0);
  await expect(page.getByText(copy.followerLabel)).toHaveCount(0);
  await expect(page.getByRole("region", { name: copy.karneTitle })).toBeVisible();
});

for (const width of [390, 820, 1179]) {
  test(`at ${width} the table fits and the viewer's controls are touch targets`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/league/members");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(copy.title);
    for (const button of await page.getByRole("button", { name: copy.viewerSelect }).all()) {
      const box = (await button.boundingBox())!;
      expect(box.height, "Bu benim").toBeGreaterThanOrEqual(44);
    }

    await claimFirstAndReturn(page);
    for (const control of [
      page.getByRole("button", { name: copy.viewerClear }),
      page.getByRole("link", { name: copy.viewerChange, exact: true }),
      page.getByRole("link", { name: copy.viewerOpenMine }),
    ]) {
      const box = (await control.boundingBox())!;
      expect(box.height).toBeGreaterThanOrEqual(44);
    }
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

    // The member page's own clear control is a touch target too.
    await page
      .getByRole("row")
      .filter({ has: page.getByRole("link", { name: second.manager_name!, exact: true }) })
      .getByRole("link", { name: second.manager_name!, exact: true })
      .click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(second.team_name!);
    const clear = page.getByRole("button", { name: copy.viewerClear });
    await clear.scrollIntoViewIfNeeded();
    expect((await clear.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  });
}
