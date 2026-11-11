import { mkdirSync } from "node:fs";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import cupStandings from "../../docs/contracts/fpl_h2h_standings_v1.examples.json" with { type: "json" };
import {
  exampleBundle,
  exampleMember,
  forwardedLive,
  LIVE_EXAMPLES,
  STANDINGS_EXAMPLES,
} from "../src/fixtures/forwarder";
import { mockDefaultRival, mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";
import { REPLAY_START_MS, REPLAY_STEP_MS } from "../src/features/liveScore/liveReplay";
import { atRest } from "./atRest";
import type { SeededClaim } from "./identity";
import {
  closedWeek,
  exampleWeek,
  FIFTEEN,
  forwardedActivity,
  forwardedBundle,
  forwardedCalendar,
  forwardedSite,
  LISTED,
  LISTED_ENTRY,
  MARKED,
  rivalFifteen,
  serveCalendar,
} from "./liveWeek";

/**
 * LIVE (the synthesis of 2026-11-11 and the owner's decisions of that day) in its five
 * contexts: a published league, a forwarded classic league, a forwarded head-to-head league
 * whose next week is published, one team on its own, and a published league whose next week
 * is already published. Each is opened half an hour into the live week's afternoon matches,
 * and read at 320, 375, 390 and 1280 px: axe finds nothing, nothing scrolls sideways, every
 * control takes a thumb, and the phone bar's LIVE pill stands between the wordmark and
 * Fikstür. With `LIVE_PAGE_SHOTS` naming a directory, the phone widths are saved there.
 */

const copy = MESSAGES.tr;
const WIDTHS = [320, 375, 390, 1280] as const;
/** Half an hour into the 15:00 matches of Saturday 21 November. */
const KICKOFF = Date.parse("2026-11-21T15:00:00Z");
const NOW = KICKOFF + 30 * 60_000;
const READ_AT = new Date(NOW - 60_000).toISOString();
const LATER = new Date(NOW + 6 * 86_400_000).toISOString();
const at = (minutes: number) => new Date(KICKOFF + minutes * 60_000).toISOString();

/** The forwarder: each route the context answers, by path and query; anything else is 404. */
async function forwarder(page: Page, answers: Record<string, unknown>) {
  const asked: string[] = [];
  await page.route("**/api/v1/fpl/**", (route) => {
    const { pathname, search } = new URL(route.request().url());
    const path = `${pathname.replace("/api/v1/fpl", "")}${search}`;
    asked.push(path);
    const answer = answers[path] ?? answers[pathname.replace("/api/v1/fpl", "")];
    if (answer === undefined) {
      return route.fulfill({ status: 404, headers: MARKED, body: '{"error":"not_found"}' });
    }
    const refused = answer as { status?: number; error?: string };
    if (typeof refused.status === "number") {
      return route.fulfill({
        status: refused.status,
        headers: MARKED,
        body: JSON.stringify({ error: refused.error }),
      });
    }
    return route.fulfill({ headers: MARKED, body: JSON.stringify(answer) });
  });
  return asked;
}

/** The example's live week as the forwarder serves it, with its event detail. */
function exampleActivity(gameweek: number) {
  const week = forwardedLive("in_progress", gameweek);
  week.source_time = READ_AT;
  const clubs = new Map(
    LIVE_EXAMPLES.in_progress.elements.map((element) => [element.element_id, element.club!]),
  );
  const fixtureOf = (club: number) => (club <= 2 ? 61 : club <= 4 ? 62 : 63);
  return {
    contract_version: "week_activity_v1",
    week,
    activity: {
      in_play_fixtures: [62, 63],
      appearances: week.elements.map((element) => ({
        element_id: element.element_id,
        fixture_id: fixtureOf(clubs.get(element.element_id)!),
        minutes: element.minutes,
        goals: element.element_id === 4 ? 1 : 0,
        assists: element.element_id === 6 ? 1 : 0,
      })),
    },
  };
}

const LISTED_RIVAL = mockDefaultRival(LISTED_ENTRY)!;
const LISTED_RIVAL_NAME = mockLeagueMembersEnvelope.payload.members.find(
  (member) => member.entry_id === LISTED_RIVAL,
)!.team_name!;

/** A published league in its live week, or with the next week published already. */
async function listed(page: Page, { nextPublished = false } = {}) {
  const live = nextPublished ? LISTED.gameweek - 1 : LISTED.gameweek;
  const calendar = exampleWeek(
    live,
    [at(-150), at(0), at(0)],
    nextPublished ? [{ gameweek: LISTED.gameweek, deadline: LATER }] : [],
  );
  await closedWeek(page, calendar);
  return forwarder(page, {
    [`/entry/${LISTED_ENTRY}/bundle?gw=${LISTED.gameweek}`]: exampleBundle(
      LISTED_ENTRY,
      LISTED.gameweek,
      exampleMember(LISTED_ENTRY, live),
    ),
    [`/entry/${LISTED_RIVAL}/bundle?gw=${LISTED.gameweek}`]: exampleBundle(
      LISTED_RIVAL,
      LISTED.gameweek,
      { ...exampleMember(LISTED_RIVAL, live), captain: 8, vice: 7, active_chip: "bboost" },
    ),
    [`/live/${live}?view=activity`]: exampleActivity(live),
  });
}

const CLASSIC = STANDINGS_EXAMPLES.first_page;
const CLASSIC_ENTRY = CLASSIC.results[0]!.entry;
const CLASSIC_RIVAL = CLASSIC.results[1]!.entry;
const CUP = cupStandings.first_page;
const CUP_ENTRY = CUP.results[0]!.entry;
const CUP_OPPONENT = CUP.results[2]!.entry;
const claim = (leagueId: number, row: { entry: number; entry_name: string; player_name: string }) =>
  ({
    leagueId,
    entryId: row.entry,
    managerName: row.player_name,
    teamName: row.entry_name,
    leagueName: null,
  }) satisfies SeededClaim;

/** A classic league the site does not publish, from the forwarder. */
async function forwardedClassic(page: Page) {
  await forwardedSite(page, claim(CLASSIC.league.id, CLASSIC.results[0]!), 7);
  await serveCalendar(page, forwardedCalendar(7, KICKOFF));
  return forwarder(page, {
    [`/standings/${CLASSIC.league.id}?page=1`]: CLASSIC,
    [`/entry/${CLASSIC_ENTRY}/bundle?gw=7`]: forwardedBundle(CLASSIC_ENTRY, 7, 7, FIFTEEN),
    [`/entry/${CLASSIC_RIVAL}/bundle?gw=7`]: forwardedBundle(CLASSIC_RIVAL, 7, 7, rivalFifteen()),
    "/live/7?view=activity": forwardedActivity(7, KICKOFF, READ_AT),
  });
}

/** One week's pairings of the cup: the member against `opponent`, the other two together. */
function pairings(gameweek: number, opponent: number) {
  const others = CUP.results.map((row) => row.entry).filter((id) => id !== CUP_ENTRY);
  const [first, second] = others.filter((id) => id !== opponent);
  const side = (entry: number) => {
    const row = CUP.results.find((result) => result.entry === entry)!;
    return { entry, name: row.entry_name, player_name: row.player_name, points: 0 };
  };
  return {
    contract_version: "fpl_h2h_matches_v1",
    league: { id: CUP.league.id, scoring: "h2h" },
    gameweek,
    page: 1,
    has_next: false,
    source_time: READ_AT,
    results: [
      {
        id: 1,
        entry_1: side(CUP_ENTRY),
        entry_2: side(opponent),
        winner: null,
        started: true,
        finished: false,
      },
      {
        id: 2,
        entry_1: side(first!),
        entry_2: side(second!),
        winner: null,
        started: true,
        finished: false,
      },
    ],
  };
}

/**
 * A head-to-head league the site does not publish, whose next week's table is published:
 * the table and the bundle are week 8's, the live week is 7, and the week 7 opponent is not
 * the one week 8 pairs the member with.
 */
async function forwardedCup(page: Page) {
  await forwardedSite(page, claim(CUP.league.id, CUP.results[0]!), 8);
  await serveCalendar(page, forwardedCalendar(7, KICKOFF, [{ gameweek: 8, deadline: LATER }]));
  return forwarder(page, {
    [`/standings/${CUP.league.id}?page=1`]: { status: 404, error: "head_to_head_league" },
    [`/h2h/${CUP.league.id}/standings?page=1`]: CUP,
    [`/h2h/${CUP.league.id}/matches?gw=7&page=1`]: pairings(7, CUP_OPPONENT),
    [`/h2h/${CUP.league.id}/matches?gw=8&page=1`]: pairings(8, CUP.results[1]!.entry),
    [`/entry/${CUP_ENTRY}/bundle?gw=8`]: forwardedBundle(CUP_ENTRY, 8, 7, FIFTEEN),
    [`/entry/${CUP_OPPONENT}/bundle?gw=8`]: forwardedBundle(CUP_OPPONENT, 8, 7, rivalFifteen()),
    "/live/7?view=activity": forwardedActivity(7, KICKOFF, READ_AT),
  });
}

/** One team on its own: no league, so no rival. */
async function standalone(page: Page) {
  await forwardedSite(page, null, 7);
  await serveCalendar(page, forwardedCalendar(7, KICKOFF));
  return forwarder(page, {
    [`/entry/${CLASSIC_ENTRY}/bundle?gw=7`]: forwardedBundle(CLASSIC_ENTRY, 7, 7, FIFTEEN),
    "/live/7?view=activity": forwardedActivity(7, KICKOFF, READ_AT),
  });
}

interface LiveContext {
  name: string;
  path: string;
  serve: (page: Page) => Promise<string[]>;
  gameweek: number;
  /** The rival the page sets beside the member, by name, or null for none. */
  rival: string | null;
  headToHead: boolean;
  totalGap: boolean;
}

const CONTEXTS: LiveContext[] = [
  {
    name: "published",
    path: `/league/352490/members/${LISTED_ENTRY}/live`,
    serve: (page) => listed(page),
    gameweek: LISTED.gameweek,
    rival: LISTED_RIVAL_NAME,
    headToHead: false,
    totalGap: true,
  },
  {
    name: "forwarded-classic",
    path: `/league/${CLASSIC.league.id}/members/${CLASSIC_ENTRY}/live`,
    serve: forwardedClassic,
    gameweek: 7,
    rival: CLASSIC.results[1]!.entry_name,
    headToHead: false,
    // FPL's table moves while the week is played, so a forwarded league shows no total gap.
    totalGap: false,
  },
  {
    name: "forwarded-h2h",
    path: `/league/${CUP.league.id}/members/${CUP_ENTRY}/live`,
    serve: forwardedCup,
    gameweek: 7,
    rival: CUP.results[2]!.entry_name,
    headToHead: true,
    totalGap: false,
  },
  {
    name: "entry",
    path: `/entry/${CLASSIC_ENTRY}/live`,
    serve: standalone,
    gameweek: 7,
    rival: null,
    headToHead: false,
    totalGap: false,
  },
  {
    name: "next-week-published",
    path: `/league/352490/members/${LISTED_ENTRY}/live`,
    serve: (page) => listed(page, { nextPublished: true }),
    gameweek: LISTED.gameweek - 1,
    rival: LISTED_RIVAL_NAME,
    headToHead: false,
    totalGap: true,
  },
];

/** Every control a thumb uses on the page and in the phone bar, smaller than it should be. */
async function smallControls(page: Page) {
  return page.evaluate(() =>
    [
      ...document.querySelectorAll(
        "main a[href], main button, main select, main summary, header a[href], header button",
      ),
    ]
      .map((element) => ({ element, box: element.getBoundingClientRect() }))
      .filter(
        ({ element, box }) =>
          box.width > 0 && box.height > 0 && !element.classList.contains("visually-hidden"),
      )
      .filter(({ element, box }) => {
        const least = element.matches("[data-live-refresh], [data-live-pill]") ? 44 : 36;
        return box.height < least || box.width < 36;
      })
      .map(({ element, box }) => ({
        text: (element.textContent ?? "").trim().slice(0, 30),
        h: Math.round(box.height),
        w: Math.round(box.width),
      })),
  );
}

for (const context of CONTEXTS) {
  test(`LIVE in a ${context.name} context at every width`, async ({ page, browserName }) => {
    test.slow();
    await page.clock.install({ time: NOW });
    await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
    const asked = await context.serve(page);
    await page.setViewportSize({ width: WIDTHS[0], height: 900 });
    await page.goto(context.path);
    const live = page.locator("[data-live-page]");
    await expect(live).toBeVisible();
    await expect(page.getByRole("heading", { level: 1, name: copy.live.title })).toBeVisible();
    await expect(live).toContainText(copy.suggestionHistory.gameweek(context.gameweek));
    // The week being played: its groups by match, and the member's fifteen.
    await expect(page.locator("[data-live-row]")).toHaveCount(15);
    await expect(page.getByRole("heading", { name: copy.live.groups.playing })).toBeVisible();
    // The live week only, read once: never the table's week when the next one is published.
    expect(asked.filter((path) => path.startsWith("/live/"))).toEqual([
      `/live/${context.gameweek}?view=activity`,
    ]);
    const rivalBlock = page.locator("[data-live-rival]");
    if (context.rival === null) {
      await expect(rivalBlock).toHaveCount(0);
    } else {
      const select = rivalBlock.getByRole("combobox");
      await expect(select.locator("option:checked")).toHaveText(context.rival);
      await expect(rivalBlock.locator("[data-live-rival-net]")).toBeVisible();
      await expect(rivalBlock).toContainText(copy.live.margin);
      if (context.totalGap) await expect(rivalBlock).toContainText(copy.live.totalGap);
      else await expect(rivalBlock).not.toContainText(copy.live.totalGap);
      await expect(rivalBlock.getByText(copy.live.h2h, { exact: true })).toHaveCount(
        context.headToHead ? 1 : 0,
      );
      expect(await select.evaluate((node) => getComputedStyle(node).fontSize)).toBe("16px");
    }
    if (context.headToHead) {
      expect(asked).not.toContain(`/h2h/${CUP.league.id}/matches?gw=8&page=1`);
    }

    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 });
      await expect(live).toBeVisible();
      await atRest(page);
      const phone = width < 600;
      // The pill while one of the member's matches is on, in the phone bar only.
      const pill = page.locator("[data-live-pill]");
      await expect(pill).toHaveCount(phone ? 1 : 0);
      if (phone) {
        const box = (await pill.boundingBox())!;
        expect(box.height).toBeGreaterThanOrEqual(44);
        const fixtures = page.getByRole("banner").getByRole("link", { name: copy.shell.fixtures });
        const end = (await fixtures.boundingBox())!;
        expect(end.x + end.width).toBeLessThanOrEqual(width);
      }
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
        `${width}px scrolls sideways`,
      ).toBe(true);
      expect(await smallControls(page), `${width}px`).toEqual([]);
      if (width === WIDTHS[0]) {
        // The pill and the page read each bundle once, under the one key they share.
        const bundles = asked.filter((path) => path.includes("/bundle?gw="));
        expect(bundles.length).toBeGreaterThan(0);
        expect(bundles).toEqual([...new Set(bundles)]);
      }
      const scan = await new AxeBuilder({ page }).analyze();
      expect(
        scan.violations.map((violation) => `${violation.id}: ${violation.nodes[0]?.target}`),
        `${width}px`,
      ).toEqual([]);
      const shots = process.env.LIVE_PAGE_SHOTS;
      if (shots && phone) {
        mkdirSync(shots, { recursive: true });
        await page.screenshot({
          path: join(shots, `${browserName}-${context.name}-${width}.png`),
          fullPage: true,
        });
      }
    }
  });
}

