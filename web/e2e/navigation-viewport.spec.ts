import { expect, test } from "@playwright/test";

import { atRest } from "./atRest";
import { installLeagueMocks } from "./leagueMocks";

for (const width of [320, 390, 1280]) {
  test(`navigation starts at the heading and back keeps the reading position at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 844 });
    await installLeagueMocks(page);
    await page.goto("/league/352490/members/35249001");
    await atRest(page);
    await page.locator("#kadro").scrollIntoViewIfNeeded();
    const original = await page.evaluate(() => window.scrollY);
    expect(original).toBeGreaterThan(100);
    if (width < 600) {
      await page.getByRole("button", { name: "Menüyü aç", exact: true }).click();
      await expect(page.getByRole("dialog", { name: "Menü", exact: true })).toBeVisible();
      expect(await page.evaluate(() => window.scrollY)).toBe(original);
    }
    await page.locator("#sidebar").getByRole("link", { name: "Fikstür", exact: true }).click();
    await expect(page).toHaveURL(/\/fixtures$/);
    await atRest(page);
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
    const heading = page.getByRole("heading", { level: 1 }).first();
    await expect(heading).toBeFocused();
    expect((await heading.boundingBox())!.y).toBeGreaterThanOrEqual(width < 600 ? 56 : 0);
    await page.goBack();
    await atRest(page);
    await expect
      .poll(async () => Math.abs((await page.evaluate(() => window.scrollY)) - original))
      .toBeLessThan(3);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  });
}

test("the phone drawer contains keyboard focus and Escape returns to its opener", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installLeagueMocks(page);
  await page.goto("/league/352490/members/35249001");
  await atRest(page);
  const opener = page.getByRole("button", { name: "Menüyü aç", exact: true });
  await opener.click();
  const close = page.getByRole("button", { name: "Menüyü kapat", exact: true });
  await expect(close).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(page.locator("#sidebar button").last()).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(close).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(opener).toBeFocused();
  await expect(page.locator("html")).not.toHaveCSS("overflow", "hidden");
});
