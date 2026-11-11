import { createHash } from "node:crypto";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

import { COMPUTE_COPY } from "../src/features/league/advice/computeCopy";
import { ASSIST_SHOUT, GOAL_SHOUT } from "../src/features/liveScore/goalMomentTiming";
import { REPLAY_START_MS, REPLAY_STEP_MS } from "../src/features/liveScore/liveReplay";
import {
  exampleBundle,
  exampleCalendar,
  exampleMember,
  exampleTable,
  forwardedLive,
  type LiveExample,
} from "../src/fixtures/forwarder";
import { mockEntrySquadEnvelopes, mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { installLeagueMocks } from "./leagueMocks";

/**
 * The member's live week (#1008, source A) with a mocked FPL forwarder: once the page's
 * week is closed, the page asks the forwarder for the member's bundle and that week's live
 * points, resolves each pick from the capture's table, and shows the card beside the
 * deadline notice. Refresh reads the live points again; a forwarder that does not answer
 * leaves no card.
 */

const ENTRY = 35249001;
const { season, gameweek, source_snapshot_id: capture } = mockEntrySquadEnvelopes[ENTRY]!.payload;
const TABLE_PATH = `device/${capture}/device-plan.json`;
const MARKED = { "x-squadopt-fpl": "1", "content-type": "application/json; charset=utf-8" };

function sha256(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

/** The league with a closed week, the capture's table its directory line names, and the calendar. */
async function closedWeek(page: Page) {
  await installLeagueMocks(page);
  const { league_id, league_name } = mockLeagueMembersEnvelope.payload;
  const bytes = `${JSON.stringify({
    contract_version: "provisional_league_ui_v1",
    generated_at_utc: "2026-08-21T07:00:00Z",
    source_kind: "live",
    payload: exampleTable({ season, gameweek, capture: capture! }),
  })}\n`;
  await page.route("**/data/leagues.json", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        contract_version: "league_directory_v1",
        generated_at_utc: mockLeagueMembersEnvelope.generated_at_utc,
        source_kind: "live",
        payload: {
          leagues: [
            {
              league_id,
              league_name,
              season,
              gameweek,
              path: "league",
              device_plan: TABLE_PATH,
              device_plan_sha256: sha256(bytes),
            },
          ],
        },
      }),
    }),
  );
  await page.route(/\/data\/device\//, (route) =>
    route.fulfill({ contentType: "application/json", body: bytes }),
  );
  await page.route("**/data/fixtures.json", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        contract_version: "fixtures_v1",
        generated_at_utc: mockLeagueMembersEnvelope.generated_at_utc,
        source_kind: "live",
        payload: exampleCalendar({ season, gameweek, deadline: "2020-01-01T00:00:00Z" }),
      }),
    }),
  );
}

/** The forwarder's two routes; the live week answers each of `weeks` in turn. */
async function forwarder(
  page: Page,
  bundle: (route: Route) => Promise<void>,
  weeks: LiveExample[],
  events?: { goals: number; assists: number }[],
) {
  const asked = { bundle: [] as string[], live: [] as string[] };
  await page.route("**/api/v1/fpl/**", async (route) => {
    const { pathname, search } = new URL(route.request().url());
    if (pathname === `/api/v1/fpl/entry/${ENTRY}/bundle`) {
      asked.bundle.push(`${pathname}${search}`);
      return bundle(route);
    }
    if (pathname === `/api/v1/fpl/live/${gameweek}`) {
      asked.live.push(`${pathname}${search}`);
      const name = weeks[Math.min(asked.live.length, weeks.length) - 1]!;
      const week = forwardedLive(name, gameweek);
      const counts = events?.[Math.min(asked.live.length, events.length) - 1];
      const fixture = week.fixtures.find((row) => !row.finished);
      const scorer = week.elements.find((row) => row.minutes > 0)!;
      const activity =
        counts && fixture
          ? {
              in_play_fixtures: [fixture.id],
              appearances: week.elements.map((row) => ({
                element_id: row.element_id,
                fixture_id: fixture.id,
                minutes: row.minutes,
                goals: row.element_id === scorer.element_id ? counts.goals : 0,
                assists: row.element_id === scorer.element_id ? counts.assists : 0,
              })),
            }
          : null;
      week.source_time = new Date(
        Date.parse(week.source_time) + asked.live.length * 60_000,
      ).toISOString();
      return route.fulfill({
        headers: MARKED,
        body: JSON.stringify(
          search === "?view=activity"
            ? {
                contract_version: "week_activity_v1",
                week,
                activity,
              }
            : week,
        ),
      });
    }
    return route.fulfill({ status: 404, headers: MARKED, body: '{"error":"not_found"}' });
  });
  return asked;
}

