import { expect, test, type Route } from "@playwright/test";

import {
  preferenceScope,
  type DecisionPreferences,
} from "../src/features/league/advice/decisionPreferences";
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
const JOB = "llmopt-scenario-job";
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

for (const [kind, vNext] of [
  ["price_increase", false],
  ["price_increase", true],
  ["unavailable", false],
  ["unavailable", true],
] as const) {
  const isPrice = kind === "price_increase";
  test(
    isPrice
      ? `a £0.1m price increase makes the original move infeasible and shows a viable reoptimization (release control ${vNext})`
      : `an unavailable captain is replaced in both scenario plans and a reload resumes the comparison (release control ${vNext})`,
    async ({ page }) => {
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
      const departure = opening.starting_xi.find(
        ({ position, player_id }) =>
          position === "MID" &&
          player_id !== opening.captain.player_id &&
          player_id !== opening.vice_captain.player_id,
      )!;
      const signing = {
        ...departure,
        player_id: 9081320,
        name: "Bukayo Saka",
        short_name: "Saka",
        team: "Arsenal",
      };
      const budgetSigning = {
        ...departure,
        player_id: 9081321,
        name: "Budget Signing",
        short_name: "Budget",
        team: "Brighton",
      };
      const reserve = opening.bench.find(({ position }) => position === opening.captain.position)!;
      const noCaptain = {
        starting_xi: opening.starting_xi.map((player) =>
          player === opening.captain ? reserve : player,
        ),
        bench: opening.bench.map((player) => (player === reserve ? opening.captain : player)),
        captain: opening.vice_captain,
        vice_captain: opening.starting_xi.find(
          (player) =>
            player !== opening.captain &&
            player !== opening.vice_captain &&
            player.position !== "GK",
        )!,
      };
      const initialMessage = "Üç haftalık plan yap. İlk hafta transferi sakla ve kalecimi tut.";
      const scenarioMessage = isPrice
        ? "Saka ikinci hafta 0,1 milyon pahalanırsa önceki transferleri ve yeni planı karşılaştır."
        : `${opening.captain.name} bu hafta oynayamazsa önceki transferleri ve yeni planı karşılaştır.`;
      const initialDraft = {
        window: 3,
        hard: [
          { kind: "hold_transfers", week: 1 },
          { kind: "keep_player", player_id: keeper.player_id },
        ],
        soft: [],
      };
      const scenario = isPrice
        ? { kind, player_id: signing.player_id, tenths: 1, week: 2 }
        : { kind, player_id: opening.captain.player_id, week: 1 };
      type Branch = "baseline" | "original" | "reoptimized";
      const posts: { branch: Branch; window: number; preferences: DecisionPreferences }[] = [];
      const reads: Branch[] = [];
      let polls = 0;
      let completed = false;

      await page.route(`${API}/api/v1/contributions/players`, (route) =>
        answer(route, {
          season: squad.season,
          players: [keeper, opening.captain, signing].map(({ player_id, name, team }) => ({
            id: player_id,
            name,
            team,
          })),
        }),
      );
      await page.route(`${API}/api/v1/leagues/${LEAGUE}/capabilities`, (route) =>
        answer(route, {
          contract_version: "league_capabilities_v1",
          ...(vNext ? { llmopt_vnext: true, llmopt_vnext_three_week: true } : {}),
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
        if (body.message === initialMessage)
          return answer(route, { status: "draft", draft: initialDraft });
        expect(body).toMatchObject({
          message: scenarioMessage,
          draft: initialDraft,
          reference_weeks: [1, 2, 3],
        });
        return answer(route, { status: "draft", draft: { ...initialDraft, scenario } });
      });
      await page.route(`${API}/api/v1/advice-jobs/${JOB}`, (route) => {
        if (route.request().method() === "OPTIONS") return answer(route, null);
        polls += 1;
        return answer(route, {
          job_id: JOB,
          status: isPrice ? "failed" : completed ? "completed" : "queued",
          ...(isPrice ? { error_code: "PLAN_NOT_FOUND", infeasibility: { repairs: [] } } : {}),
        });
      });
      await page.route(`${API}/api/v1/leagues/${LEAGUE}/entries/${ENTRY}/advice**`, (route) => {
        const request = route.request();
        if (request.method() === "OPTIONS") return answer(route, null);
        const search = new URL(request.url()).searchParams;
        const { window, preferences } =
          request.method() === "POST"
            ? (request.postDataJSON() as { window: number; preferences: DecisionPreferences })
            : {
                window: Number(search.get("window")),
                preferences: JSON.parse(search.get("preferences")!) as DecisionPreferences,
              };
        const branch: Branch = !preferences.scenario
          ? "baseline"
          : preferences.frozen_weeks?.length
            ? "original"
            : "reoptimized";
        if (request.method() === "POST") {
          const run = request.postDataJSON().run;
          if (vNext) {
            expect(run?.run_id).toMatch(/^[a-f0-9]{32}$/);
            expect(run.stage).toBe(branch === "original" ? "followup" : "base");
          } else expect(run).toBeUndefined();
          posts.push({ branch, window, preferences });
          if (
            (isPrice && branch === "original") ||
            (!isPrice && branch === "reoptimized" && !completed)
          )
            return answer(route, { job_id: JOB, status: "queued" }, 202);
        } else {
          reads.push(branch);
          if (
            (isPrice && branch === "original") ||
            (!isPrice && branch === "reoptimized" && !completed)
          )
            return answer(route, { error: { code: "NOT_COMPUTED" } }, 404);
        }
        const changed = branch !== "baseline";
        const arrival = isPrice && changed ? budgetSigning : signing;
        const first = changed && !isPrice ? noCaptain : opening;
        const later = {
          ...opening,
          starting_xi: opening.starting_xi.map((player) =>
            player === departure ? arrival : player,
          ),
        };
        return answer(route, {
          ...envelope,
          payload: {
            ...envelope.payload,
            ...first,
            source_snapshot_id: squad.source_snapshot_id,
            moves: [],
            expected_own_points: changed && !isPrice ? 43 : 46,
            transfer_hit_points: 0,
            bank_after_tenths: 0,
            free_transfers_after: 2,
            preferences,
            preferences_scope: preferenceScope(preferences),
            solver_status: "OPTIMAL",
            optimality_gap: 0,
            plan_weeks: envelope.payload.plan_weeks!.map((week, index) => ({
              ...week,
              gameweek: squad.gameweek + index,
              transfers_in: index === 1 ? [arrival] : [],
              transfers_out: index === 1 ? [departure] : [],
              chip: null,
              free_transfers_before: index === 0 ? 1 : 2,
              free_transfers_after: index < 2 ? 2 : 3,
              expected_points:
                index === 0 ? (changed && !isPrice ? 43 : 46) : index === 1 ? 45 : 46,
              transfer_hit_points: 0,
              bank_after_tenths: index > 0 && changed && isPrice ? 1 : 0,
              lineup: index === 0 ? first : later,
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
      await input.fill(initialMessage);
      await send.click();
      await expect(page.getByText("Instructions updated.", { exact: true })).toHaveCount(1);
      await compute.click();
      const baseline = page.locator("article[data-plan-ready]");
      await expect(baseline.getByText(signing.name, { exact: true })).toBeVisible();
      expect(posts.map(({ branch }) => branch)).toEqual(["baseline"]);

      await input.fill(scenarioMessage);
      await send.click();
      await expect(page.getByText("Instructions updated.", { exact: true })).toHaveCount(2);
      const assumption = isPrice
        ? `${signing.name} costs £0.1m more from GW ${squad.gameweek + 1} onward`
        : `${opening.captain.name} is unavailable in GW ${squad.gameweek}`;
      await expect(page.getByRole("listitem").filter({ hasText: assumption })).toBeVisible();
      await expect(compute).toBeEnabled();
      expect(posts).toHaveLength(1);
      await startQueuedJob(page, JOB, compute, "en", isPrice ? "failed" : "queued");
      await expect.poll(() => polls).toBeGreaterThan(0);

      if (!isPrice) {
        if (vNext) {
          expect(posts.map(({ branch }) => branch)).toEqual(["baseline", "reoptimized"]);
        } else {
          await expect
            .poll(() =>
              posts
                .slice(1)
                .map(({ branch }) => branch)
                .sort(),
            )
            .toEqual(["original", "reoptimized"]);
        }
        const beforeReload = polls;
        await reloadQueuedJob(page, JOB);
        await expect.poll(() => polls).toBeGreaterThan(beforeReload);
        expect(posts).toHaveLength(vNext ? 2 : 3);
        completed = true;
        await observeCompletedJob(page, JOB);
        await expect.poll(() => posts.length).toBe(3);
      }

      const scenarioPosts = posts.slice(1);
      expect(scenarioPosts.map(({ branch }) => branch).sort()).toEqual(["original", "reoptimized"]);
      const expectedScenario = isPrice ? scenario : { kind, player_id: opening.captain.player_id };
      for (const { window, preferences } of scenarioPosts) {
        expect(window).toBe(3);
        expect(preferences.keep_players).toEqual([keeper.player_id]);
        expect(preferences.scenario).toEqual(expectedScenario);
        expect(preferences.week_rules).toEqual(
          expect.arrayContaining([
            expect.objectContaining({
              week: 1,
              rules: expect.objectContaining({ hold_transfers: true }),
            }),
          ]),
        );
      }
      expect(
        scenarioPosts.find(({ branch }) => branch === "original")!.preferences.frozen_weeks,
      ).toEqual([
        { week: 1, transfers_in: [], transfers_out: [], chip: null },
        {
          week: 2,
          transfers_in: [signing.player_id],
          transfers_out: [departure.player_id],
          chip: null,
        },
        { week: 3, transfers_in: [], transfers_out: [], chip: null },
      ]);
      expect(
        scenarioPosts.find(({ branch }) => branch === "reoptimized")!.preferences.frozen_weeks,
      ).toBeUndefined();

      const comparison = page.getByRole("region", { name: "Scenario comparison" });
      const rows = comparison.getByRole("table");
      await expect(
        rows.getByRole("rowheader", { name: "Total transfer penalty", exact: true }),
      ).toHaveCount(vNext ? 1 : 0);
      for (const name of [
        "Expected net points",
        "Transfer penalty",
        "Remaining budget",
        "Free transfers next week",
      ]) {
        await expect(rows.getByRole("rowheader", { name, exact: true })).toHaveCount(vNext ? 3 : 0);
      }
      await expect(
        comparison.getByRole("columnheader", { name: "Original transfers" }),
      ).toBeVisible();
      await expect(
        comparison.getByRole("columnheader", { name: "Reoptimized plan" }),
      ).toBeVisible();
      if (isPrice) {
        await expect(comparison).toContainText(
          "The original transfers are infeasible in this scenario.",
        );
        const table = comparison.getByRole("table");
        const move = table.getByRole("row").filter({ hasText: signing.name });
        await expect(move.getByRole("cell").nth(0)).toHaveText(signing.name);
        await expect(move.getByRole("cell").nth(1)).toHaveText(budgetSigning.name);
        const net = table
          .getByRole("row")
          .filter({ hasText: "Total expected net points" })
          .getByRole("cell");
        await expect(net.nth(0)).toHaveText("—");
        await expect(net.nth(1)).toHaveText("137.0");
        await expect(net.nth(2)).toHaveText("—");
        await expect(comparison.locator("article[data-plan-ready]")).toHaveCount(1);
        reads.length = 0;
        await page.reload();
        await expect(comparison).toContainText(
          "The original transfers are infeasible in this scenario.",
        );
        await expect(net.nth(1)).toHaveText("137.0");
        expect(reads).toContain("reoptimized");
        expect(reads).not.toContain("original");
        expect(posts).toHaveLength(3);
        return;
      }

      await expect(comparison).toContainText(
        "The original transfers are feasible in this scenario.",
      );
      await expect.poll(() => reads.includes("reoptimized")).toBe(true);
      await expect(comparison.locator("article[data-plan-ready]")).toHaveCount(2);
      await expect(
        comparison
          .locator(`[data-player-motion="${opening.vice_captain.player_id}"]`)
          .getByRole("img", { name: "captain", exact: true }),
      ).toHaveCount(2);
      await expect(
        comparison
          .locator(`[data-player-motion="${opening.captain.player_id}"]`)
          .getByRole("img", { name: "captain", exact: true }),
      ).toHaveCount(0);
      expect(posts).toHaveLength(3);
    },
  );
}
