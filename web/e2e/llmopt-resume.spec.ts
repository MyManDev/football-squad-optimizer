import { expect, test, type Route } from "@playwright/test";

import type { DecisionPreferences } from "../src/features/league/advice/decisionPreferences";
import {
  mockEntryAdviceEnvelope,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../src/fixtures/league";
import { EXAMPLE_CLAIM } from "./identity";
import { installLeagueMocks, openCalendar } from "./leagueMocks";

const API = process.env.VITE_ADVICE_API_ORIGIN?.replace(/\/$/, "");
const LEAGUE = mockLeagueMembersEnvelope.payload.league_id;
const ENTRY = EXAMPLE_CLAIM.entryId;
const PAGE = `/league/${LEAGUE}/members/${ENTRY}/llmopt`;
const JOB = "llmopt-test-job";
const HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type, idempotency-key",
};

function answer(route: Route, json: unknown, status = 200) {
  return route.request().method() === "OPTIONS"
    ? route.fulfill({ status: 204, headers: HEADERS })
    : route.fulfill({ json, status, headers: HEADERS });
}

for (const reloadAt of ["base", "preferred"] as const) {
  test(`reloading restores the ${reloadAt} job and keeps POSTs tied to confirmation`, async ({
    page,
  }) => {
    test.skip(!API, "API build required");
    await installLeagueMocks(page);
    await page.addInitScript(() => localStorage.setItem("squadopt.language", "en"));
    const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
    const calendar = openCalendar();
    const posts: DecisionPreferences[] = [];
    const reads: DecisionPreferences[] = [];
    let polls = 0;
    let completed = false;
    await page.route("**/data/fixtures.json", (route) => route.fulfill({ json: calendar }));
    const captain = squad.starting_xi[0]!;
    await page.route(`${API}/api/v1/contributions/players`, (route) =>
      answer(route, {
        season: squad.season,
        players: [{ id: captain.player_id, name: captain.name, team: captain.team }],
      }),
    );
    await page.route(`${API}/api/v1/llmopt/intent`, (route) =>
      answer(route, {
        status: "draft",
        draft: { hard: [{ kind: "no_hits" }], soft: [{ kind: "hold_transfers" }] },
      }),
    );
    await page.route(`${API}/api/v1/leagues/${LEAGUE}/capabilities`, (route) =>
      answer(route, {
        contract_version: "league_capabilities_v1",
        league_id: LEAGUE,
        capture_snapshot_id: squad.source_snapshot_id,
        season: squad.season,
        gameweek: squad.gameweek,
        strategies: { "saf-puan": { windows: [1], requires_rival: false } },
        top100: { available: false, weights: [] },
        managers_word: { available: false },
        preferences: { available: true },
      }),
    );
    await page.route(`${API}/api/v1/advice-jobs/${JOB}`, (route) => {
      polls += 1;
      return answer(route, { job_id: JOB, status: completed ? "completed" : "queued" });
    });
    await page.route(`${API}/api/v1/leagues/${LEAGUE}/entries/${ENTRY}/advice**`, (route) => {
      const request = route.request();
      if (request.method() === "OPTIONS") return answer(route, null);
      const url = new URL(request.url());
      const preferences = JSON.parse(url.searchParams.get("preferences")!) as DecisionPreferences;
      if (request.method() === "POST") {
        posts.push(request.postDataJSON().preferences);
        if (!completed && Boolean(preferences.hold_transfers) === (reloadAt === "preferred"))
          return answer(route, { job_id: JOB, status: "queued" }, 202);
      } else reads.push(preferences);
      const envelope = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
      envelope.payload.moves = preferences.hold_transfers
        ? []
        : mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3).payload.moves;
      return answer(route, {
        ...envelope,
        payload: {
          ...envelope.payload,
          expected_own_points: preferences.hold_transfers ? 45 : 48,
          bank_after_tenths: 6,
          preferences,
          preferences_scope: "all_selected_weeks",
        },
      });
    });

    await page.goto(PAGE);
    await page.getByRole("textbox", { name: "Plan instructions" }).fill("No hits. Prefer to roll.");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    const rule = page.getByRole("listitem").filter({ hasText: "No transfer hits" });
    const compute = page.getByRole("button", { name: "Compute plans" });
    await expect(rule).toBeVisible();
    await page.reload();
    await expect(rule).toBeVisible();
    expect(posts).toHaveLength(0);
    expect(reads).toHaveLength(0);

    await compute.click();
    await expect.poll(() => polls).toBeGreaterThan(0);
    const beforeReload = polls;
    await page.reload();
    await expect(rule).toBeVisible();
    await expect.poll(() => polls).toBeGreaterThan(beforeReload);
    expect(posts).toHaveLength(reloadAt === "base" ? 1 : 2);
    completed = true;
    await expect.poll(() => posts.length).toBe(2);
    await expect(compute).toBeEnabled();
    const base = page.getByRole("article").filter({ hasText: "Base plan" });
    await expect(base.getByText("Expected net points", { exact: true })).toBeVisible();
    expect(posts.map(({ hold_transfers }) => Boolean(hold_transfers))).toEqual([false, true]);

    reads.length = 0;
    await page.reload();
    await expect(base.getByText("Expected net points", { exact: true })).toBeVisible();
    await expect.poll(() => reads.length).toBe(2);
    expect(posts).toHaveLength(2);
    expect(reads).toEqual(expect.arrayContaining(posts));

    await page.getByRole("button", { name: "Remove · Roll the transfer" }).click();
    await page.reload();
    await expect(rule).toBeVisible();
    await expect(page.getByRole("heading", { name: "Base plan" })).toHaveCount(0);
    expect(reads).toHaveLength(2);

    calendar.payload.gameweeks[0]!.deadline_utc = "2998-01-01T00:00:00Z";
    await page.reload();
    await expect(page.getByText("No rules yet", { exact: true })).toHaveCount(3);
    await expect(page.getByRole("heading", { name: "Base plan" })).toHaveCount(0);
    expect(reads).toHaveLength(2);
    expect(posts).toHaveLength(2);
  });
}
