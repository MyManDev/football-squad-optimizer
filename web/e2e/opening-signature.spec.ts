import { expect, test } from "@playwright/test";

import { installLeagueMocks } from "./leagueMocks";

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
    await opening.evaluate((node) => {
      node.getAnimations({ subtree: true }).forEach((animation) => {
        animation.pause();
        animation.currentTime = 1500;
      });
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
    await expect(opening).toHaveAttribute("inert");
    await page.screenshot({ path: testInfo.outputPath(`signature-${width}.png`) });
    await page.clock.runFor(2300);
    await expect(opening).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Ligi bul", exact: true })).toBeEnabled();
  });
}
