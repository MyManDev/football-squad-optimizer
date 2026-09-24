import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

import { MESSAGES } from "../src/i18n/messages";
import { mockEntryAdviceEnvelope } from "../src/fixtures/league";
import type { AdvicePlayer, EntryAdvice } from "../src/features/league/types";
import { installLeagueMocks } from "./leagueMocks";

const ENTRY = 35249001;
const copy = MESSAGES.tr;

/** The mocked member's one-week plan, as the page receives it. */
const PLAN = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);

/**
 * The same plan shaped like a published week with two moves (GW6 carried two): the first
 * two outfield players of the eleven come in for two who leave, each move a share of the
 * gain. Only the moves change; the eleven, the armband and the bench are the mock's.
 */
function twoMoves(): typeof PLAN {
  const eleven = PLAN.payload.starting_xi!;
  const incoming = eleven.filter((player) => player.position !== "GK").slice(0, 2);
  const leaving = (player: AdvicePlayer, index: number): AdvicePlayer => ({
    ...player,
    player_id: 900_000 + index,
    name: `Leaving Player ${index + 1}`,
    short_name: `Leaving ${index + 1}`,
  });
  const payload: EntryAdvice = {
    ...PLAN.payload,
    moves: incoming.map((player, index) => ({
      move_id: `two-${index}`,
      player_out: leaving(player, index),
      player_in: player,
      expected_points_delta: index === 0 ? 2.36 : 0.65,
      reason_code: "points_gain",
    })),
    expected_gain_vs_hold: 3.01,
    transfer_hit_points: 0,
    solver_status: "OPTIMAL",
  };
  return { ...PLAN, payload };
}

async function open(page: Page, width: number, height: number, plan = PLAN) {
  await page.setViewportSize({ width, height });
  await installLeagueMocks(page);
  await page.route(`**/data/league/advice/${ENTRY}/saf-puan/1.json`, (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(plan) }),
  );
  await page.route("**/api/v1/**", (route) => route.abort("connectionrefused"));
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
  await page.goto(`/league/members/${ENTRY}`);
  await expect(
    page.getByRole("heading", { name: copy.leagueMembers.squadAfterTitle }),
  ).toBeVisible();
}

type Box = { x: number; y: number; width: number; height: number };
const centre = (box: Box) => ({ x: box.x + box.width / 2, y: box.y + box.height / 2 });

/** The plates of one line of the pitch, in the published order. */
async function plates(pitch: Locator, line: string): Promise<Box[]> {
  const item = pitch.locator(`[role="listitem"][aria-label="${line}"]`);
  const boxes: Box[] = [];
  for (const plate of await item.locator("[title]").all()) {
    // The title is on the name; the plate is its parent.
    boxes.push((await plate.locator("xpath=..").boundingBox())!);
  }
  return boxes;
}

const mean = (values: number[]) => values.reduce((sum, value) => sum + value, 0) / values.length;

