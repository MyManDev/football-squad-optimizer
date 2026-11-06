import { expect, test } from "@playwright/test";

import { installLeagueMocks } from "./leagueMocks";

for (const { width, touch } of [
  { width: 375, touch: true },
  { width: 1280, touch: false },
]) {
  test.describe(`first interaction at ${width}px`, () => {
    test.use({ viewport: { width, height: 844 }, hasTouch: touch, reducedMotion: "no-preference" });

    test("dismisses the opening without clicking the covered control", async ({ page }) => {
      await page.clock.install();
      await page.clock.pauseAt(new Date());
      await installLeagueMocks(page);
      await page.goto("/");
      const opening = page.locator("[data-opening-mark]");
      await expect(opening).toBeAttached();
      await opening.evaluate((node) => {
        node.getAnimations({ subtree: true }).forEach((animation) => {
          animation.pause();
          animation.currentTime = 2000;
        });
      });
      const fixtures = page.getByRole("link", { name: "Fikstür", exact: true });
      const box = (await fixtures.boundingBox())!;
      const x = box.x + box.width / 2;
      const y = box.y + box.height / 2;
      if (touch) await page.touchscreen.tap(x, y);
      else await page.mouse.click(x, y);
      await expect(opening).toHaveCount(0);
      await expect(page).toHaveURL("/");
      await expect(fixtures).not.toBeFocused();
      await fixtures.click();
      await expect(page).toHaveURL("/fixtures");
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    });

    test("Tab reveals the page and keeps normal keyboard navigation", async ({ page }) => {
      await page.clock.install();
      await page.clock.pauseAt(new Date());
      await installLeagueMocks(page);
      await page.goto("/");
      await expect(page.locator("[data-opening-mark]")).toBeAttached();
      await page.keyboard.press("Tab");
      await expect(page.locator("[data-opening-mark]")).toHaveCount(0);
      await expect(page.locator(":focus")).toBeVisible();
      expect(await page.locator(":focus").evaluate((node) => node.tagName)).not.toBe("BODY");
    });
  });
}

for (const width of [320, 1280]) {
  test(`the opening signature fits at ${width}px and leaves the page usable`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    await page.clock.install();
    await page.clock.pauseAt(new Date());
    await installLeagueMocks(page);
    await page.goto("/");
    const opening = page.locator("[data-opening-mark]");
    await expect(opening).toBeAttached();
    const duration = await opening.evaluate((node) => {
      const duration = Number(node.getAnimations()[0]?.effect?.getTiming().duration);
      node.getAnimations({ subtree: true }).forEach((animation) => {
        animation.pause();
        animation.currentTime = duration * 0.75;
      });
      return duration;
    });
    await page.evaluate(() => document.fonts.ready);
    const signature = opening.getByText("MyManDev", { exact: true });
    const box = await signature.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(width);
    expect(box!.x + box!.width).toBeGreaterThan(width - 50);
    expect(box!.y).toBeGreaterThan(720);
    const brand = await opening.getByText("SquadOpt", { exact: true }).locator("..").boundingBox();
    expect(Math.abs(brand!.x + brand!.width / 2 - width / 2)).toBeLessThan(2);
    expect(Math.abs(brand!.y + brand!.height / 2 - 422)).toBeLessThan(2);
    await expect(opening.getByText("Still Building", { exact: true })).toBeVisible();
    await expect(opening).toHaveCSS("pointer-events", "auto");
    await page.screenshot({ path: testInfo.outputPath(`signature-${width}.png`) });
    await page.clock.runFor(duration + 300);
    await expect(opening).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Ligi bul", exact: true })).toBeEnabled();
  });
}