test("the row's name says the player, their role, group, match, points, events and state", async ({
  page,
}) => {
  await page.clock.install({ time: NOW });
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
  await listed(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/league/352490/members/${LISTED_ENTRY}/live`);
  // Player 4, a defender in the 15:00 match against C3: 45 minutes, 3 points and a goal.
  await expect(
    page.getByRole("listitem", {
      name: `Player 4, ${copy.live.groups.playing}, C3, ${copy.live.minutes("45")}, ${copy.live.points("3")}, ${copy.live.goal} 1, ${copy.live.doingWell}`,
    }),
  ).toBeVisible();
  // The captain, Player 7, did not play in the finished match: the armband passes to the vice.
  await expect(page.locator("[data-live-row='8']")).toHaveAttribute("aria-label", /Kaptan ×2/);
  // Farklar, closed on a phone, opens on a tap.
  const differentials = page.locator("[data-live-differentials]");
  await expect(differentials).not.toHaveAttribute("open");
  await differentials.getByText(copy.live.differentials).click();
  await expect(differentials).toHaveAttribute("open");
  await expect(differentials).toContainText(copy.live.shared);
});

test("the pill is absent while none of the member's matches is in its window", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
  // The closed week's matches kicked off in 2020.
  await closedWeek(page);
  await forwarder(page, {
    [`/entry/${LISTED_ENTRY}/bundle?gw=${LISTED.gameweek}`]: exampleBundle(
      LISTED_ENTRY,
      LISTED.gameweek,
      exampleMember(LISTED_ENTRY, LISTED.gameweek),
    ),
    [`/live/${LISTED.gameweek}?view=activity`]: exampleActivity(LISTED.gameweek),
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/league/352490/members/${LISTED_ENTRY}/live`);
  await expect(page.locator("[data-live-row]")).toHaveCount(15);
  await expect(page.locator("[data-live-pill]")).toHaveCount(0);
  await expect(page.locator("[data-live-page] h1 [role='img']")).toHaveCount(0);
});