for (const [width, height, across] of [
  [1440, 900, true],
  [1366, 768, true],
  [820, 1180, false],
  [390, 844, false],
] as const) {
  test(`the midfield stands on the halfway line and the attack is named under the first defender at ${width}x${height}`, async ({
    page,
  }, testInfo) => {
    await open(page, width, height);
    const pitch = page.getByRole("list", { name: copy.squad.pitchLabel });
    await pitch.scrollIntoViewIfNeeded();
    const field = (await pitch.boundingBox())!;
    const half = centre(field);
    // Drawn across from 640 px of pitch, upright under that, and described that way.
    expect(field.width >= 640).toBe(across);
    await expect(pitch).toHaveAccessibleDescription(
      across ? copy.leagueMembers.pitchHorizontal : copy.leagueMembers.pitchVertical,
    );

    const [keeper, defence, midfield, attack] = await Promise.all(
      ["GK", "DEF", "MID", "FWD"].map((line) => plates(pitch, line)),
    );
    const axis = (box: Box) => (across ? centre(box).x : centre(box).y);
    const halfway = across ? half.x : half.y;
    // Every midfielder's centre is on the halfway line.
    for (const plate of midfield!) expect(Math.abs(axis(plate) - halfway)).toBeLessThanOrEqual(1);
    // The defence and the attack stand at mirrored distances from it, the keeper at the own
    // goal: left across the pitch, at the bottom upright.
    const toDefence = Math.abs(mean(defence!.map(axis)) - halfway);
    const toAttack = Math.abs(mean(attack!.map(axis)) - halfway);
    expect(Math.abs(toDefence - toAttack)).toBeLessThanOrEqual(1);
    const own = across ? -1 : 1;
    expect(Math.sign(mean(defence!.map(axis)) - halfway)).toBe(own);
    expect(Math.sign(mean(keeper!.map(axis)) - mean(defence!.map(axis)))).toBe(own);
    // Each line is symmetric about the pitch's axis.
    const across2 = (box: Box) => (across ? centre(box).y : centre(box).x);
    const other = across ? half.y : half.x;
    for (const line of [defence!, midfield!, attack!])
      expect(Math.abs(mean(line.map(across2)) - other)).toBeLessThanOrEqual(1);

    // 'Hücum yönü' sits directly under the first defender in the published order (or under
    // the whole defence where four or more crowd it across the pitch).
    const label = page.getByText(copy.leagueMembers.attackDirection, { exact: true });
    await expect(label).toHaveCount(defence!.length >= 4 ? 2 : 1);
    const shown = label.locator("visible=true");
    await expect(shown).toHaveCount(1);
    const under = across && defence!.length >= 4 ? defence!.at(-1)! : defence![0]!;
    const box = (await shown.boundingBox())!;
    expect(box.y - (under.y + under.height)).toBeGreaterThanOrEqual(0);
    expect(box.y - (under.y + under.height)).toBeLessThanOrEqual(8);
    expect(box.x < under.x + under.width && box.x + box.width > under.x).toBe(true);
    // It is on a white plate inside the pitch, not over another player.
    expect(box.x).toBeGreaterThanOrEqual(field.x);
    expect(box.x + box.width).toBeLessThanOrEqual(field.x + field.width);
    for (const plate of [...keeper!, ...defence!, ...midfield!, ...attack!]) {
      const overlaps =
        box.x < plate.x + plate.width &&
        box.x + box.width > plate.x &&
        box.y < plate.y + plate.height &&
        box.y + box.height > plate.y;
      expect(overlaps).toBe(false);
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true);
    await pitch.screenshot({ path: testInfo.outputPath(`pitch-${width}.png`) });
  });
}

test("a two-move week fits the owner's laptop: the decision above 640, the pitch, bench and honesty above 900", async ({
  page,
}, testInfo) => {
  await open(page, 1440, 900, twoMoves());
  const decision = page.locator('[data-mark="decision"]');
  await expect(decision.getByRole("article")).toHaveCount(2);
  const bottom = async (locator: Locator) => {
    const box = (await locator.boundingBox())!;
    return box.y + box.height;
  };
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  expect(await bottom(decision)).toBeLessThanOrEqual(640);
  for (const mark of ["pitch", "bench", "honesty"])
    expect(await bottom(page.locator(`[data-mark="${mark}"]`)), mark).toBeLessThanOrEqual(900);
  // The fixtures are a column of their own at the window's right edge, as tall as it.
  const rail = (await page
    .getByRole("complementary", { name: copy.shell.fixtures })
    .boundingBox())!;
  expect(rail.width).toBe(340);
  expect(rail.x + rail.width).toBe(1440);
  expect(rail.y).toBe(0);
  expect(rail.height).toBe(900);
  const blocking = (await new AxeBuilder({ page }).analyze()).violations.filter((violation) =>
    ["serious", "critical"].includes(violation.impact ?? ""),
  );
  expect(blocking).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("member-1440.png") });

  // A small laptop keeps the whole decision above its 640 px line.
  await page.setViewportSize({ width: 1366, height: 768 });
  await expect.poll(async () => bottom(decision)).toBeLessThanOrEqual(640);
});
