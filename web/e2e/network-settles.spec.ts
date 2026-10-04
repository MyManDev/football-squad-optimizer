import { expect, test, type Request } from "@playwright/test";

import members from "../public/data/league/members.json" with { type: "json" };
import { REMEMBERED_LEAGUE_ID } from "./leagueState";

/**
 * Every page lets the network settle on the published tree served the way Pages serves it
 * (vite/pagesNotFound.ts): a document that is not published yet, such as the league
 * directory before its first publish, answers 404 with data/404.html. Chromium keeps a
 * response whose body is never read open until it is collected, so a reader that refused a
 * 404 without reading it kept every live league page from going network-idle.
 */
const member = members.payload.members.find((row) => row.member_kind === "human");
if (member === undefined) throw new Error("The published league lists no human member.");
const league = `/league/${REMEMBERED_LEAGUE_ID}`;

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
    const open = new Set<Request>();
    page.on("request", (request) => open.add(request));
    page.on("requestfinished", (request) => open.delete(request));
    page.on("requestfailed", (request) => open.delete(request));

    await page.goto(path);
    await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => undefined);

    expect([...open].map((request) => request.url())).toEqual([]);
  });
}