test("the pill and the light stay away, and LIVE reads once, while only another club plays", async ({
  page,
}) => {
  // The member's four matches are past their windows; clubs 9 and 10, none of the member's,
  // kicked off half an hour ago.
  const now = KICKOFF + 335 * 60_000;
  await page.clock.install({ time: now });
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
  await forwardedSite(page, null, 7);
  const calendar = forwardedCalendar(7, KICKOFF);
  calendar.gameweeks[0]!.fixtures.push({
    fixture_id: 75,
    kickoff_utc: new Date(now - 30 * 60_000).toISOString(),
    home: { team_id: 9, name: "Club 9", short_name: "K9" },
    away: { team_id: 10, name: "Club 10", short_name: "K10" },
    finished: false,
    home_score: null,
    away_score: null,
  });
  await serveCalendar(page, calendar);
  const asked = await forwarder(page, {
    [`/entry/${CLASSIC_ENTRY}/bundle?gw=7`]: forwardedBundle(CLASSIC_ENTRY, 7, 7, FIFTEEN),
    "/live/7?view=activity": forwardedActivity(7, KICKOFF, new Date(now - 60_000).toISOString()),
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/entry/${CLASSIC_ENTRY}/live`);
  await expect(page.locator("[data-live-row]")).toHaveCount(15);
  await page.clock.fastForward(3 * 60_000);
  await expect(page.locator("[data-live-pill]")).toHaveCount(0);
  await expect(page.locator("[data-live-page] h1 [role='img']")).toHaveCount(0);
  expect(asked.filter((path) => path.startsWith("/live/"))).toEqual(["/live/7?view=activity"]);
});

test("while the member's match is played LIVE reads by itself, and the goal's points wait on the GOL board", async ({
  page,
}) => {
  await page.clock.install({ time: NOW });
  await page.addInitScript(() => {
    localStorage.setItem("squadopt.language", "tr");
    sessionStorage.setItem("squadopt.openingShown", "1");
  });
  await listed(page);
  // The first read has no goal yet; a minute later Player 4, a defender, has scored: six
  // points more.
  const first = exampleActivity(LISTED.gameweek);
  for (const row of first.activity.appearances) Object.assign(row, { goals: 0, assists: 0 });
  const second = exampleActivity(LISTED.gameweek);
  second.week.source_time = new Date(NOW).toISOString();
  for (const row of second.activity.appearances) if (row.element_id !== 4) row.assists = 0;
  second.week.elements.find((element) => element.element_id === 4)!.points += 6;
  const reads: string[] = [];
  await page.route("**/api/v1/fpl/live/**", (route) => {
    reads.push(new URL(route.request().url()).pathname);
    const answer = reads.length === 1 ? first : second;
    return route.fulfill({ headers: MARKED, body: JSON.stringify(answer) });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/league/352490/members/${LISTED_ENTRY}/live`);
  await expect(page.locator("[data-live-row]")).toHaveCount(15);
  const total = page.locator("[data-live-total]");
  const before = Number(await total.textContent());
  expect(reads).toHaveLength(1);
  await expect(page.locator("[data-goal-board]")).toHaveCount(0);
  await page.clock.fastForward(60_000);
  const board = page.locator("[data-goal-board='goal']");
  await expect(board).toContainText("Player 4");
  expect(reads).toHaveLength(2);
  // Canlı puan stands where it was until the board brings the goal's points into it.
  await expect(total).toHaveText(String(before));
  await board.click();
  await expect(total).toHaveText(String(before + 6));
});

test("the member page's top bar and the pill lead to LIVE", async ({ page }) => {
  await page.clock.install({ time: NOW });
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
  await listed(page);
  await page.setViewportSize({ width: 390, height: 844 });
  // A rival's page: its own LIVE from the top bar; the visitor's own from the pill.
  await page.goto(`/league/352490/members/${LISTED_RIVAL}`);
  const topBarLink = page.locator("[data-live-link]");
  await expect(topBarLink).toHaveAttribute("href", `/league/352490/members/${LISTED_RIVAL}/live`);
  const pill = page.locator("[data-live-pill]");
  await expect(pill).toHaveAttribute("href", `/league/352490/members/${LISTED_ENTRY}/live`);
  await pill.click();
  await expect(page).toHaveURL(`/league/352490/members/${LISTED_ENTRY}/live`);
  await expect(page.locator("[data-live-row]")).toHaveCount(15);
  await expect(pill).toHaveAttribute("aria-current", "page");
});

test("the address alone replays the week's goals on LIVE's GOL board", async ({ page }) => {
  await page.clock.install({ time: Date.parse("2026-11-12T10:00:00Z") });
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
  await listed(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/league/352490/members/${LISTED_ENTRY}/live?replay=1`);
  await expect(page.locator("[data-live-row]")).toHaveCount(15);
  expect(await page.locator('a[href*="replay"]').count()).toBe(0);
  // The fixtures in order: Player 6's assist in the finished match, then Player 4's goal.
  await page.clock.fastForward(REPLAY_START_MS + 100);
  await expect(page.locator("[data-goal-board='assist']")).toContainText("Player 6");
  await page.clock.fastForward(REPLAY_STEP_MS);
  await expect(page.locator("[data-goal-board='goal']")).toContainText("Player 4");
});