const answersBundle = (route: Route) =>
  route.fulfill({
    headers: MARKED,
    body: JSON.stringify(exampleBundle(ENTRY, gameweek, exampleMember(ENTRY, gameweek))),
  });

for (const language of ["tr", "en"] as const) {
  test(`the week being played is scored beside the closed week's notice in ${language}`, async ({
    page,
  }) => {
    await closedWeek(page);
    const asked = await forwarder(page, answersBundle, ["in_progress", "finished"]);
    await page.addInitScript((lang) => localStorage.setItem("squadopt.language", lang), language);
    await page.goto(`/league/352490/members/${ENTRY}`);

    const notice = page.getByTestId("deadline-passed");
    await expect(notice).toContainText(COMPUTE_COPY[language].deadlinePassedTitle);
    const card = page.locator("[data-member-live-score]");
    await expect(card).toContainText(language === "tr" ? "Bonus bekleniyor" : "Bonus Pending");
    await expect(card.getByRole("heading", { level: 2 })).toContainText(String(gameweek));
    // The card is the notice's next sibling: it stands beside it, before the decision.
    expect(
      await notice.evaluate((element) =>
        element.nextElementSibling?.hasAttribute("data-member-live-score"),
      ),
    ).toBe(true);
    expect(asked.bundle).toEqual([`/api/v1/fpl/entry/${ENTRY}/bundle?gw=${gameweek}`]);
    expect(asked.live).toEqual([`/api/v1/fpl/live/${gameweek}?view=activity`]);
    const assertPlayerPoints = async (name: LiveExample) => {
      const table = exampleTable({ season, gameweek, capture: capture! });
      const week = forwardedLive(name, gameweek);
      await expect(page.locator('#kadro [data-points-kind="actual"]')).toHaveCount(15);
      for (const id of exampleMember(ENTRY, gameweek).pick_order) {
        const player = table.players.find((row) => row.element_id === id)!;
        const points = week.elements.find((row) => row.element_id === id)!.points;
        await expect(
          page.locator(`#kadro [data-player-motion="${player.id}"] [data-player-points]`),
        ).toHaveAttribute("data-player-points", String(points));
      }
    };
    await assertPlayerPoints("in_progress");

    // Refresh reads the live points again, and nothing else.
    await card.getByRole("button", { name: language === "tr" ? "Yenile" : "Refresh" }).click();
    await expect(card).toContainText(language === "tr" ? "Bonus eklendi" : "Bonus Added");
    await assertPlayerPoints("finished");
    expect(asked.live).toHaveLength(2);
    expect(asked.bundle).toHaveLength(1);
  });
}

for (const width of [375, 1280]) {
  for (const reduce of [false, true]) {
    test(`realized events at ${width}px with reduced motion ${reduce}`, async ({
      page,
    }, testInfo) => {
      await page.setViewportSize({ width, height: 900 });
      await page.emulateMedia({ reducedMotion: reduce ? "reduce" : "no-preference" });
      await closedWeek(page);
      await forwarder(
        page,
        answersBundle,
        ["in_progress"],
        [
          { goals: 0, assists: 0 },
          { goals: 1, assists: 0 },
          { goals: 1, assists: 0 },
          { goals: 1, assists: 1 },
        ],
      );
      await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
      await page.goto(`/league/352490/members/${ENTRY}`);
      await expect(page.locator("[data-opening-mark]")).toHaveCount(0, { timeout: 10_000 });
      const card = page.locator("[data-member-live-score]");
      await expect(card.getByRole("img", { name: "Maç sürüyor" }).first()).toBeVisible();
      await card.evaluate((node) => {
        node.setAttribute("data-test-animations", "0");
        node.addEventListener("animationstart", (event) => {
          if ((event as AnimationEvent).animationName.includes("live-event")) {
            node.setAttribute(
              "data-test-animations",
              String(Number(node.getAttribute("data-test-animations")) + 1),
            );
          }
        });
      });
      const refresh = card.getByRole("button", { name: "Yenile" });
      await refresh.click();
      await expect(card.getByLabel("Gol: 1", { exact: true })).toBeVisible();
      await expect(card).toHaveAttribute("data-test-animations", reduce ? "0" : "1");
      await refresh.click();
      await expect(refresh).toBeEnabled();
      await expect(card).toHaveAttribute("data-test-animations", reduce ? "0" : "1");
      await refresh.click();
      await expect(card.getByLabel("Asist: 1", { exact: true })).toBeVisible();
      await expect(card).toHaveAttribute("data-test-animations", reduce ? "0" : "2");
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await card.evaluate((node) =>
        Promise.all(
          node
            .getAnimations({ subtree: true })
            .map((animation) => animation.finished.catch(() => undefined)),
        ),
      );
      expect(
        (await new AxeBuilder({ page }).include("[data-member-live-score]").analyze()).violations,
      ).toEqual([]);
      await card.screenshot({
        path: testInfo.outputPath(`live-activity-${width}-${reduce ? "reduced" : "motion"}.png`),
      });
    });
  }
}

