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
      // Tap the already-visible sticky control without the runner's scrollIntoView step.
      const menu = await page.getByRole("button", { name: "Menüyü aç", exact: true }).boundingBox();
      await page.mouse.click(menu!.x + menu!.width / 2, menu!.y + menu!.height / 2);
      await expect(page.getByRole("dialog", { name: "Menü", exact: true })).toBeVisible();
      expect(await page.evaluate(() => window.scrollY)).toBe(original);
    }
    const fixtures = page.locator("#sidebar").getByRole("link", { name: "Fikstür", exact: true });
    if (width < 600) {
      await atRest(page);
      const link = await fixtures.boundingBox();
      await page.mouse.click(link!.x + link!.width / 2, link!.y + link!.height / 2);
    } else await fixtures.click();
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
  const scrim = page.locator("[class*=scrim]");
  await expect(scrim).toHaveCSS("pointer-events", "none");
  await expect(scrim).toHaveCSS("opacity", "0");
});

for (const reducedMotion of ["no-preference", "reduce"] as const) {
  test(
    "navigation without native snapshots settles and releases input: " + reducedMotion,
    async ({ page }) => {
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.setViewportSize({ width: 390, height: 844 });
      await page.emulateMedia({ reducedMotion });
      await page.addInitScript(() => {
        Object.defineProperty(document, "startViewTransition", { value: undefined });
        const observed = window as unknown as { mainArrivals: Animation[] };
        observed.mainArrivals = [];
        const animate = Element.prototype.animate;
        Element.prototype.animate = function (...args) {
          const animation = animate.apply(this, args);
          if (this.tagName === "MAIN") observed.mainArrivals.push(animation);
          return animation;
        };
      });
      await installLeagueMocks(page);
      await page.goto("/league/352490/members/35249001");
      await atRest(page);
      const arrivals = () =>
        page.evaluate(
          () => (window as unknown as { mainArrivals: Animation[] }).mainArrivals.length,
        );
      const before = await arrivals();
      await page.getByRole("button", { name: "Menüyü aç", exact: true }).click();
      await page.locator("#sidebar").getByRole("link", { name: "Fikstür", exact: true }).click();
      await expect(page).toHaveURL(/\/fixtures$/);
      // WebKit's click can return after the short effect finishes; keep real Animation
      // objects so the check does not depend on catching one particular painted frame.
      await expect.poll(arrivals).toBe(before + (reducedMotion === "no-preference" ? 1 : 0));
      await atRest(page);
      await expect(page.locator("main")).toHaveCSS("opacity", "1");
      await expect(page.locator("main")).not.toHaveAttribute("inert");
      await expect(page.locator("[class*=scrim]")).toHaveCSS("pointer-events", "none");
      await page.goBack();
      await atRest(page);
      await expect(page).toHaveURL(/\/members\/35249001$/);
      await expect(page.locator("main")).toHaveCSS("transform", "none");
      expect(errors).toEqual([]);
    },
  );
}
