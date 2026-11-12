import { expect, test } from "@playwright/test";

import {
  BEATS,
  expectReadMotion,
  expectSameEnd,
  firstRead,
  openLive,
  readAgain,
  readBeat,
} from "./liveMotion";

/**
 * LIVE's motion on each browser engine, in brief: at 375 px, a page with motion and one under
 * the reduced-motion preference read the first three beats of the synthetic Saturday (before
 * the kickoffs, the first match under way, the captain's goal with the vice's assist). The
 * first read and a read made again move nothing; each newer read moves once its GOL moments
 * have landed, within the screen and by transform and opacity alone; the page without motion
 * never moves; and both end with the same markup. The full day is live-motion.spec.ts's.
 */

const KICKOFF = BEATS.findIndex((beat) => beat.name === "kickoff");
const GOAL = BEATS.findIndex((beat) => beat.name === "goal");

test("LIVE moves once per newer read at 375px on every engine", async ({ browser }) => {
  test.slow();
  const moving = await openLive(browser, { width: 375, motion: true });
  const still = await openLive(browser, { width: 375, motion: false });
  try {
    for (const tab of [moving, still]) expect(await firstRead(tab)).toEqual([]);
    for (const index of [KICKOFF, GOAL]) {
      const beat = BEATS[index]!;
      expectReadMotion(await readBeat(moving, index), beat.name, `motion: ${beat.name}`);
      expect((await readBeat(still, index)).started, `reduced: ${beat.name}`).toEqual([]);
    }
    for (const tab of [moving, still]) expect(await readAgain(tab)).toEqual([]);
    await expectSameEnd([{ label: "375px", moving: moving.page, still: still.page }]);
  } finally {
    await moving.context.close();
    await still.context.close();
  }
});
