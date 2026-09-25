import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

import { MESSAGES } from "../src/i18n/messages";
import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../src/fixtures/league";
import type { AdvicePlayer, EntryAdvice } from "../src/features/league/types";
import { installLeagueMocks, openCalendar } from "./leagueMocks";

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

/**
 * The open calendar with the week's round filled in: every club of the plan plays, under a
 * three-letter short name, so the plates print club codes as the published calendar gives
 * them (the mock's clubs are not the league's, so no static code would name them).
 */
function codedCalendar() {
  const calendar = openCalendar();
  const players = [...PLAN.payload.starting_xi!, ...(PLAN.payload.bench ?? [])];
  const teams = [...new Set(players.map((player) => player.team))].map((name, index) => ({
    team_id: index + 1,
    name,
    short_name: name
      .replace(/[^A-Za-z]/g, "")
      .slice(0, 3)
      .toUpperCase(),
  }));
  if (teams.length % 2 === 1) teams.push({ team_id: 99, name: "Visitors", short_name: "VIS" });
  const fixtures = teams
    .filter((_, index) => index % 2 === 0)
    .map((home, index) => ({
      fixture_id: index + 1,
      kickoff_utc: null,
      home,
      away: teams[index * 2 + 1]!,
      finished: false,
      home_score: null,
      away_score: null,
    }));
  const [week] = calendar.payload.gameweeks;
  return { ...calendar, payload: { ...calendar.payload, gameweeks: [{ ...week!, fixtures }] } };
}

/**
 * Opens the member page on the mocked week. `live` serves the squad and the plan as a live
 * capture rather than example data, as the real GW6 week is, so no example-data tag takes
 * a line of its own where the fold is measured.
 */
async function open(page: Page, width: number, height: number, plan = PLAN, live = false) {
  await page.setViewportSize({ width, height });
  await installLeagueMocks(page);
  await page.route("**/data/fixtures.json", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(codedCalendar()) }),
  );
  const served = live ? { ...plan, source_kind: "live" as const } : plan;
  await page.route(`**/data/league/advice/${ENTRY}/saf-puan/1.json`, (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(served) }),
  );
  if (live)
    await page.route(`**/data/league/entries/${ENTRY}.json`, (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ ...mockEntrySquadEnvelopes[ENTRY]!, source_kind: "live" }),
      }),
    );
  await page.route("**/api/v1/**", (route) => route.abort("connectionrefused"));
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
  await page.goto(`/league/members/${ENTRY}`);
  await expect(
    page.getByRole("heading", { name: copy.leagueMembers.squadAfterTitle }),
  ).toBeVisible();
  // Measure once the calendar has arrived (the plates' codes and the rail come from it)
  // and the fonts have loaded, so nothing moves between two readings.
  await expect(page.locator('[data-mark="rail-xi"]')).toBeAttached();
  // Ask for every face the stylesheet declares rather than only those already requested:
  // on a slow runner `fonts.ready` can settle before a face starts loading, and a reading
  // taken in the fallback face moves text by a line.
  await page.evaluate(async () => {
    await Promise.all([...document.fonts].map((face) => face.load().catch(() => undefined)));
    await document.fonts.ready;
  });
}

type Box = { x: number; y: number; width: number; height: number };
const centre = (box: Box) => ({ x: box.x + box.width / 2, y: box.y + box.height / 2 });

/**
 * The plates of one line of the pitch, in the published order. The line is found by its
 * position code in `data-line`; its accessible name is the position word in the page language.
 */
async function plates(pitch: Locator, line: string): Promise<Box[]> {
  const item = pitch.locator(`[role="listitem"][data-line="${line.toLowerCase()}"]`);
  const boxes: Box[] = [];
  for (const plate of await item.locator("[title]").all()) {
    // The title is on the name; the plate is its parent.
    boxes.push((await plate.locator("xpath=..").boundingBox())!);
  }
  return boxes;
}

const mean = (values: number[]) => values.reduce((sum, value) => sum + value, 0) / values.length;

