import type { Page } from "@playwright/test";

/**
 * Waits until no animation on the page is running. The substitution boards move once when
 * a decision is drawn (#1131), and an accessibility scan reads contrast from what is on
 * screen, so it is taken at rest, never half-way through that motion. It reads each
 * animation's play state rather than awaiting its `finished`: a switch mid-motion cancels
 * the board's motion, and a cancelled animation's `finished` rejects.
 */
export async function atRest(page: Page): Promise<void> {
  await page.waitForFunction(() =>
    document.getAnimations().every((motion) => motion.playState !== "running"),
  );
}
