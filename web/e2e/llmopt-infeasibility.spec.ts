import { expect, test, type Route } from "@playwright/test";

import type { DecisionPreferences } from "../src/features/league/advice/decisionPreferences";
import {
  mockEntryAdviceEnvelope,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../src/fixtures/league";
import { EXAMPLE_CLAIM } from "./identity";
import { installLeagueMocks } from "./leagueMocks";

const API = process.env.VITE_ADVICE_API_ORIGIN?.replace(/\/$/, "");
const LEAGUE = mockLeagueMembersEnvelope.payload.league_id;
const ENTRY = EXAMPLE_CLAIM.entryId;
const PAGE = `/league/${LEAGUE}/members/${ENTRY}/llmopt`;
const JOB = "llmopt-budget-failure";
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type, idempotency-key",
};

function answer(route: Route, json: unknown, status = 200) {
  return route.request().method() === "OPTIONS"
    ? route.fulfill({ status: 204, headers: CORS })
    : route.fulfill({ json, status, headers: CORS });
}

const scenarios = {
  proven: "a proved budget shortfall offers a repair without changing the draft",
  witnessed: "a feasible repair budget omits an unproved shortfall",
  interrupted: "an interrupted solve leaves the draft intact and offers no repair",
} as const;

for (const failure of ["proven", "witnessed", "interrupted"] as const) {
  test(scenarios[failure], async ({ page }) => {
    test.skip(!API, "API build required");
    await installLeagueMocks(page);
    await page.addInitScript(() => localStorage.setItem("squadopt.language", "en"));

    const original = mockEntrySquadEnvelopes[ENTRY]!;
    const squad = { ...original.payload, bank_tenths: 26 };
    const keeper = squad.starting_xi.find(({ position }) => position === "GK")!;
    const posts: DecisionPreferences[] = [];
    let polls = 0;
    const instructions = "Bu hafta transferi sakla ve kalecimi tut. Kasada en az 3 milyon kalsın.";
    const requiredBank = { tenths: 30 };
    const repairedBank = { tenths: 26 };
    const rawError = "RAW_OPTIMIZER_DETAIL";

    await page.route(`**/data/league/entries/${ENTRY}.json`, (route) =>
      route.fulfill({ json: { ...original, payload: squad } }),
    );
    await page.route(`${API}/api/v1/contributions/players`, (route) =>
      answer(route, {
        season: squad.season,
        players: [{ id: keeper.player_id, name: keeper.name, team: keeper.team }],
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
        preferences: { available: true },
        managers_word: { available: false },
        top100: { available: false, weights: [] },
      }),
    );
    await page.route(`${API}/api/v1/llmopt/intent`, (route) => {
      if (route.request().method() === "OPTIONS") return answer(route, null);
      expect(route.request().postDataJSON().message).toBe(instructions);
      return answer(route, {
        status: "draft",
        draft: {
          window: 1,
          hard: [{ kind: "hold_transfers" }, { kind: "keep_player", player_id: keeper.player_id }],
          soft: [],
          min_bank: requiredBank,
        },
      });
    });
    await page.route(`${API}/api/v1/advice-jobs/${JOB}`, (route) => {
      if (route.request().method() === "OPTIONS") return answer(route, null);
      polls += 1;
      return answer(route, {
        job_id: JOB,
        status: "failed",
        error_code: failure === "interrupted" ? "ADVICE_FAILED" : "PLAN_NOT_FOUND",
        error_message: rawError,
        // Only a proved infeasible job is allowed to recommend a repair.
        // The interrupted case deliberately sends the same extra field to check that it is ignored.
        infeasibility: {
          repairs: [{ kind: "lower_bank_floor", tenths: repairedBank.tenths }],
          bank: {
            required: requiredBank.tenths,
            reachable: repairedBank.tenths,
            exact: failure !== "witnessed",
          },
        },
      });
    });
    await page.route(`${API}/api/v1/leagues/${LEAGUE}/entries/${ENTRY}/advice**`, (route) => {
      const request = route.request();
      if (request.method() === "OPTIONS") return answer(route, null);
      if (request.method() !== "POST")
        return answer(route, { error: { code: "NOT_COMPUTED" } }, 404);
      const body = request.postDataJSON() as { window: number; preferences: DecisionPreferences };
      expect(body.window).toBe(1);
      const preferences = body.preferences;
      posts.push(preferences);
      if (preferences.min_bank?.tenths !== repairedBank.tenths)
        return answer(route, { job_id: JOB, status: "queued" }, 202);
      const advice = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
      return answer(route, {
        ...advice,
        payload: {
          ...advice.payload,
          moves: [],
          bank_after_tenths: 26,
          expected_own_points: 48,
          transfer_hit_points: 0,
          plan_weeks: [
            {
              gameweek: squad.gameweek,
              transfers_in: [],
              transfers_out: [],
              transfer_hit_points: 0,
              chip: null,
              free_transfers_before: 1,
              free_transfers_after: 2,
              expected_points: 48,
              bank_after_tenths: 26,
            },
          ],
          preferences,
          preferences_scope: "selected_weeks",
        },
      });
    });

    await page.goto(PAGE);
    const main = page.getByRole("main");
    const compute = page.getByRole("button", { name: "Compute plans" });
    const keeperRule = main
      .getByRole("listitem")
      .filter({ hasText: `Keep player · ${keeper.name}` });
    const holdRule = main.getByRole("listitem").filter({ hasText: "Roll the transfer" });
    const originalBankRule = main.getByRole("listitem").filter({ hasText: "Keep at least £3.0m" });
    const alternative = main.getByRole("button", { name: "Apply suggested rules" });
    const diagnosis = main.getByRole("region", { name: "Why this plan is infeasible" });

    await main.getByRole("textbox", { name: "Plan instructions" }).fill(instructions);
    await main.getByRole("button", { name: "Send", exact: true }).click();
    await expect(originalBankRule).toBeVisible();
    await expect(keeperRule).toBeVisible();
    await expect(holdRule).toBeVisible();
    expect(posts).toHaveLength(0);

    await compute.click();
    await expect.poll(() => polls).toBeGreaterThan(0);
    await expect(compute).toBeEnabled();
    expect(posts).toHaveLength(1);
    expect(posts[0]).toMatchObject({
      keep_players: [keeper.player_id],
      hold_transfers: true,
      min_bank: requiredBank,
    });
    await expect(originalBankRule).toBeVisible();
    await expect(keeperRule).toBeVisible();
    await expect(holdRule).toBeVisible();
    await expect(main.locator("article[data-plan-ready]")).toHaveCount(0);
    await expect(main.getByText(rawError)).toHaveCount(0);

    if (failure === "interrupted") {
      const status = main.getByRole("article").getByRole("status");
      await expect(status).toContainText(
        /did not complete|could not complete|could not solve|search did not finish/i,
      );
      await expect(status).not.toContainText(/infeasible|impossible|contradict/i);
      await expect(status).not.toContainText(/timed out|deadline/i);
      await expect(diagnosis).toHaveCount(0);
      await expect(alternative).toHaveCount(0);

      const beforeRetry = polls;
      await compute.click();
      await expect.poll(() => polls).toBeGreaterThan(beforeRetry);
      expect(posts).toEqual([posts[0], posts[0]]);
      return;
    }

    await expect(diagnosis).toBeVisible();
    await expect(diagnosis).toContainText("£3.0m");
    await expect(diagnosis).toContainText("£2.6m");
    if (failure === "proven") {
      await expect(diagnosis).toContainText("The shortfall is £0.4m");
    } else {
      await expect(diagnosis).toContainText("A checked alternative leaves £2.6m");
      await expect(diagnosis).not.toContainText(/The most|shortfall/i);
    }
    await expect(alternative).toBeEnabled();
    expect(posts).toHaveLength(1);

    await alternative.click();
    await expect(originalBankRule).toHaveCount(0);
    await expect(
      main.getByRole("listitem").filter({ hasText: "Keep at least £2.6m" }),
    ).toBeVisible();
    await expect(keeperRule).toBeVisible();
    await expect(holdRule).toBeVisible();
    await expect(
      main.getByText("Suggested rules selected. Review them and calculate again.", { exact: true }),
    ).toBeVisible();
    await expect(compute).toBeEnabled();
    expect(posts).toHaveLength(1);

    await compute.click();
    const solved = main.locator("article[data-plan-ready]");
    await expect(
      solved.getByText("Expected net points", { exact: true }).locator("xpath=../dd"),
    ).toHaveText("48.0");
    await expect(
      solved.getByText("Remaining budget", { exact: true }).locator("xpath=../dd"),
    ).toHaveText("£2.6m");
    await expect(diagnosis).toHaveCount(0);
    expect(posts).toEqual([posts[0], { ...posts[0], min_bank: repairedBank }]);
  });
}

