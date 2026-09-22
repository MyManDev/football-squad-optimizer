import { expect, test } from "@playwright/test";

import fixtures from "../public/data/fixtures.json" with { type: "json" };
import indexFixture from "../public/data/index.json" with { type: "json" };

// The rails read whatever week the shipped fixture list names, which moves with every publish.
const current = Number(fixtures.payload.current_gameweek);
const season = indexFixture.payload.latest.season;

const scrollsSideways = () =>
  document.documentElement.scrollWidth > document.documentElement.clientWidth;

for (const width of [1280, 1600])
  test(`a ${width}px screen carries upcoming fixtures in both rails`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.clock.setFixedTime(new Date("2026-09-18T10:00:00Z"));
    await page.goto(`/gw/${season}/1`);
    const left = page.getByRole("complementary", { name: "Oynanacak hafta" });
    const right = page.getByRole("complementary", { name: "Gelecek hafta" });
    await expect(left).toContainText(`OH${current}`);
    await expect(right).toContainText(`OH${current + 1}`);
    await expect(left.getByRole("listitem")).toHaveCount(
      fixtures.payload.gameweeks[current - 1]!.fixtures.length,
    );

    const main = (await page.getByRole("main").boundingBox())!;
    const leftBox = (await left.boundingBox())!;
    const rightBox = (await right.boundingBox())!;
    expect(main.width).toBe(Math.min(1080, width - 420));
    expect(leftBox.x + leftBox.width).toBeLessThanOrEqual(main.x);
    expect(rightBox.x).toBeGreaterThanOrEqual(main.x + main.width);
    expect(await page.evaluate(scrollsSideways)).toBe(false);
    await expect(page.locator("details", { hasText: "Fikstür" })).toBeHidden();

    await left.getByRole("link", { name: "Geçmiş haftalar" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Fikstür");
    await expect(page.getByRole("heading", { level: 2 }).nth(3)).toHaveText(
      `Oyun haftası ${current - 1}`,
    );
    await expect(left).toHaveCount(0);
  });

test("a phone keeps both lists closed under the page and never scrolls sideways", async ({
  page,
}) => {
  await page.setViewportSize({ width: 400, height: 800 });
  await page.clock.setFixedTime(new Date("2026-09-18T10:00:00Z"));
  await page.goto(`/gw/${season}/1`);
  const stacked = page.locator("details", { hasText: "Fikstür: bu hafta ve gelecek hafta" });
  await expect(stacked).toBeVisible();
  await expect(stacked).not.toHaveAttribute("open", "");
  await expect(page.getByRole("complementary", { name: "Oynanacak hafta" })).toBeHidden();
  await stacked.locator("summary").click();
  await expect(stacked.getByRole("heading", { name: "Gelecek hafta" })).toBeVisible();
  expect(await page.evaluate(scrollsSideways)).toBe(false);
});