for (const [name, answer] of [
  [
    "the site's HTML shell",
    (route: Route) =>
      route.fulfill({ contentType: "text/html", body: "<!doctype html><html></html>" }),
  ],
  [
    "the forwarder's 503",
    (route: Route) =>
      route.fulfill({ status: 503, headers: MARKED, body: '{"error":"upstream_unavailable"}' }),
  ],
  [
    "an entry FPL does not have",
    (route: Route) =>
      route.fulfill({ status: 404, headers: MARKED, body: '{"error":"entry_not_found"}' }),
  ],
] as const) {
  test(`no card when the bundle is ${name}`, async ({ page }) => {
    await closedWeek(page);
    const asked = await forwarder(page, answer, ["in_progress"]);
    const answered = page.waitForResponse((response) => response.url().includes("/bundle?gw="));
    await page.goto(`/league/352490/members/${ENTRY}`);
    await answered;
    await expect(page.getByTestId("deadline-passed")).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expect(page.locator("[data-member-live-score]")).toHaveCount(0);
    expect(asked.live).toEqual([]);
  });
}

/**
 * The GOL moment (the owner's Plan 1 of 2026-11-11): a read that brings a goal by one of the
 * member's players raises the board in the middle of the screen, with the shout, the scorer
 * and the points, and lowers it by itself; under reduced motion one still line says it.
 */
// The example's first player who played is its goalkeeper, Player 1, without the armband:
// in 2026-27 a goal brings him the keeper's 10 points and an assist 3.
const SCORER = { name: "Player 1", goal: "+10", assist: "+3" };

/** Nothing of the GOL moment is on the page now, nor a moment later. */
async function nothingPlays(page: Page) {
  await page.waitForTimeout(800);
  expect(await page.locator("[data-goal-board], [data-goal-still]").count()).toBe(0);
}

/** A move inside the page, as the sidebar makes it: the page stays mounted. */
async function moveTo(page: Page, path: string) {
  await page.evaluate((to) => {
    history.pushState({}, "", to);
    dispatchEvent(new PopStateEvent("popstate"));
  }, path);
}