/**
 * What is wrong with the plates: an armband or YENİ that is not inside its plate across the
 * pitch, or not centred over it upright (so it could read as the next plate's), and a club
 * code cut short.
 */
async function plateFaults(pitch: Locator, across: boolean): Promise<string[]> {
  return pitch.evaluate(
    (list, { across, fresh }) => {
      const faults: string[] = [];
      for (const name of list.querySelectorAll("[title]")) {
        const plate = name.parentElement!;
        const own = plate.getBoundingClientRect();
        const tags = [...plate.children].filter(
          (child) => child.getAttribute("role") === "img" || child.textContent === fresh,
        );
        if (tags.length > 0) {
          const boxes = tags.map((tag) => tag.getBoundingClientRect());
          const left = Math.min(...boxes.map((tag) => tag.left));
          const right = Math.max(...boxes.map((tag) => tag.right));
          const fits = across
            ? left >= own.left - 0.5 && right <= own.right + 0.5
            : Math.abs((left + right) / 2 - (own.left + own.right) / 2) <= 1;
          if (!fits) faults.push(`tags of ${name.getAttribute("title")}`);
        }
        // A club the calendar does not name is printed by its name and may be cut short.
        const code = plate.querySelector("[class*='codeText']");
        if (code && /^[A-Z]{3}$/.test(code.textContent ?? "")) {
          if (code.scrollWidth > code.clientWidth + 0.5)
            faults.push(`club code of ${name.getAttribute("title")}`);
        } else faults.push(`no club code for ${name.getAttribute("title")}`);
      }
      return faults;
    },
    { across, fresh: copy.leagueMembers.boardNew },
  );
}

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
    // The armband and YENİ belong visibly to their own plate: inside it across the pitch,
    // centred over it upright, so neither reads as the next plate's. Every club code is
    // printed whole, however many share a line.
    expect(await plateFaults(pitch, across)).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true);
    await pitch.screenshot({ path: testInfo.outputPath(`pitch-${width}.png`) });
  });
}

test("a line of five on the smallest phone keeps every club code whole and every tag on its own plate", async ({
  page,
}, testInfo) => {
  // The two-move week's eleven drawn as 3-5-2: the same players, the positions by place.
  const shape = ["GK", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "MID", "FWD", "FWD"];
  const week = twoMoves();
  const payload: EntryAdvice = {
    ...week.payload,
    starting_xi: week.payload.starting_xi!.map((player, index) => ({
      ...player,
      position: shape[index] as AdvicePlayer["position"],
    })),
  };
  await open(page, 375, 667, { ...week, payload });
  const pitch = page.getByRole("list", { name: copy.squad.pitchLabel });
  await pitch.scrollIntoViewIfNeeded();
  await expect(pitch.locator('[role="listitem"][data-line="mid"] [title]')).toHaveCount(5);
  await expect(pitch.getByText(copy.leagueMembers.boardNew, { exact: true })).toHaveCount(2);
  expect(await plateFaults(pitch, false)).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await pitch.screenshot({ path: testInfo.outputPath("pitch-375-five.png") });
});

