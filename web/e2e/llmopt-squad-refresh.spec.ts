import { expect, test, type Route } from "@playwright/test";

import { mockEntrySquadEnvelopes } from "../src/fixtures/league";
import { EXAMPLE_CLAIM } from "./identity";
import { installLeagueMocks, openCalendar } from "./leagueMocks";

const API = process.env.VITE_ADVICE_API_ORIGIN?.replace(/\/$/, "");
const { leagueId, entryId } = EXAMPLE_CLAIM;
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,POST,OPTIONS",
  "access-control-allow-headers": "content-type,idempotency-key",
};

function reply(route: Route, json: unknown, status = 200) {
  return route.request().method() === "OPTIONS"
    ? route.fulfill({ status: 204, headers: CORS })
    : route.fulfill({ json, status, headers: CORS });
}

for (const change of ["bank", "snapshot", "compute"] as const) {
  const title =
    change === "compute"
      ? "a squad change found by Compute keeps the rules across the requested reload"
      : `a successful ${change} refresh keeps the rules and drops the stale running plan`;
  test(title, async ({ page }) => {
    test.skip(!API, "API build required");
    await installLeagueMocks(page);
    await page.addInitScript(() => localStorage.setItem("squadopt.language", "en"));
    const original = mockEntrySquadEnvelopes[entryId]!;
    let envelope = original;
    let squadReads = 0;
    let advicePosts = 0;
    let jobReads = 0;
    const calendar = openCalendar();
    await page.route("**/data/fixtures.json", (route) => route.fulfill({ json: calendar }));
    await page.route(`**/data/league/entries/${entryId}.json`, (route) => {
      squadReads += 1;
      return route.fulfill({ json: envelope });
    });
    await page.route(`${API}/api/v1/contributions/players`, (route) =>
      reply(route, {
        season: original.payload.season,
        players: [...original.payload.starting_xi, ...original.payload.bench].map(
          ({ player_id, name, team }) => ({ id: player_id, name, team }),
        ),
      }),
    );
    await page.route(`${API}/api/v1/leagues/${leagueId}/capabilities`, (route) =>
      reply(route, {
        contract_version: "league_capabilities_v1",
        league_id: leagueId,
        season: original.payload.season,
        gameweek: original.payload.gameweek,
        capture_snapshot_id: original.payload.source_snapshot_id,
        strategies: { "saf-puan": { windows: [1], requires_rival: false } },
        preferences: { available: true },
        top100: { available: false, weights: [] },
        managers_word: { available: false },
      }),
    );
    await page.route(`${API}/api/v1/leagues/${leagueId}/entries/${entryId}/advice**`, (route) => {
      if (route.request().method() === "POST") {
        advicePosts += 1;
        return reply(route, { job_id: "refresh-old-plan", status: "queued" }, 202);
      }
      return reply(route, {});
    });
    await page.route(`${API}/api/v1/advice-jobs/refresh-old-plan`, (route) => {
      if (route.request().method() === "GET") jobReads += 1;
      return reply(route, { job_id: "refresh-old-plan", status: "queued" });
    });

    await page.goto(`/league/${leagueId}/members/${entryId}/llmopt`);
    const add = page.getByRole("button", { name: "Add rule", exact: true });
    const rolled = page.getByRole("button", { name: "Remove · Roll the transfer", exact: true });
    await add.click();
    await expect(rolled).toBeVisible();
    const results = page.getByRole("region", { name: "Plans" });
    const compute = page.getByRole("button", { name: "Compute plans", exact: true });
    if (change !== "compute") {
      await compute.click();
      await expect.poll(() => jobReads).toBeGreaterThan(0);
      await expect(results).toBeVisible();
    }

    envelope = {
      ...original,
      payload: {
        ...original.payload,
        ...(change === "snapshot"
          ? { source_snapshot_id: "fresh-squad-capture" }
          : { bank_tenths: original.payload.bank_tenths + 1 }),
      },
    };
    if (change === "compute") {
      await compute.click();
      const reload = page.getByRole("button", { name: "Reload", exact: true });
      await expect(reload).toBeVisible();
      expect(advicePosts).toBe(0);
      await reload.click();
    } else {
      const readsBeforeRefresh = squadReads;
      await page.clock.install();
      await page.clock.fastForward(61_000);
      await page.evaluate(() => {
        window.dispatchEvent(new Event("offline"));
        window.dispatchEvent(new Event("online"));
      });
      await expect.poll(() => squadReads).toBeGreaterThan(readsBeforeRefresh);
    }
    await expect(rolled).toBeVisible();
    await expect(results).toHaveCount(0);
    const expectedPosts = change === "compute" ? 0 : 1;
    expect(advicePosts).toBe(expectedPosts);

    await page.getByRole("combobox", { name: "Rule", exact: true }).selectOption("no_hits");
    await add.click();
    const noHits = page.getByRole("button", { name: "Remove · No transfer hits", exact: true });
    await expect(noHits).toBeVisible();
    await page.reload();
    await expect(rolled).toBeVisible();
    await expect(noHits).toBeVisible();
    await expect(results).toHaveCount(0);
    expect(advicePosts).toBe(expectedPosts);

    calendar.payload.gameweeks[0]!.deadline_utc = "2998-01-01T00:00:00Z";
    await page.reload();
    await expect(rolled).toHaveCount(0);
    await expect(noHits).toHaveCount(0);
    await expect(results).toHaveCount(0);
    expect(advicePosts).toBe(expectedPosts);
  });
}
