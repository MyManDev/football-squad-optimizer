import {
  expect,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
  type Response,
} from "@playwright/test";

import { exampleBundle } from "../src/fixtures/forwarder";
import { mockDefaultRival } from "../src/fixtures/league";
import { liveBeats, type BeatMoment, type BeatName } from "../src/testSupport/liveBeats";
import { TEST_WEEK, testWeek } from "../src/testSupport/liveWeek";
import { atRest } from "./atRest";
import { closedWeek, LISTED, LISTED_ENTRY, MARKED } from "./liveWeek";

/**
 * LIVE's motion (liveMotion.ts) in a browser: the synthetic Saturday of `liveBeats.ts` read
 * beat by beat through Yenile on the published league's LIVE page, the member's fifteen beside
 * a rival who holds the same fifteen with the armband on the vice. The capture's table and the
 * calendar are the synthetic week's own (`testWeek`), so every element id the beats name is in
 * the table. The forwarder answers the live week with the beat the test is on, however often it
 * is asked, so a followed read or a second Yenile only reads that beat again.
 *
 * The page's clock stands half an hour into the 15:00 match, so the follow window is open and
 * the heading's light shows while one of the member's rows is played. Every document is
 * synthetic.
 */

export const BEATS = liveBeats();
export const LAST_BEAT = BEATS.length - 1;

/** The beats whose board has one of the member's rows in a match being played. */
export const IN_PLAY: readonly BeatName[] = ["kickoff", "goal", "card", "over", "bonus"];

/** A read shows at most this many rows' own changes (liveMotion.ts, MOVING_ROWS). */
export const MOVING_ROWS = 6;

/**
 * What each newer read of the day moves, as the planner makes it (liveMotion.test.ts): the rows
 * it takes to another group, which slide there, and the rows that show their own changes, the
 * six that changed most.
 */
export const MOVES: Record<
  Exclude<BeatName, "before">,
  { moved: string[]; decorated: string[] }
> = {
  kickoff: { moved: ["1", "2", "3", "6", "7", "10"], decorated: [] },
  goal: { moved: [], decorated: ["10", "7"] },
  card: { moved: [], decorated: ["2"] },
  over: {
    moved: ["1", "2", "3", "4", "5", "6", "7", "8", "10", "11"],
    decorated: ["1", "2", "3", "6", "7", "10"],
  },
  bonus: { moved: [], decorated: ["10", "7", "6", "3", "4", "5"] },
  second: { moved: ["4", "5", "8", "11"], decorated: ["4", "5", "8", "11"] },
  final: { moved: ["9"], decorated: ["11", "13"] },
};

/** The times of a read's run at which its held motion is measured, past every delayed part. */
const FRAMES = [0, 200, 500, 800, 1100];

/** The member's rival in the published league: the same fifteen, the armband on the vice. */
const RIVAL = mockDefaultRival(LISTED_ENTRY)!;
const LIVE_PATH = `/league/${LISTED.league_id}/members/${LISTED_ENTRY}/live`;
const NOW = Date.parse("2026-11-21T15:30:00Z");
const HEIGHT: Record<number, number> = { 320: 640, 375: 812, 390: 844 };

/** Where each of the GOL board's moments is landed: its board, or a card's line. */
const MOMENT: Record<BeatMoment, string> = {
  goal: "[data-goal-board='goal']",
  assist: "[data-goal-board='assist']",
  card: "[data-goal-line='card']",
  substitution: "[data-goal-board='substitution']",
};

export type Scheme = "light" | "dark";

export interface LiveTab {
  page: Page;
  context: BrowserContext;
  motion: boolean;
  scheme: Scheme;
  /** The beat the forwarder answers the live week with. */
  server: { step: number };
}

/** One frame of a read's motion, held at `time` ms. */
export interface MotionFrame {
  time: number;
  /** How far the document is wider than the screen. */
  sideways: number;
  /** The rows and the rival block whose content is wider than their box. */
  wide: string[];
}

