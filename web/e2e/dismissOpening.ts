import { expect, type Page } from "@playwright/test";

/** A returning tab has already dismissed the opening. A fresh tab can use Escape. */
export async function dismissOpening(page: Page): Promise<void> {
  const mark = page.locator("[data-opening-mark]");
  if (await mark.isVisible()) await page.keyboard.press("Escape");
  await expect(mark).toHaveCount(0);
}
