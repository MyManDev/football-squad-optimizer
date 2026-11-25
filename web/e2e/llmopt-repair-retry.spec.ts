import { expect, test } from "@playwright/test";
import { mockEntryAdviceEnvelope } from "../src/fixtures/league";
import {
  checkedPreferences,
  preferenceScope,
} from "../src/features/league/advice/decisionPreferences";
import type { AdviceRequest } from "../src/features/league/advice/adviceClient";
import { LLMOPT_COPY } from "../src/features/league/llmopt/copy";
import { holdModel, routeChat } from "./llmoptChat";
import {
  ADVICE,
  API,
  DATA_ID,
  ENTRY,
  PAGE,
  answer,
  checkButton,
  installMember,
  instructions,
} from "./llmoptRepairMocks";

test("an explicit main retry closes its failed run and submits the unchanged rules", async ({
  page,
}) => {
  test.skip(!API, "API-origin build required");
  const { release } = await installMember(page, "tr");
  release.threeWeek = true;
  const copy = LLMOPT_COPY.tr;
  const events: string[] = [];
  const submissions: AdviceRequest[] = [];
  await page.route(`${API}/api/v1/llmopt/runs/*/cancel`, (route) => {
    if (route.request().method() === "POST")
      events.push(`close:${new URL(route.request().url()).pathname.split("/").at(-2)}`);
    return answer(route, {});
  });
  await page.route(ADVICE, (route) => {
    if (route.request().method() !== "POST")
      return answer(route, { error: { code: "NOT_COMPUTED" } }, 404);
    const request = route.request().postDataJSON() as AdviceRequest;
    submissions.push(request);
    events.push(`submit:${request.run?.run_id}`);
    const first = submissions.length === 1;
    return answer(
      route,
      { error: { code: first ? "MODEL_INPUTS_UNAVAILABLE" : "RUN_BUDGET_EXHAUSTED" } },
      first ? 503 : 409,
    );
  });
  await routeChat(page, API, (route) =>
    answer(route, { status: "draft", draft: { window: 3, hard: [{ kind: "no_hits" }], soft: [] } }),
  );
  await page.goto(PAGE);
  await holdModel(page);
  await instructions(page, "tr", "Üç hafta boyunca transfer cezası alma.");
  const compute = page.getByRole("button", { name: copy.compute });
  await compute.click();
  const status = page.locator("[data-rule-repairs]").getByRole("status");
  await expect(status).toHaveText(copy.repairs.missing);
  await expect(compute).toBeEnabled();
  expect(submissions).toHaveLength(1);
  await compute.click();
  await expect(status).toHaveText(copy.repairs.budget);
  await expect(compute).toBeEnabled();
  expect(submissions).toHaveLength(2);
  const [first, second] = submissions;
  expect(first!.run?.run_id).toMatch(/^[a-f0-9]{32}$/);
  expect(second!.run?.run_id).toMatch(/^[a-f0-9]{32}$/);
  expect(second!.run?.run_id).not.toBe(first!.run?.run_id);
  expect(second!.run?.stage).toBe("base");
  expect(second!.preferences).toEqual(first!.preferences);
  expect(events).toEqual([
    `submit:${first!.run!.run_id}`,
    `close:${first!.run!.run_id}`,
    `submit:${second!.run!.run_id}`,
  ]);
});

test("a transient candidate failure and a mismatched replay preserve checked changes on their run", async ({
  page,
}) => {
  test.skip(!API, "API-origin build required");
  const { squad, release } = await installMember(page, "en");
  release.threeWeek = true;
  const copy = LLMOPT_COPY.en.repairs;
  const counts = [3, 2].map((count) => ({ kind: "club_count", club: "Club 1", count }));
  await routeChat(page, API, (route) =>
    answer(route, { status: "draft", draft: { window: 3, hard: counts, soft: [] } }),
  );
  const submissions: AdviceRequest[] = [];
  let retrySecond = false;
  let mismatch = true;
  await page.route(ADVICE, (route) => {
    if (route.request().method() !== "POST")
      return answer(route, { error: { code: "NOT_COMPUTED" } }, 404);
    const body = route.request().postDataJSON() as AdviceRequest;
    submissions.push(body);
    const rules = checkedPreferences(body.preferences);
    const replay = !!rules.frozen_weeks;
    if (!replay && rules.club_counts?.[0]?.count === 3 && !retrySecond)
      return answer(route, { error: { code: "ADVICE_FAILED" } }, 503);
    const envelope = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3);
    const lineup = {
      bench: squad.bench,
      starting_xi: squad.starting_xi,
      captain: squad.starting_xi.find((p) => p.is_captain)!,
      vice_captain: squad.starting_xi.find((p) => p.is_vice_captain)!,
    };
    const score = replay && mismatch ? 9 : 10;
    const weeks = [0, 1, 2].map((offset) => ({
      gameweek: squad.gameweek + offset,
      transfers_in: [],
      transfers_out: [],
      chip: null,
      transfer_hit_points: 0,
      free_transfers_before: offset + 1,
      free_transfers_after: offset + 2,
      bank_after_tenths: squad.bank_tenths,
      expected_points: score,
      lineup,
    }));
    return answer(route, {
      ...envelope,
      payload: {
        ...envelope.payload,
        ...lineup,
        plan_data_id: DATA_ID,
        solver_status: "FEASIBLE",
        ...(body.model === "football"
          ? {
              prediction_model: {
                id: "football",
                version: "test-v1",
                experimental: true,
                fingerprint: DATA_ID,
              },
            }
          : {}),
        chip: null,
        moves: [],
        bank_after_tenths: squad.bank_tenths,
        expected_own_points: score,
        transfer_hit_points: 0,
        free_transfers_after: 2,
        plan_weeks: weeks,
        preferences: rules,
        preferences_scope: preferenceScope(rules),
      },
    });
  });
  await page.goto(PAGE);
  await holdModel(page);
  await instructions(page, "en", "Require both club counts");
  const region = page.locator("[data-rule-repairs]");
  const check = checkButton(page, "en");
  const options = region.locator("[data-repair-plan]");
  await check.click();
  await expect(region.getByRole("status")).toHaveText(copy.unconfirmed);
  await expect(options).toHaveCount(1);
  const first = options.first();
  const id = await first.getAttribute("data-repair-plan");
  expect(id).toMatch(/^[a-f0-9]{64}$/);
  expect(submissions).toHaveLength(2);
  retrySecond = true;
  await check.click();
  await expect(options).toHaveCount(2);
  expect(await first.getAttribute("data-repair-plan")).toBe(id);
  expect(submissions).toHaveLength(3);
  expect(submissions[2]).toEqual(submissions[1]);
  await first.getByRole("button").click();
  await expect(region.getByRole("status")).toHaveText(copy.unconfirmed);
  await expect(options).toHaveCount(2);
  await expect(check).toBeEnabled();
  await expect(page.locator("article[data-plan-id]")).toHaveCount(0);
  mismatch = false;
  await check.click();
  await expect(page.locator(`article[data-plan-id="${id}"]`)).toBeVisible();
  expect(submissions[3]?.preferences?.frozen_weeks).toHaveLength(3);
  expect(submissions[4]).toEqual(submissions[3]);
  expect(submissions).toHaveLength(5);
  expect(new Set(submissions.map((request) => request.run?.run_id)).size).toBe(1);
  expect(new Set(submissions.map((request) => JSON.stringify(request))).size).toBe(3);
});