/** What a newer read moved, held where it was drawn. */
export interface ReadMotion {
  /** The animations on LIVE when the read was drawn. */
  held: number;
  frames: MotionFrame[];
  /** Every property the keyframes name. */
  properties: string[];
  /** The animations that never end. */
  endless: string[];
  /** The rows whose own parts move, the row's slide aside. */
  decorated: string[];
  /** The rows that slide, each as a whole. */
  slid: string[];
  /** The duel's ball rolls. */
  rolls: boolean;
}

export interface BeatResult {
  /** Every LIVE animation started while the beat was read and shown, in order. */
  started: string[];
  /** The rows whose place within the groups the read changed. */
  shifted: string[];
  /** Null on the page without motion. */
  motion: ReadMotion | null;
  /** The light's breaths, where it breathed. */
  breaths: number | null;
}

/** Each LIVE animation started, by script or by the stylesheet, is written down. */
function countLiveMotion() {
  const started: string[] = [];
  Object.defineProperty(window, "__liveStarted", { value: started });
  const onLive = (node: unknown): node is Element =>
    node instanceof Element && node.closest("[data-live-page]") !== null;
  const name = (node: Element) =>
    [
      node.tagName.toLowerCase(),
      ...node.getAttributeNames().filter((attribute) => attribute.startsWith("data-live")),
    ].join(" ");
  const animate = Element.prototype.animate;
  Element.prototype.animate = function (this: Element, keyframes, options) {
    const animation = animate.call(this, keyframes, options);
    if (onLive(this)) started.push(`script ${name(this)}`);
    return animation;
  };
  document.addEventListener(
    "animationstart",
    (event) => {
      if (onLive(event.target)) started.push(`css ${event.animationName}`);
    },
    true,
  );
}

const startedOn = (page: Page) =>
  page.evaluate(() => [...(window as unknown as { __liveStarted: string[] }).__liveStarted]);

/** The published league in the synthetic week, its live week answered with `server.step`'s beat. */
async function serveMatchDay(page: Page, server: { step: number }) {
  const week = testWeek();
  await closedWeek(page, week.fixtures, {
    ...week.table,
    gameweek: LISTED.gameweek,
    source_snapshot_id: LISTED.source_snapshot_id!,
  });
  const bundles = new Map([
    [
      `/entry/${LISTED_ENTRY}/bundle`,
      exampleBundle(LISTED_ENTRY, LISTED.gameweek, { ...week.member, entry_id: LISTED_ENTRY }),
    ],
    [
      `/entry/${RIVAL}/bundle`,
      exampleBundle(RIVAL, LISTED.gameweek, {
        ...week.member,
        entry_id: RIVAL,
        captain: 7,
        vice: 10,
      }),
    ],
  ]);
  await page.route("**/api/v1/fpl/**", (route) => {
    const { pathname, search } = new URL(route.request().url());
    const path = pathname.replace("/api/v1/fpl", "");
    const answer =
      path === `/live/${TEST_WEEK}` && search === "?view=activity"
        ? BEATS[server.step]!.document
        : search === `?gw=${LISTED.gameweek}`
          ? bundles.get(path)
          : undefined;
    if (answer === undefined) {
      return route.fulfill({ status: 404, headers: MARKED, body: '{"error":"not_found"}' });
    }
    return route.fulfill({ headers: MARKED, body: JSON.stringify(answer) });
  });
}

const liveRead = (response: Response) =>
  new URL(response.url()).pathname === `/api/v1/fpl/live/${TEST_WEEK}`;
const rivalRead = (response: Response) =>
  new URL(response.url()).pathname === `/api/v1/fpl/entry/${RIVAL}/bundle`;

/**
 * LIVE in a context of its own: `width` px wide, with motion or under the reduced-motion
 * preference, in the day or night palette, its video kept in `video` where one is named.
 */
export async function openLive(
  browser: Browser,
  {
    width,
    motion,
    scheme = "light",
    video = null,
  }: { width: number; motion: boolean; scheme?: Scheme; video?: string | null },
): Promise<LiveTab> {
  const size = { width, height: HEIGHT[width] ?? 844 };
  const context = await browser.newContext({
    viewport: size,
    reducedMotion: motion ? "no-preference" : "reduce",
    ...(video === null ? {} : { recordVideo: { dir: video, size } }),
  });
  const page = await context.newPage();
  await page.clock.install({ time: NOW });
  await page.addInitScript((palette) => {
    localStorage.setItem("squadopt.language", "tr");
    localStorage.setItem("squadopt.scheme", palette);
  }, scheme);
  await page.addInitScript(countLiveMotion);
  const server = { step: 0 };
  await serveMatchDay(page, server);
  await page.goto(LIVE_PATH);
  return { page, context, motion, scheme, server };
}

