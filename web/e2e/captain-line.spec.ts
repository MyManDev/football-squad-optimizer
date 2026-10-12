import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import { shippedTrees } from "../src/testSupport/shippedTrees";

/**
 * The decision's captain line on a phone, over the published tree rather than the example
 * plan: every published member, every strategy and window their index offers, at the three
 * common phone widths. The armband and the vice-captain stay on one line, nothing spills
 * past the line's edge and no type in it is smaller than 12 px.
 *
 * GW6 showed why the example plan is not enough: member 3832237's three and five week plans
 * captain Semenyo (MCI, 4,79 xP) with Magalhães as vice, and that pair wrapped at 360 px
 * while every other member's fitted.
 */

const WIDTHS = [360, 375, 390] as const;

type Published = { entry: number; strategy: string; window: number; armband: boolean };

/** Each page a tree's indexes offer, and whether its plan names a captain and a vice. */
function publishedPages(root: string): { leagueId: number; pages: Map<number, Published[]> } {
  const read = (relative: string) => JSON.parse(readFileSync(join(root, relative), "utf-8"));
  const members = read("members.json").payload;
  const pages = new Map<number, Published[]>();
  for (const member of members.members) {
    if (member.member_kind !== "human") continue;
    const entry = member.entry_id as number;
    const index = `advice/${entry}/index.json`;
    if (!existsSync(join(root, index))) continue;
    const windows = (read(index).payload.windows ?? {}) as Record<string, number[]>;
    pages.set(
      entry,
      Object.entries(windows).flatMap(([strategy, sizes]) =>
        sizes.map((window) => {
          const plan = `advice/${entry}/${strategy}/${window}.json`;
          const payload = existsSync(join(root, plan)) ? read(plan).payload : null;
          return {
            entry,
            strategy,
            window,
            armband: !!payload?.captain && !!payload?.vice_captain,
          };
        }),
      ),
    );
  }
  return { leagueId: members.league_id as number, pages };
}

// Every tree the site lists, each member and each page its index offers.
const TREES = shippedTrees().map(({ root }) => publishedPages(root));

test("the published trees have members to check", () => {
  for (const { pages } of TREES) {
    expect(pages.size).toBeGreaterThan(0);
    expect([...pages.values()].flat().filter((page) => page.armband).length).toBeGreaterThan(0);
  }
});

for (const language of ["tr", "en"] as const) {
  for (const [LEAGUE_ID, entry, pages] of TREES.flatMap(({ leagueId, pages }) =>
    [...pages].map(([entry, rows]) => [leagueId, entry, rows] as const),
  )) {
    test(`the captain line holds one line on a phone for ${entry} of ${LEAGUE_ID} in ${language}`, async ({
      page,
    }) => {
      await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
      await page.route("**/api/v1/**", (route) => route.abort("connectionrefused"));
      for (const { strategy, window, armband } of pages) {
        if (!armband) continue;
        await page.setViewportSize({ width: WIDTHS[0], height: 800 });
        await page.goto(`/league/${LEAGUE_ID}/members/${entry}?mode=${strategy}&window=${window}`);
        const line = page.locator('[data-mark="decision"] p[class*="_captain_"]');
        await expect(line).toBeVisible();
        // The club codes come from the calendar, and the widths from the page's own faces:
        // measure once both have arrived, so nothing moves between two readings.
        await expect(page.locator('[data-mark="rail-xi"]')).toBeAttached();
        await page.evaluate(async () => {
          await Promise.all([...document.fonts].map((face) => face.load().catch(() => undefined)));
          await document.fonts.ready;
        });
        for (const width of WIDTHS) {
          await page.setViewportSize({ width, height: 800 });
          const reading = await line.evaluate((element) => {
            const box = element.getBoundingClientRect();
            const armbands = [...element.children].map((child) => child.getBoundingClientRect());
            // Centred in one row, the armbands overlap vertically; wrapped, the second
            // starts below the first ends.
            return {
              oneLine:
                Math.max(...armbands.map((band) => band.top)) <
                Math.min(...armbands.map((band) => band.bottom)),
              spill: Math.max(...armbands.map((band) => band.right)) - box.right,
              smallest: Math.min(
                ...[element, ...element.querySelectorAll("*")].map((node) =>
                  parseFloat(getComputedStyle(node).fontSize),
                ),
              ),
              sideways: document.documentElement.scrollWidth > document.documentElement.clientWidth,
            };
          });
          const where = `${entry} ${strategy} ${window} at ${width} px`;
          expect(reading.oneLine, `${where}: the armbands share one line`).toBe(true);
          expect(reading.spill, `${where}: nothing spills past the line`).toBeLessThanOrEqual(0.5);
          expect(reading.smallest, `${where}: no type under 12 px`).toBeGreaterThanOrEqual(12);
          expect(reading.sideways, `${where}: no sideways scroll`).toBe(false);
        }
      }
    });
  }
}