test("LLMOPT names the player and gameweek of a local rule conflict before submitting", async ({
  page,
}) => {
  test.skip(!API, "API build required");
  await installLeagueMocks(page);
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "en"));
  const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
  const keeper = squad.starting_xi.find(({ position }) => position === "GK")!;
  let advicePosts = 0;
  await page.route(`${API}/api/v1/contributions/players`, (route) =>
    answer(route, {
      season: squad.season,
      players: [{ id: keeper.player_id, name: keeper.name, team: keeper.team }],
    }),
  );
  await page.route(`${API}/api/v1/llmopt/intent`, (route) =>
    answer(route, {
      status: "draft",
      draft: {
        window: 3,
        hard: [
          { kind: "keep_player", player_id: keeper.player_id },
          { kind: "avoid_player", player_id: keeper.player_id, week: 2 },
        ],
        soft: [],
      },
    }),
  );
  await page.route(`${API}/api/v1/leagues/${LEAGUE}/entries/${ENTRY}/advice**`, (route) => {
    if (route.request().method() === "POST") advicePosts += 1;
    return answer(route, { error: { code: "NOT_COMPUTED" } }, 404);
  });

  await page.goto(PAGE);
  const main = page.getByRole("main");
  await main
    .getByRole("textbox", { name: "Plan instructions" })
    .fill("Kalecimi bu üç hafta tut ama ikinci hafta kadrodan çıkar.");
  await main.getByRole("button", { name: "Send", exact: true }).click();
  const alert = main.getByRole("alert");
  const compute = main.getByRole("button", { name: "Compute plans" });
  await expect(alert).toContainText(`In GW ${squad.gameweek + 1}`);
  await expect(alert).toContainText(`Keep player · ${keeper.name}`);
  await expect(alert).toContainText(`Exclude player · ${keeper.name}`);
  await expect(compute).toBeDisabled();
  expect(advicePosts).toBe(0);

  await main.getByRole("button", { name: /Remove · Exclude player/ }).click();
  await expect(alert).toHaveCount(0);
  await expect(compute).toBeEnabled();
  expect(advicePosts).toBe(0);
});