/** Two frames and a moment more: long enough for a motion a render starts to have begun. */
async function settle(page: Page) {
  await page.evaluate(
    () =>
      new Promise<void>((done) =>
        requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(done, 300))),
      ),
  );
}

/** The first read: the fifteen and the duel drawn, and nothing on LIVE moves. */
export async function firstRead(tab: LiveTab): Promise<string[]> {
  const { page } = tab;
  await expect(page.locator("[data-live-row]")).toHaveCount(15);
  await expect(page.locator("[data-live-page] time")).toHaveAttribute("datetime", BEATS[0]!.at);
  await expect(
    page.locator("[data-live-rival] [data-live-rival-net]:not([data-pending])"),
  ).toBeVisible();
  await expect(page.locator("[data-live-rival] [data-live-ball]")).toBeVisible();
  await settle(page);
  await atRest(page);
  return startedOn(page);
}

/** Yenile again on the beat shown: the same read comes back, and nothing on LIVE moves. */
export async function readAgain(tab: LiveTab): Promise<string[]> {
  const { page } = tab;
  const before = (await startedOn(page)).length;
  const answered = Promise.all([page.waitForResponse(liveRead), page.waitForResponse(rivalRead)]);
  await page.locator("[data-live-refresh]").click();
  await answered;
  await expect(page.locator("[data-live-refresh]")).not.toHaveAttribute("aria-disabled", "true");
  await settle(page);
  await atRest(page);
  return (await startedOn(page)).slice(before);
}

/**
 * Held in the frame that draws the beat's read: every animation on LIVE is paused where it
 * stands, and kept for the frames to come. Polled each frame, so nothing has run far.
 */
function holdWhenDrawn(at: string) {
  const live = document.querySelector("[data-live-page]");
  if (live === null || live.querySelector("time")?.getAttribute("datetime") !== at) return false;
  const held = document.getAnimations().filter((animation) => {
    const target = (animation.effect as KeyframeEffect | null)?.target;
    return target instanceof Element && live.contains(target);
  });
  for (const animation of held) animation.pause();
  (window as unknown as { __liveHeld: Animation[] }).__liveHeld = held;
  return true;
}

/** The held motion at `times` ms of its run, and what it is made of. */
function framesOf(times: number[]): ReadMotion {
  const held = (window as unknown as { __liveHeld: Animation[] }).__liveHeld;
  const live = document.querySelector("[data-live-page]")!;
  const boxes = [...live.querySelectorAll<HTMLElement>("[data-live-row], [data-live-rival]")];
  const target = (animation: Animation) => (animation.effect as KeyframeEffect).target!;
  const describe = (node: Element) =>
    [
      node.tagName.toLowerCase(),
      ...node
        .getAttributeNames()
        .filter((name) => name.startsWith("data-live"))
        .map((name) => `${name}=${node.getAttribute(name)}`),
    ].join(" ");
  const frames = times.map((time) => {
    for (const animation of held) animation.currentTime = time;
    return {
      time,
      sideways: document.documentElement.scrollWidth - window.innerWidth,
      wide: boxes
        .filter((box) => box.scrollWidth > box.clientWidth)
        .map((box) => `${describe(box)}: ${box.scrollWidth} > ${box.clientWidth}`),
    };
  });
  const properties = new Set<string>();
  for (const animation of held) {
    for (const keyframe of (animation.effect as KeyframeEffect).getKeyframes()) {
      for (const property of Object.keys(keyframe)) properties.add(property);
    }
  }
  for (const timing of ["offset", "computedOffset", "easing", "composite"]) {
    properties.delete(timing);
  }
  const decorated = new Set<string>();
  const slid = new Set<string>();
  for (const animation of held) {
    const node = target(animation);
    const row = node.closest<HTMLElement>("[data-live-row]");
    if (row === null) continue;
    if (row !== node) decorated.add(row.dataset.liveRow!);
    else if (
      (animation.effect as KeyframeEffect)
        .getKeyframes()
        .some((frame) => String(frame.transform).includes("translateY"))
    ) {
      slid.add(row.dataset.liveRow!);
    }
  }
  return {
    held: held.length,
    frames,
    properties: [...properties].sort(),
    endless: held
      .filter((animation) => animation.effect?.getTiming().iterations === Infinity)
      .map((animation) => describe(target(animation))),
    decorated: [...decorated],
    slid: [...slid],
    rolls: held.some((animation) => target(animation).matches("[data-live-lane]")),
  };
}

