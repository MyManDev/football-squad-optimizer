import { createHash } from "node:crypto";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

import { COMPUTE_COPY } from "../src/features/league/advice/computeCopy";
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
