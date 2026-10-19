import type { Page } from "@playwright/test";

/**
 * Waits until every animation on the page has finished. The substitution boards move once
 * when a decision is drawn (#1131), and an accessibility scan reads contrast from what is on
 * screen, so it is taken at rest, never half-way through that motion.
 */
export async function atRest(page: Page): Promise<void> {
  await page.evaluate(() => Promise.all(document.getAnimations().map((motion) => motion.finished)));
}