for (const [width, height] of [
  [1280, 720],
  [820, 1180],
] as const) {
  test(`the sidebar's 'Kadro' lands the squad's heading and toggle below the pinned top bar at ${width}x${height}`, async ({
    page,
  }) => {
    await open(page, width, height, twoMoves());
    const squadLink = page.locator("#sidebar nav").getByRole("link", { name: copy.shell.squad });
    await squadLink.click();
    await expect(page).toHaveURL(/#kadro$/);
    const heading = page.getByRole("heading", { name: copy.leagueMembers.squadAfterTitle });
    const toggle = page.getByRole("group", { name: copy.leagueMembers.viewLabel });
    const bar = page.locator("main header").first();
    await expect
      .poll(async () => {
        const [top, title, buttons] = await Promise.all(
          [bar, heading, toggle].map(async (locator) => (await locator.boundingBox())!),
        );
        return Math.min(title!.y, buttons!.y) >= top!.y + top!.height && title!.y < height;
      })
      .toBe(true);
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

test("a two-move week keeps the decision in a phone's first screen, the stamp beside the transfer facts", async ({
  page,
}, testInfo) => {
  await open(page, 390, 844, twoMoves(), true);
  const decision = page.locator('[data-mark="decision"]');
  const boards = decision.getByRole("article");
  await expect(boards).toHaveCount(2);
  const box = async (locator: Locator) => (await locator.boundingBox())!;
  const bottom = async (locator: Locator) => {
    const { y, height } = await box(locator);
    return y + height;
  };
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  // D-Phone-Bu-Hafta's lines: the boards and the captain above 548, the gain with its
  // stamp above 664 and the two honesty lines above 844, the whole first screen.
  expect(await bottom(boards.nth(1))).toBeLessThanOrEqual(548);
  // The captain line is the paragraph that names the vice-captain too (the gain's caption
  // also says 'kaptan').
  const captain = decision.locator("p").filter({
    has: page.getByText(copy.leagueMembers.viceCaptainLabel, { exact: true }),
  });
  expect(await bottom(captain)).toBeLessThanOrEqual(548);
  const stamp = decision.getByText(copy.leagueMembers.stampOptimal, { exact: true });
  const caption = decision.getByText(copy.leagueMembers.stampOptimalCaption, { exact: true });
  // When a runner draws the page taller than this machine does, say where: the bottom of
  // every block above the stamp, so a failure names the block that grew.
  const layout = await page.evaluate(() => {
    const at = (selector: string) => {
      const element = document.querySelector(selector);
      return element ? Math.round(element.getBoundingClientRect().bottom) : null;
    };
    const decision = document.querySelector('[data-mark="decision"]');
    const blocks = decision
      ? Array.from(decision.querySelectorAll(":scope > *, :scope > * > *")).map((element) => {
          const box = element.getBoundingClientRect();
          return `${element.tagName.toLowerCase()}.${String((element as HTMLElement).className).split(" ")[0]}:${Math.round(box.top)}-${Math.round(box.bottom)}`;
        })
      : [];
    return { phoneBar: at("body header"), topBar: at("main header"), blocks };
  });
  expect(await bottom(caption), JSON.stringify(layout)).toBeLessThanOrEqual(664);
  expect(await bottom(page.locator('[data-mark="honesty"]'))).toBeLessThanOrEqual(844);
  // The stamp stands beside the week's transfer facts, as the artboard draws it, after the
  // captain line and the gain figure.
  const facts = decision.locator("ul").filter({ hasText: copy.leagueMembers.hitPointsFact("0") });
  const [stampBox, factsBox, captainBox] = await Promise.all([
    box(stamp),
    box(facts),
    box(captain),
  ]);
  expect(factsBox.x).toBeGreaterThan(stampBox.x + stampBox.width);
  expect(Math.abs(centre(factsBox).y - centre(stampBox).y)).toBeLessThanOrEqual(8);
  expect(stampBox.y).toBeGreaterThan(captainBox.y + captainBox.height);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("member-390.png") });
});

for (const [width, height] of [
  [1440, 900],
  [1366, 768],
  [1280, 720],
] as const)
  test(`the sidebar's foot never covers Hesapla at ${width}x${height}`, async ({ page }) => {
    await open(page, width, height, twoMoves());
    const compute = page
      .locator("#sidebar")
      .getByRole("button", { name: copy.leagueMembers.computeButton, exact: true });
    await compute.scrollIntoViewIfNeeded();
    await expect(compute).toBeInViewport({ ratio: 1 });
    // Whatever stands at the button's centre is the button itself, not the pinned footer.
    expect(
      await compute.evaluate((button) => {
        const { left, top, width: w, height: h } = button.getBoundingClientRect();
        const hit = document.elementFromPoint(left + w / 2, top + h / 2);
        return hit === button || button.contains(hit);
      }),
    ).toBe(true);
    // The language switch stays reachable in the sidebar.
    await expect(page.locator("#sidebar").getByRole("button", { name: /^TR/ })).toBeAttached();
  });
