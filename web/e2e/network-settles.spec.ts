import { expect, test, type Page, type Request, type Route } from "@playwright/test";

import members from "../public/data/league/members.json" with { type: "json" };
import { REMEMBERED_LEAGUE_ID } from "./leagueState";

/**
 * No page leaves a request open. Chromium keeps a response whose body is never read open
 * until it is collected, so a reader that refused a 404 without reading it kept every live
 * league page from going network-idle. The preview answers a missing file the way Pages
 * does (vite/pagesNotFound.ts), and each reader that can refuse an answer is made to refuse
 * one here, whatever the published tree holds.
 */
const member = members.payload.members.find((row) => row.member_kind === "human");
if (member === undefined) throw new Error("The published league lists no human member.");
const league = `/league/${REMEMBERED_LEAGUE_ID}`;

/**
 * Send the request to an address the preview does not serve, so the refusal is the
 * server's own 404 with data/404.html. A refusal fulfilled by Playwright hands the page a
 * body that is complete at once, and Chromium ends that request whether or not it is read.
 */
function unpublished(route: Route) {
  const url = new URL(route.request().url());
  url.pathname = url.pathname.replace(/\.json$/, ".unpublished.json");
  return route.continue({ url: url.toString() });
}

async function openRequestsAfter(page: Page, path: string): Promise<string[]> {
  const open = new Set<Request>();
  page.on("request", (request) => open.add(request));
  page.on("requestfinished", (request) => open.delete(request));
  page.on("requestfailed", (request) => open.delete(request));
  await page.goto(path);
  await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => undefined);
  return [...open].map((request) => request.url());
}

test.beforeEach(async ({ page }) => {
  // CI builds with the production API origin; no spec may reach it (e2e/leagueMocks.ts).
  await page.route("**/api/v1/**", (route) => route.abort("connectionrefused"));
});

const PAGES = [
  "/",
  "/moves",
  "/rivals",
  "/fixtures",
  "/status",
  league,
  `${league}/members`,
  `${league}/members/${member.entry_id}`,
  `${league}/members/${member.entry_id}/history`,
];

for (const path of PAGES) {
  test(`${path} leaves no request open`, async ({ page }) => {
    expect(await openRequestsAfter(page, path)).toEqual([]);
  });
}

// Each reader of the published tree, refused by the server. The readers of the compute
// service sit on another origin the preview cannot answer for; their unit tests cover them.
const REFUSALS: { reader: string; path: string; unpublish?: string }[] = [
  { reader: "the league directory", path: `${league}/members`, unpublish: "**/data/leagues.json" },
  { reader: "a league document", path: `${league}/members/1` },
  { reader: "the site data client", path: "/gw/2026-27/38" },
  { reader: "the fixture list", path: "/fixtures", unpublish: "**/data/fixtures.json" },
];

for (const { reader, path, unpublish } of REFUSALS) {
  test(`${reader} refused leaves no request open`, async ({ page }) => {
    if (unpublish) await page.route(unpublish, unpublished);
    expect(await openRequestsAfter(page, path)).toEqual([]);
  });
}
