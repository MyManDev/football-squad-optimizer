import { createHash } from "node:crypto";

import { expect, test, type Page } from "@playwright/test";

import fixture from "../src/fixtures/device-plan/instances.json" with { type: "json" };
import { bundleHolding, fixtureCaptureTable, STANDINGS_EXAMPLES } from "../src/fixtures/forwarder";
import { mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";
import { installLeagueMocks } from "./leagueMocks";

/**
 * #983 step 4 with a mocked FPL forwarder: a classic league the site does not publish, typed
 * on the entry page, opens from the forwarder's standings, and a member chosen from it opens
 * with the plan the device solves (the real worker and solver) from the newest capture table
 * the directory names. A head-to-head id is named. With the forwarder down, a typed league
 * cannot be opened and the listed league still opens from the published tree. `/entry/<id>`
 * opens one team on its own.
 */

const copy = MESSAGES.tr;
const CAPTURE = "fpl-live-20261016T060000Z-0123456789ab";
const TABLE = fixtureCaptureTable(CAPTURE);
const TABLE_BYTES = `${JSON.stringify({
  contract_version: "provisional_league_ui_v1",
  generated_at_utc: "2026-10-16T08:00:00Z",
  source_kind: "live",
  payload: TABLE,
})}\n`;
const TABLE_SHA = createHash("sha256").update(TABLE_BYTES, "utf8").digest("hex");
const FIRST = STANDINGS_EXAMPLES.first_page;
const LAST = STANDINGS_EXAMPLES.last_page;
const LEAGUE = FIRST.league.id;
const HEAD_TO_HEAD = 4242;
const PUBLISHED = mockLeagueMembersEnvelope.payload;
const ENTRY = FIRST.results[0]!.entry;
const member = fixture.members[2]!;
// The parity fixture member's fifteen, the first eleven a legal formation.
const FIFTEEN = [101, 111, 114, 115, 116, 131, 132, 136, 139, 154, 155, 105, 123, 148, 156];
const WORTH = Object.values(member.entry.sell_tenths).reduce((sum, price) => sum + price, 0);
const BUNDLE = bundleHolding(ENTRY, TABLE.gameweek, FIFTEEN, {
  bank: member.entry.bank_tenths,
  value: member.entry.bank_tenths + WORTH,
  captain: 132,
  vice: 139,
});
const MARKED = { "x-squadopt-fpl": "1", "content-type": "application/json; charset=utf-8" };

/**
 * The published example league in a directory whose line names the capture's table, a
 * calendar with both weeks open, and the forwarder up or down. Returns what it was asked.
 */
async function serveSite(page: Page, forwarder: "up" | "down") {
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "tr"));
  await installLeagueMocks(page);
  await page.route("**/data/leagues.json", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        contract_version: "league_directory_v1",
        generated_at_utc: "2026-10-16T08:00:00Z",
        source_kind: "live",
        payload: {
          leagues: [
            {
              league_id: PUBLISHED.league_id,
              league_name: PUBLISHED.league_name,
              season: PUBLISHED.season,
              gameweek: PUBLISHED.gameweek,
              path: "league",
              device_plan: `device/${CAPTURE}/device-plan.json`,
              device_plan_sha256: TABLE_SHA,
            },
          ],
        },
      }),
    }),
  );
  await page.route(/\/data\/device\//, (route) =>
    route.fulfill({ contentType: "application/json", body: TABLE_BYTES }),
  );
  await page.route("**/data/fixtures.json", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        contract_version: "fixtures_v1",
        generated_at_utc: "2026-10-16T08:00:00Z",
        source_kind: "live",
        payload: {
          season: TABLE.season,
          source_snapshot_id: CAPTURE,
          captured_at_utc: "2026-10-16T06:00:00Z",
          current_gameweek: PUBLISHED.gameweek,
          unscheduled_count: 0,
          gameweeks: [PUBLISHED.gameweek, TABLE.gameweek].map((gameweek) => ({
            gameweek,
            deadline_utc: "2999-01-01T00:00:00Z",
            fixtures: [],
          })),
        },
      }),
    }),
  );
  const asked: string[] = [];
  await page.route("**/api/v1/fpl/**", (route) => {
    const { pathname, search } = new URL(route.request().url());
    asked.push(`${pathname}${search}`);
    if (forwarder === "down") {
      // A forwarder that is not deployed: the site's shell answers its paths.
      return route.fulfill({ contentType: "text/html", body: "<!doctype html><html></html>" });
    }
    const answer = (status: number, value: unknown) =>
      route.fulfill({ status, headers: MARKED, body: JSON.stringify(value) });
    if (pathname === `/api/v1/fpl/standings/${LEAGUE}`) {
      return answer(200, search === "?page=1" ? FIRST : LAST);
    }
    if (pathname === `/api/v1/fpl/standings/${HEAD_TO_HEAD}`) {
      return answer(404, { error: "head_to_head_league", league: HEAD_TO_HEAD });
    }
    if (pathname === `/api/v1/fpl/entry/${ENTRY}/bundle` && search === `?gw=${TABLE.gameweek}`) {
      return answer(200, BUNDLE);
    }
    return answer(404, { error: "not_found" });
  });
  return asked;
}

