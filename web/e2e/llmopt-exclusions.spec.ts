import { expect, test, type Route } from "@playwright/test";

import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../src/fixtures/league";
import { EXAMPLE_CLAIM } from "./identity";
import { installLeagueMocks } from "./leagueMocks";
import { holdModel, routeChat } from "./llmoptChat";

const API = process.env.VITE_ADVICE_API_ORIGIN?.replace(/\/$/, "");
const { leagueId, entryId } = EXAMPLE_CLAIM;
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,POST,OPTIONS",
  "access-control-allow-headers": "content-type,idempotency-key,authorization",
};

function answer(route: Route, json: unknown) {
  return route.request().method() === "OPTIONS"
    ? route.fulfill({ status: 204, headers: CORS })
    : route.fulfill({ json, headers: CORS });
}

for (const comparison of [false, true]) {
  test(`sixteen valid exclusions reach the optimizer${comparison ? " with an extra comparison exclusion" : ""} and draw a plan`, async ({
    page,
  }) => {
    test.skip(!API, "API build required");
    await installLeagueMocks(page);
    await page.addInitScript(() => localStorage.setItem("squadopt.language", "en"));
    const squad = mockEntrySquadEnvelopes[entryId]!.payload;
    const excluded = Array.from({ length: 16 }, (_, i) => ({
      id: 900001 + i,
      name: `Excluded ${i + 1}`,
      team: "Brighton",
    }));
    const target = { id: 900017, name: "Comparison Target", team: "Arsenal" };
    await page.route(`${API}/api/v1/contributions/players`, (route) =>
      answer(route, {
        season: squad.season,
        players: [
          ...excluded,
          target,
          ...[...squad.starting_xi, ...squad.bench].map(({ player_id, name, team }) => ({
            id: player_id,
            name,
            team,
          })),
        ],
      }),
    );
    await page.route(`${API}/api/v1/leagues/${leagueId}/capabilities`, (route) =>
      answer(route, {
        contract_version: "league_capabilities_v1",
        league_id: leagueId,
        capture_snapshot_id: squad.source_snapshot_id,
        season: squad.season,
        gameweek: squad.gameweek,
        strategies: { "saf-puan": { windows: [1], requires_rival: false } },
        top100: { available: false, weights: [] },
        managers_word: { available: false },
        preferences: { available: true },
      }),
    );
    await routeChat(page, API, (route) =>
      answer(route, {
        status: "draft",
        draft: {
          hard: excluded.map(({ id }) => ({ kind: "avoid_player", player_id: id })),
          soft: [],
          ...(comparison
            ? { comparison: { kind: "include_player", player_id: target.id, both: true } }
            : {}),
        },
      }),
    );
    const submitted: { avoid_players: number[]; include_players?: number[] }[] = [];
    await page.route(`${API}/api/v1/leagues/${leagueId}/entries/${entryId}/advice**`, (route) => {
      if (route.request().method() !== "POST") return answer(route, {});
      const { preferences } = route.request().postDataJSON();
      submitted.push(preferences);
      if (preferences.include_players?.includes(target.id))
        return route.fulfill({
          status: 202,
          headers: CORS,
          json: { job_id: "with-comparison-target", status: "queued" },
        });
      const envelope = mockEntryAdviceEnvelope(entryId, "saf-puan", 1);
      return answer(route, {
        ...envelope,
        payload: { ...envelope.payload, preferences, preferences_scope: "all_selected_weeks" },
      });
    });
    await page.route(`${API}/api/v1/advice-jobs/with-comparison-target`, (route) =>
      answer(route, { job_id: "with-comparison-target", status: "queued" }),
    );
    await page.goto(`/league/${leagueId}/members/${entryId}/llmopt`);
    await holdModel(page);
    await page
      .getByRole("textbox", { name: "Plan instructions" })
      .fill("Exclude all sixteen listed players.");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect(
      page.getByRole("button", { name: /^Remove · Exclude player · Excluded / }),
    ).toHaveCount(16);
    const compute = page.getByRole("button", { name: "Compute plans", exact: true });
    await expect(compute).toBeEnabled();
    await compute.click();
    const avoided = [...excluded.map(({ id }) => id), ...(comparison ? [target.id] : [])];
    await expect
      .poll(() =>
        submitted.some(
          (preferences) => JSON.stringify(preferences.avoid_players) === JSON.stringify(avoided),
        ),
      )
      .toBe(true);
    if (comparison)
      await expect
        .poll(() =>
          submitted.some((preferences) => preferences.include_players?.includes(target.id)),
        )
        .toBe(true);
    const plan = page.locator("article[data-plan-ready]").first();
    await expect(plan.locator("[data-player-motion]")).toHaveCount(15);
  });
}
