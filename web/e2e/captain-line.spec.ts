import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

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

const ROOT = fileURLToPath(new URL("../public/data/league", import.meta.url));
const WIDTHS = [360, 375, 390] as const;

const read = (relative: string) => JSON.parse(readFileSync(join(ROOT, relative), "utf-8"));

type Published = { entry: number; strategy: string; window: number; armband: boolean };

/** Each page the published indexes offer, and whether its plan names a captain and a vice. */
function publishedPages(): Map<number, Published[]> {
  const pages = new Map<number, Published[]>();
  if (!existsSync(join(ROOT, "members.json"))) return pages;
  for (const member of read("members.json").payload.members) {
    if (member.member_kind !== "human") continue;
    const entry = member.entry_id as number;
    const index = `advice/${entry}/index.json`;
    if (!existsSync(join(ROOT, index))) continue;
    const windows = (read(index).payload.windows ?? {}) as Record<string, number[]>;
    pages.set(
      entry,
      Object.entries(windows).flatMap(([strategy, sizes]) =>
        sizes.map((window) => {
          const plan = `advice/${entry}/${strategy}/${window}.json`;
          const payload = existsSync(join(ROOT, plan)) ? read(plan).payload : null;
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
  return pages;
}

const PAGES = publishedPages();

test("the published tree has members to check", () => {
  test.skip(!existsSync(join(ROOT, "members.json")), "No league tree is published here.");
  expect(PAGES.size).toBeGreaterThan(0);
  expect([...PAGES.values()].flat().filter((page) => page.armband).length).toBeGreaterThan(0);
});

for (const language of ["tr", "en"] as const) {
  for (const [entry, pages] of PAGES) {
    test(`the captain line holds one line on a phone for ${entry} in ${language}`, async ({
      page,
    }) => {
      await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
      await page.route("**/api/v1/**", (route) => route.abort("connectionrefused"));
      for (const { strategy, window, armband } of pages) {
        if (!armband) continue;
        await page.setViewportSize({ width: WIDTHS[0], height: 800 });
        await page.goto(`/league/members/${entry}?mode=${strategy}&window=${window}`);
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
