import { createHash } from "node:crypto";

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
) {
  const asked = { bundle: [] as string[], live: [] as string[] };
  await page.route("**/api/v1/fpl/**", async (route) => {
    const { pathname, search } = new URL(route.request().url());
    if (pathname === `/api/v1/fpl/entry/${ENTRY}/bundle`) {
      asked.bundle.push(`${pathname}${search}`);
      return bundle(route);
    }
    if (pathname === `/api/v1/fpl/live/${gameweek}`) {
      asked.live.push(pathname);
      const name = weeks[Math.min(asked.live.length, weeks.length) - 1]!;
      return route.fulfill({
        headers: MARKED,
        body: JSON.stringify(forwardedLive(name, gameweek)),
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
    await expect(card).toContainText(language === "tr" ? "Bonus bekleniyor" : "Bonus pending");
    await expect(card.getByRole("heading", { level: 2 })).toContainText(String(gameweek));
    // The card is the notice's next sibling: it stands beside it, before the decision.
    expect(
      await notice.evaluate((element) =>
        element.nextElementSibling?.hasAttribute("data-member-live-score"),
      ),
    ).toBe(true);
    expect(asked.bundle).toEqual([`/api/v1/fpl/entry/${ENTRY}/bundle?gw=${gameweek}`]);
    expect(asked.live).toEqual([`/api/v1/fpl/live/${gameweek}`]);

    // Refresh reads the live points again, and nothing else.
    await card.getByRole("button", { name: language === "tr" ? "Yenile" : "Refresh" }).click();
    await expect(card).toContainText(language === "tr" ? "Bonus eklendi" : "Bonus added");
    expect(asked.live).toHaveLength(2);
    expect(asked.bundle).toHaveLength(1);
  });
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