/** Each row's top within the groups, by its element id. */
function rowPlaces(): Record<string, number> {
  const rows = [...document.querySelectorAll<HTMLElement>("[data-live-page] [data-live-row]")];
  const origin = rows[0]?.closest("section")?.parentElement?.getBoundingClientRect().top ?? 0;
  return Object.fromEntries(
    rows.map((row) => [row.dataset.liveRow!, row.getBoundingClientRect().top - origin]),
  );
}

/**
 * The held motion plays on from where it was left; one brought to its end ends there (played,
 * it would start again), and one that would never end is stopped, its count already taken.
 */
function playHeld() {
  const page = window as unknown as { __liveHeld: Animation[] };
  for (const animation of page.__liveHeld) {
    if (animation.effect?.getTiming().iterations === Infinity) animation.cancel();
    else if (animation.playState === "paused") {
      const end = animation.effect?.getComputedTiming().endTime;
      if (typeof end === "number" && Number(animation.currentTime) >= end) animation.finish();
      else animation.play();
    }
  }
  page.__liveHeld = [];
}

/**
 * The light's three breaths, once they have started: their count, and then they are brought to
 * their end at once, so the beat does not wait 4.2 s for them. An endless light is stopped, for
 * the count to say so.
 */
async function finishBreaths(page: Page): Promise<number> {
  const breaths = await page.waitForFunction(
    () => {
      const live = document.querySelector("[data-live-page]");
      const breath = document
        .getAnimations()
        .find(
          (animation) =>
            animation instanceof CSSAnimation &&
            animation.animationName.includes("live-breath") &&
            live?.contains((animation.effect as KeyframeEffect | null)?.target ?? null),
        );
      if (breath === undefined) return false;
      const iterations = breath.effect?.getTiming().iterations ?? 0;
      if (Number.isFinite(iterations)) breath.finish();
      else breath.cancel();
      return { iterations };
    },
    undefined,
    { polling: "raf" },
  );
  // Resolved only once the page function gave its object.
  const { iterations } = (await breaths.jsonValue()) as { iterations: number };
  return iterations;
}

/**
 * Once the board or line `selector` names is up: the read LIVE shows then, and how many LIVE
 * animations had started, both from the frame it rose in.
 */
function raisedOver(selector: string) {
  if (document.querySelector(selector) === null) return false;
  return {
    shown: document.querySelector("[data-live-page] time")?.getAttribute("datetime") ?? null,
    started: (window as unknown as { __liveStarted: string[] }).__liveStarted.length,
  };
}

/**
 * A tap that lands a GOL moment: on its board, its card line or the still line's close. One
 * that went down by itself before the tap reached it has landed all the same.
 */
async function land(target: Locator) {
  try {
    await target.click({ timeout: 5_000 });
  } catch (error) {
    if ((await target.count()) > 0) throw error;
  }
}

/**
 * The beat at `index` read through Yenile, its GOL moments landed (each board or card line on
 * the page with motion; the still line closed without it), until its read is drawn and LIVE is
 * at rest. With motion, the read's motion is held in the frame that draws it and measured at 0,
 * 200, 500, 800 and 1100 ms of its run, past every part's delay, before it plays out.
 */
