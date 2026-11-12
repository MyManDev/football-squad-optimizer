import { expect, test, type TestInfo } from "@playwright/test";

import {
  BEATS,
  expectReadMotion,
  expectSameEnd,
  firstRead,
  LAST_BEAT,
  openLive,
  readAgain,
  readBeat,
  type LiveTab,
  type Scheme,
} from "./liveMotion";

/**
 * LIVE moves once when a newer read is drawn (liveMotion.ts), on a phone: the synthetic
 * Saturday's eight reads, one per Yenile, on two pages side by side, one with motion and one
 * under the reduced-motion preference. With motion, each newer read moves only after the GOL
 * board's moments have landed, and is held in the frame that draws it: at 0, 100, 200 and
 * 300 ms of its run nothing scrolls sideways or overflows, only transform and opacity move,
 * nothing loops, at most six rows show their own changes, and the heading's light breathes
 * three times while one of the member's rows is played. The first read and a read made again
 * move nothing, the page without motion never moves, and both pages end with the same markup.
 *
 * With `LIVE_MOTION_SHOTS` set, the 375 and 390 px runs also read the day in the night palette,
 * save each beat at rest, and keep a video of the 390 px page with motion.
 */

/** The beats read a second time, each once its own read has moved. */
const READ_AGAIN = new Set(["before", "goal", "bonus"]);

const shotsAt = (width: number) =>
  Boolean(process.env.LIVE_MOTION_SHOTS) && (width === 375 || width === 390);

const nameOf = (tab: LiveTab) => `${tab.scheme} ${tab.motion ? "motion" : "reduced"}`;

async function shoot(tab: LiveTab, width: number, index: number, testInfo: TestInfo) {
  const name = `${width}-${nameOf(tab).replace(" ", "-")}-${index}-${BEATS[index]!.name}.png`;
  await tab.page.screenshot({ path: testInfo.outputPath(name), fullPage: true });
}

for (const width of [320, 375, 390]) {
  test(`LIVE moves once per newer read at ${width}px and ends as it does without motion`, async ({
    browser,
  }, testInfo) => {
    test.slow();
    const shots = shotsAt(width);
    if (shots) test.setTimeout(testInfo.timeout * 2);
    const schemes: Scheme[] = shots ? ["light", "dark"] : ["light"];
    const tabs: LiveTab[] = [];
    try {
      for (const scheme of schemes) {
        for (const motion of [true, false]) {
          const filmed = shots && width === 390 && motion && scheme === "light";
          tabs.push(
            await openLive(browser, {
              width,
              motion,
              scheme,
              video: filmed ? testInfo.outputPath("video") : null,
            }),
          );
        }
      }
      for (const tab of tabs) {
        expect(await firstRead(tab), `${nameOf(tab)}: the first read`).toEqual([]);
        if (shots) await shoot(tab, width, 0, testInfo);
        if (READ_AGAIN.has(BEATS[0]!.name)) {
          expect(await readAgain(tab), `${nameOf(tab)}: the first read again`).toEqual([]);
        }
      }
      for (let index = 1; index <= LAST_BEAT; index += 1) {
        const beat = BEATS[index]!;
        for (const tab of tabs) {
          const label = `${nameOf(tab)}: ${beat.name}`;
          const result = await readBeat(tab, index);
          if (tab.motion) expectReadMotion(result, beat.name, label);
          else expect(result.started, label).toEqual([]);
          if (shots) await shoot(tab, width, index, testInfo);
          if (READ_AGAIN.has(beat.name)) {
            expect(await readAgain(tab), `${label} read again`).toEqual([]);
          }
        }
      }
      await expectSameEnd(
        schemes.map((scheme) => {
          const [moving, still] = tabs.filter((tab) => tab.scheme === scheme);
          return { label: `${width}px ${scheme}`, moving: moving!.page, still: still!.page };
        }),
      );
    } finally {
      for (const tab of tabs) await tab.context.close();
    }
  });
}
