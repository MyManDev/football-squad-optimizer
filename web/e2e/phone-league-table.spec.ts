import { expect, test, type Page } from "@playwright/test";

import { mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";
import { installLeagueMocks } from "./leagueMocks";

const copy = MESSAGES.tr.leagueMembers;
const humans = mockLeagueMembersEnvelope.payload.members.filter(
  (member) => member.member_kind === "human",
);
const second = humans[1]!;

/** What a tap on a point of the row would land on: the member's link, or nothing of it. */
function linkAt(page: Page, x: number, y: number) {
  return page.evaluate(
    ([px, py]) => document.elementFromPoint(px!, py!)?.closest("a")?.textContent ?? null,
    [x, y],
  );
}

for (const width of [390, 414]) {
  test.describe(`the league table at ${width} px`, () => {
    test.use({ viewport: { width, height: 844 } });

    test.beforeEach(async ({ page }) => {
      await installLeagueMocks(page);
      await page.goto("/league/352490/members");
      await expect(page.locator("#league-member-list tbody tr")).toHaveCount(humans.length);
    });

    test("fits, with the first-screen columns and nothing shrunken", async ({ page }) => {
      const table = page.locator("#league-member-list");
      const fit = await table.evaluate((element) => ({
        table: element.scrollWidth,
        column: element.parentElement!.clientWidth,
      }));
      expect(fit.table).toBeLessThanOrEqual(fit.column);
      expect(
        await page.locator("main").evaluate((main) => main.scrollWidth <= main.clientWidth),
      ).toBe(true);

      for (const name of [copy.rank, copy.team, copy.total]) {
        await expect(table.getByRole("columnheader", { name, exact: true })).toBeInViewport();
      }
      await expect(table.getByRole("columnheader", { name: copy.leaderGap })).toHaveCount(0);
      await expect(table.getByRole("columnheader", { name: copy.lastWeekLabel })).toHaveCount(0);
      const row = table.getByRole("row").filter({ hasText: second.team_name! });
      await expect(row).toContainText(second.manager_name!);
      await expect(row).toContainText(String(second.total_points));
    });

    test("every row is a thumb's height and opens the member's page", async ({ page }) => {
      const rows = page.locator("#league-member-list tbody tr");
      for (const row of await rows.all()) {
        const box = (await row.boundingBox())!;
        expect(box.height).toBeGreaterThanOrEqual(44);
        const link = row.getByRole("link");
        const linkBox = (await link.boundingBox())!;
        expect(linkBox.height).toBeGreaterThanOrEqual(44);
        const name = await link.textContent();
        const toggleBox = (await row.getByRole("button").boundingBox())!;
        expect(toggleBox.width).toBeGreaterThanOrEqual(44);
        expect(toggleBox.height).toBeGreaterThanOrEqual(44);
        // From the rank at the row's start to the total just before the chevron.
        const y = box.y + box.height / 2;
        expect(await linkAt(page, box.x + 8, y)).toBe(name);
        expect(await linkAt(page, toggleBox.x - 8, y)).toBe(name);
      }
    });

    test("the rest of a row folds out from its chevron and folds back", async ({ page }) => {
      const address = page.url();
      const row = page
        .locator("#league-member-list tbody tr")
        .filter({ hasText: second.team_name! });
      const toggle = row.getByRole("button");
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      await toggle.focus();
      await page.keyboard.press("Enter");
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
      // Still the same button: opening its row does not draw the row again.
      await expect(toggle).toBeFocused();
      const details = page.locator(`#${await toggle.getAttribute("aria-controls")}`);
      await expect(details).toContainText(copy.leaderGap);
      await expect(details).toContainText(/\d/);
      expect(page.url()).toBe(address);
      await toggle.click();
      await expect(details).toHaveCount(0);
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
    });
  });
}

test("a tablet keeps every column and no chevron", async ({ page }) => {
  await page.setViewportSize({ width: 820, height: 1180 });
  await installLeagueMocks(page);
  await page.goto("/league/352490/members");
  const table = page.locator("#league-member-list");
  await expect(table.getByRole("columnheader", { name: copy.leaderGap })).toHaveCount(1);
  await expect(table.getByRole("button")).toHaveCount(0);
});
