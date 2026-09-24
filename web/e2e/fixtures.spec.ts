import { expect, test } from "@playwright/test";

import fixtures from "../public/data/fixtures.json" with { type: "json" };
import indexFixture from "../public/data/index.json" with { type: "json" };

// The fixtures page reads whatever week the shipped fixture list names, which moves with every
// publish.
const current = Number(fixtures.payload.current_gameweek);
const season = indexFixture.payload.latest.season;

const scrollsSideways = () =>
  document.documentElement.scrollWidth > document.documentElement.clientWidth;

for (const width of [1280, 1600])
  test(`a ${width}px screen keeps the page beside the sidebar, with no league-wide rail`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.clock.setFixedTime(new Date("2026-09-18T10:00:00Z"));
    await page.goto(`/gw/${season}/1`);
    await expect(page.getByRole("heading", { level: 1 })).toContainText(/Oyun haftası/);

    // The two margin rails and the closed list under the page are gone: a member's page
    // carries its own fixtures, and /fixtures carries the whole list.
    await expect(page.getByRole("complementary", { name: "Oynanacak hafta" })).toHaveCount(0);
    await expect(page.getByRole("complementary", { name: "Gelecek hafta" })).toHaveCount(0);
    await expect(
      page.locator("details", { hasText: "Fikstür: bu hafta ve gelecek hafta" }),
    ).toHaveCount(0);

    const sidebar = (await page.locator("#sidebar").boundingBox())!;
    const main = (await page.getByRole("main").boundingBox())!;
    expect(sidebar.x).toBe(0);
    expect(sidebar.width).toBe(264);
    expect(main.x).toBeGreaterThanOrEqual(sidebar.x + sidebar.width);
    expect(main.x + main.width).toBeLessThanOrEqual(width);
    expect(await page.evaluate(scrollsSideways)).toBe(false);

    await page.getByRole("navigation").getByRole("link", { name: "Fikstür", exact: true }).click();
    await expect(page).toHaveURL("/fixtures");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Fikstür");
    const weeks = page.getByRole("main").getByRole("heading", { level: 2 });
    await expect(weeks.first()).toHaveText(`Oynanacak hafta · Oyun haftası ${current}`);
    await expect(weeks.nth(3)).toHaveText(`Oyun haftası ${current - 1}`);
    await expect(
      page.getByRole("navigation").getByRole("link", { name: "Fikstür", exact: true }),
    ).toHaveAttribute("aria-current", "page");
  });

test("a phone reaches the fixture list from its bar and never scrolls sideways", async ({
  page,
}) => {
  await page.setViewportSize({ width: 400, height: 800 });
  await page.clock.setFixedTime(new Date("2026-09-18T10:00:00Z"));
  await page.goto(`/gw/${season}/1`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/Oyun haftası/);
  await expect(page.getByRole("complementary", { name: "Oynanacak hafta" })).toHaveCount(0);
  await expect(
    page.locator("details", { hasText: "Fikstür: bu hafta ve gelecek hafta" }),
  ).toHaveCount(0);
  expect(await page.evaluate(scrollsSideways)).toBe(false);

  const bar = page.getByRole("banner");
  await expect(bar).toBeVisible();
  expect((await bar.boundingBox())!.height).toBe(56);
  // No page offers a fixture sheet here, so the bar's 'Fikstür' is a link to the list.
  await bar.getByRole("link", { name: "Fikstür", exact: true }).click();
  await expect(page).toHaveURL("/fixtures");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Fikstür");
  await expect(
    page.getByRole("main").getByRole("heading", {
      level: 2,
      name: `Gelecek hafta · Oyun haftası ${current + 1}`,
    }),
  ).toBeVisible();
  expect(await page.evaluate(scrollsSideways)).toBe(false);

  // The bar stays at the top while the page scrolls under it.
  await page.evaluate(() => window.scrollTo(0, 600));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
  expect((await bar.boundingBox())!.y).toBe(0);
});
