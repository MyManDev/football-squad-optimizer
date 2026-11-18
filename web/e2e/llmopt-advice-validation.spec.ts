import { expect, test, type Route } from "@playwright/test";

import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../src/fixtures/league";
import { EXAMPLE_CLAIM } from "./identity";
import { installLeagueMocks } from "./leagueMocks";
import { holdModel, routeChat } from "./llmoptChat";

const API = process.env.VITE_ADVICE_API_ORIGIN?.replace(/\/$/, "");
const { leagueId, entryId } = EXAMPLE_CLAIM;
const HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,POST,OPTIONS",
  "access-control-allow-headers": "content-type,idempotency-key",
};

function answer(route: Route, json: unknown, status = 200) {
  return route.request().method() === "OPTIONS"
    ? route.fulfill({ status: 204, headers: HEADERS })
    : route.fulfill({ json, status, headers: HEADERS });
}

for (const stage of [
  "immediate",
  "completed",
  "corrupt-poll",
  "negative-opening",
  "negative-later",
  "negative-alternative",
] as const) {
  test(`LLMOPT rejects a ${stage} response without reporting a network failure`, async ({
    page,
  }) => {
    test.skip(!API, "API build required");
    await installLeagueMocks(page);
    await page.addInitScript(() => localStorage.setItem("squadopt.language", "en"));
    const squad = mockEntrySquadEnvelopes[entryId]!.payload;
    const player = squad.starting_xi[0]!;
    const negative = stage.startsWith("negative-");
    const window = stage === "negative-later" ? 3 : 1;
    let preferences: Record<string, unknown> | undefined;
    let posts = 0;
    let polls = 0;
    await page.route(`${API}/api/v1/contributions/players`, (route) =>
      answer(route, {
        season: squad.season,
        players: [
          { id: player.player_id, name: player.name, team: player.team },
          { id: 990001, name: "Excluded Signing", team: "Brighton" },
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
        strategies: { "saf-puan": { windows: [1, 3], requires_rival: false } },
        preferences: { available: true },
        top100: { available: false, weights: [] },
        managers_word: { available: false },
      }),
    );
    await routeChat(page, API, (route) =>
      answer(route, {
        status: "draft",
        draft: {
          hard: negative ? [{ kind: "avoid_player", player_id: 990001 }] : [{ kind: "no_hits" }],
          soft: [],
          window,
        },
      }),
    );
    await page.route(`${API}/api/v1/leagues/${leagueId}/entries/${entryId}/advice**`, (route) => {
      if (route.request().method() === "OPTIONS") return answer(route, null);
      if (route.request().method() === "POST") {
        posts += 1;
        preferences = route.request().postDataJSON().preferences;
        if (stage !== "immediate" && !negative)
          return answer(route, { job_id: "invalid-plan", status: "queued" }, 202);
      }
      const envelope = mockEntryAdviceEnvelope(entryId, "saf-puan", window);
      if (negative) {
        if (stage === "negative-opening") envelope.payload.transfer_hit_points = -4;
        if (stage === "negative-later") envelope.payload.plan_weeks![1]!.transfer_hit_points = -4;
        if (stage === "negative-alternative")
          envelope.payload.alternative_plan = {
            kind: "with_hits",
            overlap_applied: 0,
            transfer_hit_points: -4,
            expected_points_cost: 0,
          };
        return answer(route, {
          ...envelope,
          payload: {
            ...envelope.payload,
            preferences,
            preferences_scope: "all_selected_weeks",
          },
        });
      }
      return answer(route, {
        ...envelope,
        payload: { ...envelope.payload, entry_id: entryId + 1 },
      });
    });
    await page.route(`${API}/api/v1/advice-jobs/invalid-plan`, (route) => {
      if (route.request().method() === "OPTIONS") return answer(route, null);
      polls += 1;
      return stage === "corrupt-poll"
        ? route.fulfill({
            status: 200,
            body: "<html>",
            headers: { ...HEADERS, "content-type": "text/html" },
          })
        : answer(route, { job_id: "invalid-plan", status: "completed" });
    });

    await page.goto(`/league/${leagueId}/members/${entryId}/llmopt`);
    await holdModel(page);
    await page
      .getByRole("textbox", { name: "Plan instructions" })
      .fill(negative ? "Avoid Excluded Signing." : "No hits.");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    const compute = page.getByRole("button", { name: "Compute plans" });
    await compute.click();
    await expect(
      page.getByText("The computation did not complete.", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("The compute service could not be reached.", { exact: true }),
    ).toHaveCount(0);
    await expect(page.locator("article[data-plan-ready]")).toHaveCount(0);
    await expect(compute).toBeEnabled();
    expect(posts).toBe(1);
    expect(polls).toBe(stage === "immediate" || negative ? 0 : 1);
  });
}