export async function readBeat(tab: LiveTab, index: number): Promise<BeatResult> {
  const { page, motion } = tab;
  const beat = BEATS[index]!;
  const before = (await startedOn(page)).length;
  const shownBefore = await page.locator("[data-live-page] time").getAttribute("datetime");
  const placesBefore = await page.evaluate(rowPlaces);
  const drawn = motion ? page.waitForFunction(holdWhenDrawn, beat.at, { polling: "raf" }) : null;
  // Awaited below; a failure before then must not go unhandled.
  drawn?.catch(() => undefined);
  tab.server.step = index;
  const answered = page.waitForResponse(liveRead);
  await page.locator("[data-live-refresh]").click();
  await answered;
  if (motion) {
    for (const [order, moment] of beat.moments.entries()) {
      const raised = await page.waitForFunction(raisedOver, MOMENT[moment], { polling: "raf" });
      const under = await raised.jsonValue();
      // In the frame the first board rises, the read waits under it: LIVE still shows the read
      // before, and nothing on it has moved for the new one.
      if (order === 0) {
        expect(under, `${beat.name}: under the board`).toEqual({
          shown: shownBefore,
          started: before,
        });
      }
      await land(page.locator(MOMENT[moment]));
    }
  } else if (beat.moments.length > 0) {
    // One still line says the read's moments, and LIVE has taken the read at once.
    const still = page.locator("[data-goal-still]");
    await expect(still.locator("p > span")).toHaveCount(beat.moments.length);
    await land(still.getByRole("button", { name: "Kapat" }));
    await expect(still).toHaveCount(0);
  }
  await expect(page.locator("[data-live-page] time")).toHaveAttribute("datetime", beat.at);
  let measured: ReadMotion | null = null;
  let breaths: number | null = null;
  if (drawn !== null) {
    await drawn;
    measured = await page.evaluate(framesOf, FRAMES);
    if (IN_PLAY.includes(beat.name)) breaths = await finishBreaths(page);
    await page.evaluate(playHeld);
  }
  await atRest(page);
  const placesAfter = await page.evaluate(rowPlaces);
  const shifted = Object.keys(placesAfter).filter(
    (id) => id in placesBefore && Math.abs(placesAfter[id]! - placesBefore[id]!) >= 1,
  );
  return { started: (await startedOn(page)).slice(before), shifted, motion: measured, breaths };
}

/**
 * The checks every newer read's motion passes: each row whose place within the groups the read
 * changed slides, and the rows that show their own changes are the planner's, at most six; nothing scrolls
 * sideways or overflows a row or the rival block in any held frame, only transform and opacity
 * move, nothing loops, and the light breathes three times exactly when one of the member's
 * rows is played.
 */
export function expectReadMotion(result: BeatResult, name: BeatName, label: string) {
  const motion = result.motion!;
  expect(motion.held, `${label}: something moves`).toBeGreaterThan(0);
  // A row whose place within the groups changed slides there; one that changed group and kept
  // its place (the whole group taking its head at the first kickoff) has nothing to slide.
  for (const id of result.shifted) expect(motion.slid, `${label}: row ${id} slides`).toContain(id);
  if (name !== "before") {
    expect([...motion.decorated].sort(), `${label}: the rows showing their changes`).toEqual(
      [...MOVES[name].decorated].sort(),
    );
  }
  for (const frame of motion.frames) {
    expect(frame.sideways, `${label} at ${frame.time} ms: sideways scroll`).toBeLessThanOrEqual(0);
    expect(frame.wide, `${label} at ${frame.time} ms: wider than its box`).toEqual([]);
  }
  expect(
    motion.properties.filter((property) => property !== "transform" && property !== "opacity"),
    `${label}: keyframes`,
  ).toEqual([]);
  expect(motion.endless, `${label}: endless`).toEqual([]);
  expect(motion.decorated.length, `${label}: rows decorated`).toBeLessThanOrEqual(MOVING_ROWS);
  const breathing = result.started.filter((entry) => entry.includes("live-breath"));
  if (IN_PLAY.includes(name)) expect(result.breaths, `${label}: breaths`).toBe(3);
  else expect(breathing, `${label}: the light stands still`).toEqual([]);
  // The captain's goal puts the member ahead of the rival: the duel's ball rolls to his side.
  if (name === "goal") expect(motion.rolls, `${label}: the duel's ball rolls`).toBe(true);
}

