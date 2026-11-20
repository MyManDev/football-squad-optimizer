import { expect, test, type Route } from "@playwright/test";

import type { DecisionPreferences } from "../src/features/league/advice/decisionPreferences";
import {
  mockEntryAdviceEnvelope,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../src/fixtures/league";
import { EXAMPLE_CLAIM } from "./identity";
import { installLeagueMocks } from "./leagueMocks";
import { holdModel, routeChat } from "./llmoptChat";
import { observeCompletedJob, reloadQueuedJob, startQueuedJob } from "./queuedAdviceJob";

const API = process.env.VITE_ADVICE_API_ORIGIN?.replace(/\/$/, "");
const LEAGUE = mockLeagueMembersEnvelope.payload.league_id;
const ENTRY = EXAMPLE_CLAIM.entryId;
const PAGE = `/league/${LEAGUE}/members/${ENTRY}/llmopt`;
const JOB = "llmopt-revision-with-player";
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

test("a chat revision keeps week one and prices both exact comparisons after reload", async ({
  page,
}) => {
  test.skip(!API, "API build required");
  await installLeagueMocks(page);
  await page.addInitScript(() => localStorage.setItem("squadopt.language", "en"));

  const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
  const envelope = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3);
  const opening = {
    starting_xi: envelope.payload.starting_xi!,
    bench: envelope.payload.bench!,
    captain: envelope.payload.captain!,
    vice_captain: envelope.payload.vice_captain!,
  };
  const keeper = opening.starting_xi.find(({ position }) => position === "GK")!;
  const replacements = opening.starting_xi
    .filter(
      ({ player_id, position }) =>
        position !== "GK" &&
        player_id !== opening.captain.player_id &&
        player_id !== opening.vice_captain.player_id,
    )
    .slice(0, 3);
  const target = { ...replacements[0]!, player_id: 9081310, name: "Bukayo Saka", team: "Arsenal" };
  const variants = {
    original: {
      arrivals: [{ ...replacements[0]!, player_id: 9081311, name: "Original Signing" }],
      points: [46, 44, 47],
      hits: 0,
      bank: 6,
      free: 2,
    },
    without: {
      arrivals: [{ ...replacements[0]!, player_id: 9081312, name: "Budget Signing" }],
      points: [46, 45, 49],
      hits: 0,
      bank: 20,
      free: 2,
    },
    with: {
      arrivals: [
        target,
        { ...replacements[1]!, player_id: 9081313, name: "Second Signing" },
        { ...replacements[2]!, player_id: 9081314, name: "Third Signing" },
      ],
      points: [46, 49, 50],
      hits: 4,
      bank: 13,
      free: 1,
    },
    shorter: { arrivals: [], points: [46], hits: 0, bank: 18, free: 2 },
  };
  type Variant = keyof typeof variants;
  const initialMessage = "Üç haftalık plan yap. İlk hafta transferi sakla ve kalecimi tut.";
  const revisionMessage =
    "İlk haftayı olduğu gibi bırak. İkinci hafta sonunda en az 1,2 milyon kalsın. İkinci hafta Saka varken ve yokken iki planı karşılaştır.";
  const shorterMessage = "Sadece ilk haftayı göster ve aynen koru. Saka karşılaştırmasını kaldır.";
  const initialDraft = {
    window: 3,
    hard: [
      { kind: "hold_transfers", week: 1 },
      { kind: "keep_player", player_id: keeper.player_id },
    ],
    soft: [],
  };
  const revisionDraft = {
    ...initialDraft,
    keep_weeks: [1],
    min_bank: { tenths: 12, week: 2 },
    comparison: { kind: "include_player", player_id: target.player_id, week: 2, both: true },
  };
  const posts: { kind: Variant; window: number; preferences: DecisionPreferences }[] = [];
  const cacheReads: Variant[] = [];
  let polls = 0;
  let completed = false;

  await page.route(`${API}/api/v1/contributions/players`, (route) =>
    answer(route, {
      season: squad.season,
      players: [keeper, target].map(({ player_id, name, team }) => ({ id: player_id, name, team })),
    }),
  );
  await page.route(`${API}/api/v1/leagues/${LEAGUE}/capabilities`, (route) =>
    answer(route, {
      contract_version: "league_capabilities_v1",
      league_id: LEAGUE,
      capture_snapshot_id: squad.source_snapshot_id,
      season: squad.season,
      gameweek: squad.gameweek,
      strategies: { "saf-puan": { windows: [1, 3], requires_rival: false } },
      preferences: { available: true },
      managers_word: { available: false },
      top100: { available: false, weights: [] },
    }),
  );
  await routeChat(page, API, (route) => {
    if (route.request().method() === "OPTIONS") return answer(route, null);
    const body = route.request().postDataJSON();
    if (body.message === initialMessage) {
      expect(body.reference_weeks ?? []).toEqual([]);
      return answer(route, { status: "draft", draft: initialDraft });
    }
    if (body.message === shorterMessage) {
      expect(body).toMatchObject({ draft: revisionDraft, reference_weeks: [1, 2, 3] });
      return answer(route, {
        status: "draft",
        draft: { ...initialDraft, window: 1, keep_weeks: [1] },
      });
    }
    expect(body).toMatchObject({
      message: revisionMessage,
      draft: initialDraft,
      reference_weeks: [1, 2, 3],
    });
    return answer(route, { status: "draft", draft: revisionDraft });
  });
  await page.route(`${API}/api/v1/advice-jobs/${JOB}`, (route) => {
    if (route.request().method() === "OPTIONS") return answer(route, null);
    polls += 1;
    return answer(route, { job_id: JOB, status: completed ? "completed" : "queued" });
  });
  await page.route(`${API}/api/v1/leagues/${LEAGUE}/entries/${ENTRY}/advice**`, (route) => {
    const request = route.request();
    if (request.method() === "OPTIONS") return answer(route, null);
    const url = new URL(request.url());
    const { window, preferences } =
      request.method() === "POST"
        ? (request.postDataJSON() as { window: number; preferences: DecisionPreferences })
        : {
            window: Number(url.searchParams.get("window")),
            preferences: JSON.parse(url.searchParams.get("preferences")!) as DecisionPreferences,
          };
    const secondWeek = preferences.week_rules?.find(({ week }) => week === 2)?.rules;
    const kind: Variant =
      window === 1
        ? "shorter"
        : secondWeek?.include_players?.includes(target.player_id)
          ? "with"
          : secondWeek?.avoid_players.includes(target.player_id)
            ? "without"
            : "original";
    if (request.method() === "POST") {
      posts.push({ kind, window, preferences });
      if (kind === "with" && !completed)
        return answer(route, { job_id: JOB, status: "queued" }, 202);
    } else {
      cacheReads.push(kind);
      if (kind === "with" && !completed)
        return answer(route, { error: { code: "NOT_COMPUTED" } }, 404);
    }
    const variant = variants[kind];
    const departures = replacements.slice(0, variant.arrivals.length);
    const laterLineup = {
      ...opening,
      starting_xi: opening.starting_xi.map((player) => {
        const index = departures.findIndex(({ player_id }) => player_id === player.player_id);
        return variant.arrivals[index] ?? player;
      }),
    };
    return answer(route, {
      ...envelope,
      payload: {
        ...envelope.payload,
        window,
        moves: [],
        bank_after_tenths: 18,
        free_transfers_after: 2,
        expected_own_points: 46,
        solver_status: "OPTIMAL",
        optimality_gap: 0,
        preferences,
        preferences_scope: "selected_weeks",
        plan_weeks: envelope.payload.plan_weeks!.slice(0, window).map((week, i) => ({
          ...week,
          gameweek: squad.gameweek + i,
          transfers_in: i === 1 ? variant.arrivals : [],
          transfers_out: i === 1 ? departures : [],
          chip: null,
          free_transfers_before: i === 0 ? 1 : i === 1 ? 2 : variant.free,
          free_transfers_after: i === 0 ? 2 : variant.free + i - 1,
          transfer_hit_points: i === 1 ? variant.hits : 0,
          expected_points: variant.points[i],
          bank_after_tenths: i === 0 ? 18 : variant.bank,
          lineup: i === 0 ? opening : laterLineup,
        })),
      },
    });
  });

  await page.clock.install();
  await page.goto(PAGE);

  await holdModel(page);
  const input = page.getByRole("textbox", { name: "Plan instructions" });
  const send = page.getByRole("button", { name: "Send", exact: true });
  const compute = page.getByRole("button", { name: "Compute plans" });
  const card = (name: string) =>
    page.getByRole("article").filter({ has: page.getByRole("heading", { name, exact: true }) });
  const ready = (name: string) => card(name).and(page.locator("article[data-plan-ready]"));
  const revision = page.getByRole("region", { name: "Plan revision" });

  await input.fill(initialMessage);
  await send.click();
  await expect(page.getByText("Instructions updated.", { exact: true })).toHaveCount(1);
  expect(posts).toHaveLength(0);
  await compute.click();
  await expect(ready("Base plan")).toBeVisible();
  expect(posts.map(({ kind }) => kind)).toEqual(["original"]);

  await input.fill(revisionMessage);
  await send.click();
  await expect(page.getByText("Instructions updated.", { exact: true })).toHaveCount(2);
  await expect(
    page
      .getByRole("listitem")
      .filter({ hasText: `Keep the previous plan for GW ${squad.gameweek}` }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("listitem")
      .filter({ hasText: `Keep at least £1.2m after GW ${squad.gameweek + 1}` }),
  ).toBeVisible();
  await expect(compute).toBeEnabled();
  expect(posts.map(({ kind }) => kind)).toEqual(["original"]);

  await startQueuedJob(page, JOB, compute, "en");
  await expect.poll(() => polls).toBeGreaterThan(0);
  const revisedPosts = posts.filter(({ kind }) => kind !== "original");
  expect(revisedPosts.map(({ kind }) => kind).sort()).toEqual(["with", "without"]);
  for (const { window, preferences } of revisedPosts) {
    expect(window).toBe(3);
    expect(preferences).toMatchObject({
      keep_players: [keeper.player_id],
      min_bank: { tenths: 12, week: 2 },
      frozen_weeks: [
        {
          week: 1,
          transfers_in: [],
          transfers_out: [],
          chip: null,
          captain: opening.captain.player_id,
        },
      ],
    });
    const ids = preferences.frozen_weeks![0]!.starting_xi!;
    expect([...ids].sort((a, b) => a - b)).toEqual(
      opening.starting_xi.map(({ player_id }) => player_id).sort((a, b) => a - b),
    );
  }

  const beforeReload = polls;
  await reloadQueuedJob(page, JOB);
  await expect.poll(() => polls).toBeGreaterThan(beforeReload);
  expect(posts).toHaveLength(3);
  completed = true;
  await observeCompletedJob(page, JOB);
  await expect(ready("With player")).toBeVisible({ timeout: 15_000 });

  const assertComparisons = async () => {
    const without = card("Without player");
    const withPlayer = card("With player");
    await expect(without.getByText("Budget Signing", { exact: true })).toBeVisible();
    await expect(withPlayer.getByText(/Bukayo Saka/).first()).toBeVisible();
    await expect(
      without.getByText("Total expected net points", { exact: true }).locator("xpath=../dd"),
    ).toContainText("140.0");
    await expect(
      withPlayer.getByText("Total expected net points", { exact: true }).locator("xpath=../dd"),
    ).toContainText("141.0");
    await expect(
      withPlayer.getByText("Difference from first plan", { exact: true }).locator("xpath=../dd"),
    ).toContainText("+1.0");
    await expect(
      withPlayer.getByText("Total transfer penalty", { exact: true }).locator("xpath=../dd"),
    ).toContainText("4");
    await expect(revision.getByRole("columnheader", { name: "Previous plan" })).toBeVisible();
    await expect(revision.getByRole("columnheader", { name: "Revised plan" })).toBeVisible();
    const net = revision.getByRole("row").filter({ hasText: "Total expected net points" });
    await expect(net).toContainText("137.0");
    await expect(net).toContainText("140.0");
    await expect(net).toContainText("+3.0");
    const budget = revision.getByRole("row").filter({ hasText: "Budget after final week" });
    await expect(budget).toContainText("£0.6m");
    await expect(budget).toContainText("£2.0m");
    await expect(revision.getByText("Original Signing", { exact: true })).toBeVisible();
    await expect(revision.getByText("Budget Signing", { exact: true })).toBeVisible();
  };
  await assertComparisons();

  cacheReads.length = 0;
  await page.reload();
  await assertComparisons();
  expect(cacheReads).toEqual(expect.arrayContaining(["with", "without"]));
  expect(posts).toHaveLength(3);

  // The reload dropped the key with the tab's memory; the chat needs it again.
  await holdModel(page);
  await card("With player").getByRole("button", { name: "Revise this plan" }).click();
  await expect(input).toBeFocused();
  await input.fill(shorterMessage);
  await send.click();
  await expect(page.getByLabel("Plan window")).toHaveValue("1");
  expect(posts).toHaveLength(3);
  await compute.click();
  await expect(ready("Base plan")).toBeVisible();
  const differentHorizons = revision
    .getByRole("row")
    .filter({ hasText: "Total expected net points" });
  const cells = differentHorizons.getByRole("cell");
  await expect(cells.nth(0)).toHaveText("141.0");
  await expect(cells.nth(1)).toHaveText("46.0");
  await expect(cells.nth(2)).toHaveText("—");
  expect(posts).toHaveLength(4);
  expect(posts.at(-1)?.kind).toBe("shorter");
});
