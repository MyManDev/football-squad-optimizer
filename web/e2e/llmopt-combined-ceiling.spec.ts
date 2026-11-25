import { expect, test, type Route } from "@playwright/test";
import { readFileSync } from "node:fs";

import type { DecisionPreferences } from "../src/features/league/advice/decisionPreferences";
import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../src/fixtures/league";
import { EXAMPLE_CLAIM } from "./identity";
import { installLeagueMocks } from "./leagueMocks";
import { holdModel, routeChat } from "./llmoptChat";

const API = process.env.VITE_ADVICE_API_ORIGIN?.replace(/\/$/, "");
const { leagueId, entryId } = EXAMPLE_CLAIM;
const PAGE = `/league/${leagueId}/members/${entryId}/llmopt`;
const frozenRequests = JSON.parse(
  readFileSync(
    new URL("../../tests/fixtures/llmopt/develop_three_week_requests.json", import.meta.url),
    "utf8",
  ),
).requests as { path: string; body: string; cache_key: string }[];
const HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,POST,OPTIONS",
  "access-control-allow-headers": "content-type,idempotency-key",
};

function answer(route: Route, json: unknown) {
  return route.request().method() === "OPTIONS"
    ? route.fulfill({ status: 204, headers: HEADERS })
    : route.fulfill({ json, headers: HEADERS });
}

for (const limit of [0, 15, undefined]) {
  test(`a third preference ${limit === undefined ? "without a limit is combined" : `with a ${limit / 10}-point limit waits for its own price`}`, async ({
    page,
  }) => {
    test.skip(!API, "API build required");
    await installLeagueMocks(page);
    await page.addInitScript(() => localStorage.setItem("squadopt.language", "en"));
    const squad = mockEntrySquadEnvelopes[entryId]!.payload;
    const outgoing = squad.starting_xi.filter(({ position }) => position === "MID").slice(0, 3);
    expect(outgoing).toHaveLength(3);
    const players = outgoing.map((player, index) => ({
      ...player,
      player_id: 9081401 + index,
      name: ["First Target", "Second Target", "Third Target"][index]!,
    }));
    const posts: DecisionPreferences[] = [];
    const wire: { path: string; body: string | null }[] = [];
    const reads: DecisionPreferences[] = [];

    await page.route(`${API}/api/v1/contributions/players`, (route) =>
      answer(route, {
        season: squad.season,
        players: players.map(({ player_id, name, team }) => ({ id: player_id, name, team })),
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
        ...(limit === undefined ? { llmopt_vnext: true } : {}),
        top100: { available: false, weights: [] },
        managers_word: { available: false },
      }),
    );
    await routeChat(page, API, (route) =>
      answer(route, {
        status: "draft",
        draft: {
          window: 3,
          hard: [{ kind: "no_hits" }],
          soft: players.map(({ player_id }, index) => ({
            kind: "include_player",
            player_id,
            ...(index < 2
              ? { max_cost_tenths: 15 }
              : limit === undefined
                ? {}
                : { max_cost_tenths: limit }),
          })),
        },
      }),
    );
    await page.route(`${API}/api/v1/leagues/${leagueId}/entries/${entryId}/advice**`, (route) => {
      const request = route.request();
      if (request.method() === "OPTIONS") return answer(route, null);
      if (request.method() === "POST") {
        wire.push({ path: new URL(request.url()).pathname, body: request.postData() });
      }
      const preferences =
        request.method() === "POST"
          ? (request.postDataJSON() as { preferences: DecisionPreferences }).preferences
          : (JSON.parse(
              new URL(request.url()).searchParams.get("preferences") ?? "{}",
            ) as DecisionPreferences);
      (request.method() === "POST" ? posts : reads).push(preferences);
      const wanted = preferences.include_players ?? [];
      const signing = players.filter(({ player_id }) => wanted.includes(player_id));
      const envelope = mockEntryAdviceEnvelope(entryId, "saf-puan", 3);
      const moves = signing.map((player_in) => ({
        ...envelope.payload.moves[0]!,
        move_id: `target-${player_in.player_id}`,
        player_in,
        player_out: outgoing[players.indexOf(player_in)]!,
      }));
      const cost =
        wanted.length > 1
          ? 2.4
          : wanted[0] === players[0]!.player_id
            ? 1
            : wanted[0] === players[1]!.player_id
              ? 1.2
              : wanted.length
                ? 5
                : 0;
      return answer(route, {
        ...envelope,
        payload: {
          ...envelope.payload,
          moves,
          starting_xi: squad.starting_xi.map((player) => {
            const index = outgoing.findIndex(({ player_id }) => player_id === player.player_id);
            return index >= 0 && wanted.includes(players[index]!.player_id)
              ? players[index]!
              : player;
          }),
          plan_weeks: envelope.payload.plan_weeks!.map((week, index) => ({
            ...week,
            gameweek: squad.gameweek + index,
            transfers_in: index === 0 ? signing : [],
            transfers_out: index === 0 ? moves.map(({ player_out }) => player_out) : [],
            chip: null,
            transfer_hit_points: 0,
            expected_points: index === 0 ? 45 - cost : 44,
          })),
          preferences,
          preferences_scope: "all_selected_weeks",
        },
      });
    });

    await page.goto(PAGE);
    await holdModel(page);
    await page
      .getByRole("textbox", { name: "Plan instructions" })
      .fill("No hits. Prefer these three players within their individual point limits.");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await page.getByRole("button", { name: "Compute plans" }).click();
    const combined = page.getByRole("article").filter({
      has: page.getByRole("heading", { name: "Plan with all preferences" }),
    });
    await expect(combined.locator("[data-combined=applied]")).toHaveCount(
      limit === undefined ? 3 : 2,
    );
    await expect(
      combined.getByText("2.4 expected points lost against the base plan"),
    ).toBeVisible();
    expect(posts).toHaveLength(4);
    if (limit === undefined) {
      expect(wire).toEqual(frozenRequests.map(({ path, body }) => ({ path, body })));
    }
    const appliedIds = players
      .slice(0, limit === undefined ? 3 : 2)
      .map(({ player_id }) => player_id);
    expect(posts[3]?.include_players).toEqual(appliedIds);
    if (limit !== undefined) {
      await expect(combined.locator("[data-combined=left-out]")).toContainText("Third Target");
      for (const preferences of posts)
        expect(preferences.include_players ?? []).not.toContain(players[2]!.player_id);
    }

    if (limit === 0) {
      // A run saved by the earlier version may have accepted the unpriced bounded rule.
      await page.evaluate(() => {
        const key = Object.keys(sessionStorage).find((key) => key.startsWith("squadopt.llmopt:"))!;
        const saved = JSON.parse(sessionStorage.getItem(key)!);
        saved.confirmation.combined = [0, 1, 2];
        sessionStorage.setItem(key, JSON.stringify(saved));
      });
      await page.reload();
      await expect(combined.locator("[data-combined=applied]")).toHaveCount(2);
      await expect(combined.locator("[data-combined=left-out]")).toContainText("Third Target");
      await expect(combined).toHaveAttribute("data-plan-ready", "");
      expect(posts).toHaveLength(4);
      for (const preferences of reads)
        expect(preferences.include_players ?? []).not.toContain(players[2]!.player_id);
    }
  });
}