/** Where the parts the visitor may read stand: each row and heading's top, the bar, the scroll. */
function readingPlaces() {
  const live = document.querySelector("[data-live-page]")!;
  const bar = document.querySelector("[data-phone-bar]")?.getBoundingClientRect().bottom ?? 0;
  const parts = [...live.querySelectorAll<HTMLElement>("[data-live-row], [data-live-group]")].map(
    (node) => ({
      part:
        node.dataset.liveRow === undefined
          ? `group:${node.dataset.liveGroup}`
          : `row:${node.dataset.liveRow}`,
      top: node.getBoundingClientRect().top,
    }),
  );
  const groupsTop = Math.min(...parts.map(({ top }) => top));
  return { bar, groupsTop, scrollY: window.scrollY, parts };
}

/**
 * The visitor reads past the groups' top while a read lands: scrolled to the page's foot, the
 * groups' top under the phone bar, and the beat at `index` read with Yenile pressed where it
 * stands, out of sight, so nothing scrolls it into view; its moments landed, LIVE at rest. The
 * first row or heading that stood wholly below the bar, and that the read neither took to
 * another group nor took away, stands where it stood on the screen, though the read moved it
 * in the page: the page made up for what changed above it.
 */
export async function expectPlaceKept(tab: LiveTab, index: number, label: string) {
  const { page, motion } = tab;
  const beat = BEATS[index]!;
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  // A scroll this recent is the visitor's, and the page keeps its hands off: wait it out.
  await page.waitForTimeout(400);
  const before = await page.evaluate(readingPlaces);
  expect(before.groupsTop, `${label}: the groups' top is under the bar`).toBeLessThan(before.bar);
  tab.server.step = index;
  const answered = page.waitForResponse(liveRead);
  await page.locator("[data-live-refresh]").dispatchEvent("click");
  await answered;
  if (motion) {
    for (const moment of beat.moments) {
      await page.waitForFunction(raisedOver, MOMENT[moment], { polling: "raf" });
      await land(page.locator(MOMENT[moment]));
    }
  } else if (beat.moments.length > 0) {
    await land(page.locator("[data-goal-still]").getByRole("button", { name: "Kapat" }));
  }
  await expect(page.locator("[data-live-page] time")).toHaveAttribute("datetime", beat.at);
  if (motion && IN_PLAY.includes(beat.name)) await finishBreaths(page);
  await atRest(page);
  const after = await page.evaluate(readingPlaces);
  const now = new Map(after.parts.map(({ part, top }) => [part, top]));
  const moved = new Set(
    beat.name === "before" ? [] : MOVES[beat.name].moved.map((id) => `row:${id}`),
  );
  const read = before.parts
    .filter(({ top }) => top >= before.bar)
    .sort((a, b) => a.top - b.top)
    .find(({ part }) => !moved.has(part) && now.has(part));
  expect(read, `${label}: a part to read below the bar`).toBeDefined();
  const top = now.get(read!.part)!;
  expect(Math.abs(top - read!.top), `${label}: ${read!.part} stays on the screen`).toBeLessThan(1);
  const shifted = top + after.scrollY - (read!.top + before.scrollY);
  expect(Math.abs(shifted), `${label}: ${read!.part} moved in the page`).toBeGreaterThan(10);
}

/**
 * LIVE's markup, comparable between two pages: the ids React makes and every attribute that
 * points at one are emptied, and each tag starts a line of its own, so a difference reads as
 * the lines it changes.
 */
async function liveMarkup(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const copy = document.querySelector("[data-live-page]")!.cloneNode(true) as Element;
    for (const node of [copy, ...copy.querySelectorAll("*")]) {
      for (const name of ["id", "for", "aria-labelledby", "aria-describedby"]) {
        if (node.hasAttribute(name)) node.setAttribute(name, "");
      }
    }
    return copy.outerHTML
      .replace(/«[^»]*»|:r[0-9a-z]+:|_r_[0-9a-z]+_/g, "")
      .replace(/></g, ">\n<")
      .split("\n");
  });
}

/** Each pair of pages, one with motion and one without, ends with the same LIVE markup. */
export async function expectSameEnd(pairs: { label: string; moving: Page; still: Page }[]) {
  for (const { label, moving, still } of pairs) {
    expect(
      await liveMarkup(still),
      `${label}: LIVE's markup at the end, without motion and with`,
    ).toEqual(await liveMarkup(moving));
  }
}