for (const width of [320, 375, 390]) {
  for (const reduce of [false, true]) {
    test(`a goal raises the GOL board at ${width}px with reduced motion ${reduce}`, async ({
      page,
    }, testInfo) => {
      await page.setViewportSize({ width, height: 800 });
      await page.emulateMedia({ reducedMotion: reduce ? "reduce" : "no-preference" });
      await closedWeek(page);
      // The keeper scored before the page opened; each later read is a minute newer.
      await forwarder(
        page,
        answersBundle,
        ["in_progress"],
        [
          { goals: 1, assists: 0 },
          { goals: 2, assists: 0 },
          { goals: 2, assists: 0 },
          { goals: 2, assists: 1 },
        ],
      );
      await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
      await page.goto(`/league/352490/members/${ENTRY}`);
      await expect(page.locator("[data-opening-mark]")).toHaveCount(0, { timeout: 10_000 });
      const card = page.locator("[data-member-live-score]");
      await expect(card).toBeVisible();
      // The first read is the starting point: the goal already scored does not play.
      await nothingPlays(page);
      const refresh = card.getByRole("button", { name: "Yenile" });
      await refresh.click();
      if (reduce) {
        const still = page.locator("[data-goal-still]");
        await expect(still).toContainText(`${GOAL_SHOUT.tr} · ${SCORER.name} · ${SCORER.goal}`);
        await expect(page.locator("[data-goal-board]")).toHaveCount(0);
        await page.screenshot({ path: testInfo.outputPath(`goal-still-${width}.png`) });
        await still.getByRole("button", { name: "Kapat" }).click();
        await expect(still).toHaveCount(0);
      } else {
        const board = page.locator("[data-goal-board='goal']");
        await expect(board).toBeVisible();
        await expect(board).toContainText(GOAL_SHOUT.tr);
        await expect(board).toContainText(SCORER.name);
        await expect(board.locator("[data-goal-points]")).toHaveText(SCORER.goal);
        await expect(page.getByRole("status").filter({ hasText: "Gol:" })).toHaveText(
          `Gol: ${SCORER.name}, ${SCORER.goal} puan`,
        );
        // Once risen, the board sits inside the screen, in its middle, and the page does not
        // scroll sideways.
        await page.waitForTimeout(600);
        const box = (await board.boundingBox())!;
        expect(box.x).toBeGreaterThanOrEqual(0);
        expect(box.x + box.width).toBeLessThanOrEqual(width);
        expect(box.y).toBeGreaterThan(800 * 0.2);
        expect(box.y + box.height).toBeLessThan(800 * 0.85);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
          true,
        );
        await page.screenshot({ path: testInfo.outputPath(`goal-board-${width}.png`) });
        // It goes down by itself.
        await expect(board).toHaveCount(0, { timeout: 6_000 });
      }
      // The same goal in a later read plays nothing.
      await refresh.click();
      await expect(refresh).toBeEnabled();
      await nothingPlays(page);
      // An assist rises the board with its own long shout, which fits the narrowest screen.
      await refresh.click();
      if (reduce) {
        await expect(page.locator("[data-goal-still]")).toContainText(
          `${ASSIST_SHOUT.tr} · ${SCORER.name} · ${SCORER.assist}`,
        );
      } else {
        const assist = page.locator("[data-goal-board='assist']");
        await expect(assist).toContainText(ASSIST_SHOUT.tr);
        await expect(assist.locator("[data-goal-points]")).toHaveText(SCORER.assist);
        // Measured once it has risen: a board turning about its top edge looks wider.
        await page.waitForTimeout(600);
        const box = (await assist.boundingBox())!;
        expect(box.x).toBeGreaterThanOrEqual(0);
        expect(box.x + box.width).toBeLessThanOrEqual(width);
        const shout = assist.locator("[data-long]");
        expect(
          await shout.evaluate((node) => node.scrollWidth <= node.parentElement!.clientWidth),
        ).toBe(true);
        await page.screenshot({ path: testInfo.outputPath(`assist-board-${width}.png`) });
        await expect(assist).toHaveCount(0, { timeout: 6_000 });
      }
    });
  }
}

test("a moment already played does not play again after a tool and back", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await closedWeek(page);
  await forwarder(
    page,
    answersBundle,
    ["in_progress"],
    [
      { goals: 0, assists: 0 },
      { goals: 1, assists: 0 },
    ],
  );
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
  await page.goto(`/league/352490/members/${ENTRY}`);
  await expect(page.locator("[data-opening-mark]")).toHaveCount(0, { timeout: 10_000 });
  const card = page.locator("[data-member-live-score]");
  await card.getByRole("button", { name: "Yenile" }).click();
  const board = page.locator("[data-goal-board='goal']");
  await expect(board).toBeVisible();
  await board.click();
  await expect(board).toHaveCount(0);
  for (const tool of ["current-squad", "what-if"]) {
    await moveTo(page, `/league/352490/members/${ENTRY}/${tool}`);
    await expect(page.locator("#member-tool-title")).toBeVisible();
    await moveTo(page, `/league/352490/members/${ENTRY}`);
    await expect(card).toBeVisible();
    await nothingPlays(page);
  }
});

test("while a match is played the page reads by itself and the goal plays", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const now = Date.parse("2026-11-21T15:30:00Z");
  await page.clock.install({ time: now });
  await closedWeek(page);
  // The live week kicked off half an hour ago, so its match is being played.
  await page.route("**/data/fixtures.json", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        contract_version: "fixtures_v1",
        generated_at_utc: mockLeagueMembersEnvelope.generated_at_utc,
        source_kind: "live",
        payload: exampleCalendar({
          season,
          gameweek,
          deadline: new Date(now - 30 * 60_000).toISOString(),
        }),
      }),
    }),
  );
  const asked = await forwarder(
    page,
    answersBundle,
    ["in_progress"],
    [
      { goals: 0, assists: 0 },
      { goals: 1, assists: 0 },
    ],
  );
  await page.addInitScript(() => {
    localStorage.setItem("squadopt.language", "tr");
    sessionStorage.setItem("squadopt.openingShown", "1");
  });
  await page.goto(`/league/352490/members/${ENTRY}`);
  await expect(page.locator("[data-member-live-score]")).toBeVisible();
  expect(asked.live).toHaveLength(1);
  await page.clock.fastForward(60_000);
  await expect(page.locator("[data-goal-board='goal']")).toContainText(SCORER.name);
  expect(asked.live).toHaveLength(2);
  expect(asked.bundle).toHaveLength(1);
});