/** Types a league number on the entry page and asks for it. */
async function typeLeague(page: Page, league: number) {
  await page.goto("/");
  await page.getByLabel(copy.leagueEntry.label, { exact: true }).fill(String(league));
  await page.getByRole("button", { name: copy.leagueEntry.submit, exact: true }).click();
}

/** The device's plan on the page: the real worker solved it, and its moves are named. */
async function expectDevicePlan(page: Page) {
  await expect(page.locator("[data-device-state='done']")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(copy.leagueMembers.adviceComputedBadge)).toBeVisible();
  const names = new Map(TABLE.players.map((player) => [player.id, player.name]));
  for (const move of member.reference.moves) {
    await expect(page.getByText(names.get(move.in!)!).first()).toBeVisible();
  }
}

test("a typed unlisted league opens from the forwarder, and a member opens with a device plan", async ({
  page,
}) => {
  const asked = await serveSite(page, "up");
  await typeLeague(page, LEAGUE);
  await expect(page).toHaveURL(`/league/${LEAGUE}`);
  await expect(page.getByRole("heading", { level: 1, name: FIRST.league.name! })).toBeVisible();
  // The end of the table is in view, so the next page is read as well; there is no third.
  await expect(page.getByRole("link", { name: LAST.results[0]!.entry_name })).toBeVisible();
  await expect(page.getByRole("button", { name: copy.forwarded.more })).toHaveCount(0);
  expect(asked).toEqual([
    `/api/v1/fpl/standings/${LEAGUE}?page=1`,
    `/api/v1/fpl/standings/${LEAGUE}?page=2`,
  ]);
  // The visitor's league stays the published one: a forwarded league is never chosen.
  expect(await page.evaluate(() => localStorage.getItem("squadopt.league"))).toBe(
    String(PUBLISHED.league_id),
  );

  await page.getByRole("link", { name: FIRST.results[0]!.entry_name }).click();
  await expect(page).toHaveURL(`/league/${LEAGUE}/members/${ENTRY}`);
  await expect(
    page.getByRole("heading", { level: 1, name: FIRST.results[0]!.entry_name }),
  ).toBeVisible();
  await expectDevicePlan(page);
  expect(asked).toContain(`/api/v1/fpl/entry/${ENTRY}/bundle?gw=${TABLE.gameweek}`);
  // Nothing of the forwarded league's published tree exists, so nothing of it is shown.
  await expect(page.getByText(copy.suggestionHistory.title)).toHaveCount(0);
});

test("a typed head-to-head league is named", async ({ page }) => {
  await serveSite(page, "up");
  await typeLeague(page, HEAD_TO_HEAD);
  await expect(page).toHaveURL(`/league/${HEAD_TO_HEAD}`);
  await expect(page.getByRole("status")).toHaveText(copy.leagueEntry.headToHead(HEAD_TO_HEAD));
});

test("with the forwarder down a typed league is not opened, and the listed league still is", async ({
  page,
}) => {
  const asked = await serveSite(page, "down");
  await typeLeague(page, LEAGUE);
  await expect(page.getByRole("status")).toHaveText(copy.leagueEntry.cannotOpen(LEAGUE));
  const listed = page.getByRole("navigation", { name: copy.leagueEntry.listedLeagues });
  await listed.getByRole("link", { name: PUBLISHED.league_name }).click();
  await expect(page).toHaveURL(`/league/${PUBLISHED.league_id}`);
  await expect(page.getByText(copy.leagueEntry.cannotOpen(LEAGUE))).toHaveCount(0);

  // The published member page reads the published tree, and asks the forwarder nothing more
  // than it asked before (its live week only once a deadline has passed).
  const before = asked.length;
  const human = PUBLISHED.members.find((row) => row.member_kind === "human")!;
  await page.goto(`/league/${PUBLISHED.league_id}/members/${human.entry_id}`);
  await expect(page.getByRole("heading", { level: 1, name: human.team_name! })).toBeVisible();
  expect(asked.slice(before)).toEqual([]);
});

test("/entry/<id> opens one team on its own with a device plan", async ({ page }) => {
  const asked = await serveSite(page, "up");
  await page.goto(`/entry/${ENTRY}`);
  await expect(page.getByRole("heading", { level: 1, name: BUNDLE.entry.name })).toBeVisible();
  await expectDevicePlan(page);
  expect(asked).toEqual([`/api/v1/fpl/entry/${ENTRY}/bundle?gw=${TABLE.gameweek}`]);
  await expect(page.getByRole("link", { name: copy.forwarded.backToLeague })).toHaveCount(0);
});
