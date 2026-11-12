import { expect, test } from "@playwright/test";

import {
  BEATS,
  expectPlaceKept,
  expectReadMotion,
  expectSameEnd,
  firstRead,
  openLive,
  readAgain,
  readBeat,
} from "./liveMotion";

/**
 * LIVE's motion on each browser engine, in brief: at 375 px, a page with motion and one under
 * the reduced-motion preference read the first four beats of the synthetic Saturday (before
 * the kickoffs, the first match under way, the captain's goal with the vice's assist, the card).
 * The first read and a read made again move nothing; each newer read moves once its GOL moments
 * have landed, the planner's rows and no others, within the screen and by transform and opacity
 * alone; the page without motion never moves. Then, scrolled into the groups, the read that
 * ends the first match and starts the second keeps the part the visitor reads where it was on
 * both pages (WebKit has no scroll anchoring of its own); and both end with the same markup.
 * The full day is live-motion.spec.ts's.
 */

const index = (name: (typeof BEATS)[number]["name"]) =>
  BEATS.findIndex((beat) => beat.name === name);

test("LIVE moves once per newer read at 375px on every engine", async ({ browser }) => {
  test.slow();
  const moving = await openLive(browser, { width: 375, motion: true });
  const still = await openLive(browser, { width: 375, motion: false });
  try {
    for (const tab of [moving, still]) expect(await firstRead(tab)).toEqual([]);
    for (const at of [index("kickoff"), index("goal"), index("card")]) {
      const beat = BEATS[at]!;
      expectReadMotion(await readBeat(moving, at), beat.name, `motion: ${beat.name}`);
      expect((await readBeat(still, at)).started, `reduced: ${beat.name}`).toEqual([]);
    }
    await expectPlaceKept(moving, index("over"), "motion: over");
    await expectPlaceKept(still, index("over"), "reduced: over");
    for (const tab of [moving, still]) expect(await readAgain(tab)).toEqual([]);
    await expectSameEnd([{ label: "375px", moving: moving.page, still: still.page }]);
  } finally {
    await moving.context.close();
    await still.context.close();
  }
});
