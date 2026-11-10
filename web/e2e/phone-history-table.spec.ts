import { expect, test, type Page } from "@playwright/test";

import { mockSuggestionOverview } from "../src/fixtures/weeklySuggestionOverview";
import { MESSAGES } from "../src/i18n/messages";
import { installLeagueMocks } from "./leagueMocks";

const copy = MESSAGES.tr.suggestionHistory;

async function openOverview(page: Page) {
  await installLeagueMocks(page);
  await page.route("**/data/league/history/101.json", (route) =>
    route.fulfill({ json: mockSuggestionOverview() }),
  );
  await page.goto("/league/352490/members/101/history");
  const overview = page.getByRole("region", { name: copy.overview });
  await expect(overview.getByRole("table")).toBeVisible();
  return overview;
}

for (const width of [390, 414]) {
  test.describe(`the history overview at ${width} px`, () => {
    test.use({ viewport: { width, height: 844 } });

    test("fits, with the week and both net scores on the screen", async ({ page }) => {
      const overview = await openOverview(page);
      const fit = await overview.evaluate((box) => ({
        scroll: box.scrollWidth,
        client: box.clientWidth,
      }));
      expect(fit.scroll).toBeLessThanOrEqual(fit.client);
      for (const name of [copy.week, copy.systemNet, copy.memberNet]) {
        const header = overview.getByRole("columnheader", { name, exact: true });
        await expect(header).toBeInViewport({ ratio: 1 });
      }
      for (const name of [copy.weekDifference, copy.cumulative]) {
        await expect(overview.getByRole("columnheader", { name })).toHaveCount(0);
      }
      // The box's own vertical scroll keeps its header and footer.
      await expect(overview.locator("thead th").first()).toHaveCSS("position", "sticky");
      await expect(overview.locator("tfoot th").first()).toHaveCSS("position", "sticky");
    });

    test("every week button and chevron is a thumb's size", async ({ page }) => {
      const overview = await openOverview(page);
      const buttons = overview.getByRole("button");
      expect(await buttons.count()).toBeGreaterThan(0);
      for (const button of await buttons.all()) {
        const box = (await button.boundingBox())!;
        expect(box.width).toBeGreaterThanOrEqual(44);
        expect(box.height).toBeGreaterThanOrEqual(44);
      }
      for (const row of await overview.locator("tbody tr").all()) {
        expect((await row.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      }
    });

    test("a week's differences fold out under it, and its button still opens it", async ({
      page,
    }) => {
      const overview = await openOverview(page);
      const row = overview.locator("tbody tr").first();
      const toggle = row.locator("td button");
      await toggle.focus();
      await page.keyboard.press("Enter");
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
      await expect(toggle).toBeFocused();
      const details = page.locator(`#${await toggle.getAttribute("aria-controls")}`);
      await expect(details).toContainText(copy.weekDifference);
      await expect(details).toContainText(copy.cumulative);
      await toggle.click();
      await expect(details).toHaveCount(0);

      await row.getByRole("rowheader").getByRole("button").click();
      await expect(page.getByText(`${copy.difference}:`)).toBeVisible();
    });
  });
}

test("a tablet keeps the five columns and no chevron", async ({ page }) => {
  await page.setViewportSize({ width: 820, height: 1180 });
  const overview = await openOverview(page);
  await expect(overview.getByRole("columnheader")).toHaveCount(5);
  await expect(overview.getByRole("button", { expanded: false })).toHaveCount(0);
});