test("a goal of the week being played plays on the next week's open page", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const now = Date.parse("2026-11-21T15:30:00Z");
  await page.clock.install({ time: now });
  await closedWeek(page);
  // The live week is the one before the page's: it kicked off half an hour ago, while the
  // page's own week, whose plan is published, is still open.
  const live = gameweek - 1;
  const calendar = exampleCalendar({
    season,
    gameweek: live,
    deadline: new Date(now - 30 * 60_000).toISOString(),
  });
  calendar.gameweeks.push({
    gameweek,
    deadline_utc: new Date(now + 6 * 86_400_000).toISOString(),
    fixtures: [],
  });
  await page.route("**/data/fixtures.json", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        contract_version: "fixtures_v1",
        generated_at_utc: mockLeagueMembersEnvelope.generated_at_utc,
        source_kind: "live",
        payload: calendar,
      }),
    }),
  );
  let reads = 0;
  await page.route("**/api/v1/fpl/**", async (route) => {
    const { pathname } = new URL(route.request().url());
    if (pathname === `/api/v1/fpl/entry/${ENTRY}/bundle`) {
      return route.fulfill({
        headers: MARKED,
        body: JSON.stringify(exampleBundle(ENTRY, gameweek, exampleMember(ENTRY, live))),
      });
    }
    if (pathname === `/api/v1/fpl/live/${live}`) {
      reads += 1;
      const week = forwardedLive("in_progress", live);
      week.source_time = new Date(Date.parse(week.source_time) + reads * 60_000).toISOString();
      const fixture = week.fixtures.find((row) => !row.finished)!;
      const scorer = week.elements.find((row) => row.minutes > 0)!;
      return route.fulfill({
        headers: MARKED,
        body: JSON.stringify({
          contract_version: "week_activity_v1",
          week,
          activity: {
            in_play_fixtures: [fixture.id],
            appearances: week.elements.map((row) => ({
              element_id: row.element_id,
              fixture_id: fixture.id,
              minutes: row.minutes,
              goals: row.element_id === scorer.element_id && reads > 1 ? 1 : 0,
              assists: 0,
            })),
          },
        }),
      });
    }
    return route.fulfill({ status: 404, headers: MARKED, body: '{"error":"not_found"}' });
  });
  await page.addInitScript(() => {
    localStorage.setItem("squadopt.language", "tr");
    sessionStorage.setItem("squadopt.openingShown", "1");
  });
  await page.goto(`/league/352490/members/${ENTRY}`);
  // The page shows its own open week: no deadline notice and no live card.
  await expect(page.locator("#entry-advice-title")).toBeVisible();
  await expect(page.getByTestId("deadline-passed")).toHaveCount(0);
  await expect(page.locator("[data-member-live-score]")).toHaveCount(0);
  await expect.poll(() => reads).toBe(1);
  await page.clock.fastForward(60_000);
  await expect(page.locator("[data-goal-board='goal']")).toContainText(SCORER.name);
  expect(reads).toBe(2);
});

test("the address alone replays the week's goals and assists on the GOL board", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.clock.install({ time: Date.parse("2026-11-12T10:00:00Z") });
  await closedWeek(page);
  const asked = await forwarder(page, answersBundle, ["in_progress"], [{ goals: 1, assists: 1 }]);
  await page.addInitScript(() => {
    localStorage.setItem("squadopt.language", "tr");
    sessionStorage.setItem("squadopt.openingShown", "1");
  });
  await page.goto(`/league/352490/members/${ENTRY}?replay=1`);
  await expect(page.locator("[data-member-live-score]")).toBeVisible();
  // Nothing on the page links to the replay or names it.
  expect(await page.locator('a[href*="replay"]').count()).toBe(0);
  expect(await page.evaluate(() => /replay/i.test(document.body.innerText))).toBe(false);
  await page.clock.fastForward(REPLAY_START_MS + 100);
  await expect(page.locator("[data-goal-board='goal']")).toContainText(SCORER.name);
  await page.clock.fastForward(REPLAY_STEP_MS);
  await expect(page.locator("[data-goal-board='assist']")).toContainText(ASSIST_SHOUT.tr);
  // The replay reads the week once, beside the page's own first read, and nothing follows.
  await page.clock.fastForward(2 * 60_000);
  expect(asked.live).toHaveLength(2);
});
