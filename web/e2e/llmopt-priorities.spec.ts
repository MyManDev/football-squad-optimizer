import { expect, test, type Route } from "@playwright/test";
import {
  checkedPreferences,
  preferenceScope,
  preferencesKey,
  type DecisionPreferences,
} from "../src/features/league/advice/decisionPreferences";
import {
  bundleKey,
  expandSelection,
  type PreferenceBundle,
  type PreferenceBundleResult,
  type PreferenceSelection,
} from "../src/features/league/advice/preferenceBundle";
import { LLMOPT_COPY } from "../src/features/league/llmopt/copy";
import type { EntryAdvice, LeagueViewEnvelope } from "../src/features/league/types";
import {
  mockEntryAdviceEnvelope,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../src/fixtures/league";
import { EXAMPLE_CLAIM } from "./identity";
import { installLeagueMocks, openCalendar } from "./leagueMocks";
import { holdModel, routeChat } from "./llmoptChat";
import { observeCompletedJob, reloadQueuedJob, startQueuedJob } from "./queuedAdviceJob";

const API = process.env.VITE_ADVICE_API_ORIGIN?.replace(/\/$/, "");
const LEAGUE = mockLeagueMembersEnvelope.payload.league_id;
const ENTRY = EXAMPLE_CLAIM.entryId;
const PAGE = `/league/${LEAGUE}/members/${ENTRY}/llmopt`;
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

for (const language of ["tr", "en"] as const)
  for (const window of [1, 3] as const)
    for (const mode of window === 3
      ? ["legacy prices", "priority total", "partial priority total", "failed priority total"]
      : ["legacy prices", "priority total"]) {
      const total = mode !== "legacy prices";
      const partial = mode === "partial priority total";
      const failed = mode === "failed priority total";
      test(`${language} ${window}-week ${mode} uses one preference request across pending reload`, async ({
        page,
      }) => {
        test.skip(!API, "API build required");
        await installLeagueMocks(page);
        await page.setViewportSize({ width: language === "tr" ? 375 : 1280, height: 900 });
        await page.addInitScript(
          (language) => localStorage.setItem("squadopt.language", language),
          language,
        );
        const copy = LLMOPT_COPY[language];
        const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
        const held = [...squad.starting_xi, ...squad.bench];
        const calendar = openCalendar();
        calendar.payload.gameweeks = [0, 1, 2].map((offset) => ({
          gameweek: squad.gameweek + offset,
          deadline_utc: "2999-01-01T00:00:00Z",
          fixtures: [],
        }));
        await page.route("**/data/fixtures.json", (route) => answer(route, calendar));
        await page.route(`${API}/api/v1/contributions/players`, (route) =>
          answer(route, {
            season: squad.season,
            players: held.map((row) => ({ id: row.player_id, name: row.name, team: row.team })),
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
            top100: { available: false, weights: [0] },
            managers_word: { available: false },
            preferences: { available: true },
            llmopt_vnext: true,
            ...(window === 3 ? { llmopt_vnext_three_week: true } : {}),
            preference_bundles: { version: "llmopt_preference_bundle_v1" },
          }),
        );
        const soft = [
          { kind: "keep_player", player_id: held[0]!.player_id, ...(total ? { priority: 1 } : {}) },
          {
            kind: "avoid_player",
            player_id: held[1]!.player_id,
            ...(total ? { priority: 2 } : {}),
          },
          { kind: "keep_player", player_id: held[2]!.player_id, ...(total ? { priority: 3 } : {}) },
        ];
        await routeChat(page, API, (route) =>
          answer(route, {
            status: "draft",
            draft: { hard: [], soft, window, ...(total ? { max_total_cost_tenths: 15 } : {}) },
          }),
        );
        type Body = {
          window: 1 | 3;
          preferences: DecisionPreferences;
          run: { run_id: string; stage: string };
          preference_bundle?: PreferenceBundle;
        };
        const posts: Body[] = [];
        const cache = new Map<string, LeagueViewEnvelope<EntryAdvice>>();
        let released = false;
        let polls = 0;
        const key = (preferences: DecisionPreferences, bundle?: PreferenceBundle) =>
          `${preferencesKey(checkedPreferences(preferences))}:${bundle ? bundleKey(bundle) : ""}`;
        function computed(
          preferences: DecisionPreferences,
          loss = 0,
          chip: PreferenceSelection["chip"] = null,
        ) {
          const result = structuredClone(mockEntryAdviceEnvelope(ENTRY, "saf-puan", window));
          result.payload.preferences = checkedPreferences(preferences);
          result.payload.preferences_scope = preferenceScope(preferences);
          result.payload.expected_own_points = 50 - loss;
          result.payload.lineup_expectation = undefined;
          result.payload.transfer_hit_points = 0;
          result.payload.bank_after_tenths = 6;
          result.payload.free_transfers_after = 1;
          result.payload.chip = chip;
          if (result.payload.plan_weeks)
            result.payload.plan_weeks = result.payload.plan_weeks.map((row, index) => ({
              ...row,
              expected_points: 50 - (index === 0 ? loss : 0),
              transfer_hit_points: 0,
            }));
          return result;
        }
        await page.route(`${API}/api/v1/advice-jobs/preference-bundle`, (route) => {
          if (route.request().method() === "OPTIONS") return answer(route, null);
          polls += 1;
          return answer(route, {
            job_id: "preference-bundle",
            status: released ? "completed" : "queued",
          });
        });
        await page.route(`${API}/api/v1/leagues/${LEAGUE}/entries/${ENTRY}/advice**`, (route) => {
          const request = route.request();
          if (request.method() === "OPTIONS") return answer(route, null);
          const url = new URL(request.url());
          if (request.method() === "GET") {
            const preferences = JSON.parse(url.searchParams.get("preferences") ?? "{}");
            const bundle = url.searchParams.has("preference_bundle")
              ? JSON.parse(url.searchParams.get("preference_bundle")!)
              : undefined;
            const result = cache.get(key(preferences, bundle));
            return result
              ? answer(route, result)
              : answer(route, { error: { code: "NOT_COMPUTED" } }, 404);
          }
          const body = request.postDataJSON() as Body;
          posts.push(body);
          const parent = computed(body.preferences);
          const bundle = body.preference_bundle;
          if (!bundle) {
            cache.set(key(body.preferences), parent);
            return answer(route, parent);
          }
          const accepted = bundle.prices.reduce(
            (mask, price, index) =>
              typeof price.outcome === "number" || price.outcome === "same"
                ? mask | (1 << index)
                : mask,
            0,
          );
          const choice = bundle.choices.find((row) => row.accepted === accepted);
          const selected = bundle.program ? { preferences: {}, chip: null } : choice?.selection;
          expect(selected).toBeTruthy();
          const preferred = computed(
            expandSelection(body.preferences, selected!),
            1,
            selected!.chip,
          ).payload;
          if (bundle.program) {
            const identities = bundle.program.preferences.map((row) => JSON.stringify(row.rules));
            preferred.priority_preferences = {
              contract_version: "llmopt_priority_result_v1",
              satisfied: partial ? identities.slice(0, 1) : identities,
              left_out: partial ? identities.slice(1, 2) : [],
              unsearched: partial ? identities.slice(2) : [],
              completed_priorities: partial ? [1, 2] : [1, 2, 3],
              total_cost: 1,
              reference_proved: false,
              budget_exhausted: partial,
            };
          }
          const result: PreferenceBundleResult = {
            contract_version: "llmopt_preference_result_v1",
            request: bundle,
            components: bundle.slots.map((slot) => ({
              status: "done",
              payload: computed(expandSelection(body.preferences, slot!), 0.5, slot!.chip).payload,
              error_code: null,
            })),
            selected: failed
              ? { status: "failed", payload: null, error_code: "ADVICE_FAILED" }
              : { status: "done", payload: preferred, error_code: null },
            applied: bundle.program ? [] : choice!.applied,
            accepted,
            budget_exhausted: partial,
          };
          parent.payload.preference_bundle_result = result;
          cache.set(key(body.preferences, bundle), parent);
          return answer(route, { job_id: "preference-bundle", status: "queued" }, 202);
        });
        await page.clock.install();
        await page.goto(PAGE);
        await holdModel(page);
        await page
          .getByRole("textbox", { name: copy.chat })
          .fill(
            total
              ? "Keep the first player with high priority, avoid the second, and keep the third; total allowance 1.5 points."
              : "Prefer keeping the first and third players and avoiding the second.",
          );
        await page.getByRole("button", { name: copy.send, exact: true }).click();
        await expect(page.getByText(copy.understood, { exact: true })).toBeVisible();
        expect(posts).toHaveLength(0);
        if (total)
          await expect(page.getByRole("spinbutton", { name: copy.totalLimit })).toHaveValue("1.5");
        if (window === 1 && total) {
          const selector = page.getByRole("combobox", { name: copy.window, exact: true });
          await selector.selectOption("3");
          await expect(page.getByText(copy.individualLimitsOnly)).toBeVisible();
          await expect(
            page.getByRole("button", { name: copy.clearPrioritySettings }),
          ).toBeEnabled();
          await expect(page.getByRole("button", { name: copy.compute })).toBeDisabled();
          await selector.selectOption("1");
          await expect(page.getByRole("spinbutton", { name: copy.totalLimit })).toHaveValue("1.5");
          expect(posts).toHaveLength(0);
        }
        const job = "preference-bundle";
        await startQueuedJob(
          page,
          job,
          page.getByRole("button", { name: copy.compute, exact: true }),
          language,
        );
        await expect.poll(() => posts.length).toBe(2);
        expect(posts[0]!.run.stage).toBe("base");
        expect(posts[1]!.run).toEqual({ ...posts[0]!.run, stage: "followup" });
        expect(posts[1]!.preference_bundle?.prices).toHaveLength(total ? 0 : 3);
        expect(posts[1]!.preference_bundle?.program?.max_total_cost_tenths).toBe(
          total ? 15 : undefined,
        );
        await expect.poll(() => polls).toBeGreaterThan(0);
        const before = polls;
        await reloadQueuedJob(page, job, language);
        await expect.poll(() => polls).toBeGreaterThan(before);
        expect(posts).toHaveLength(2);
        released = true;
        await observeCompletedJob(page, job);
        await expect(
          page.getByRole("heading", { name: copy.combinedPlan, exact: true }),
        ).toBeVisible();
        await expect(page.locator('[data-combined="applied"]')).toHaveCount(
          failed ? 0 : partial ? 1 : 3,
        );
        if (failed) {
          await expect(page.getByText(copy.combinedFailed, { exact: true })).toBeVisible();
          const summary = page.getByRole("region", { name: copy.requestedPreferences });
          for (const player of held.slice(0, 3)) await expect(summary).toContainText(player.name);
          await expect(page.locator("article[data-plan-ready]")).toHaveCount(1);
        }
        if (partial) {
          await expect(page.locator('[data-combined="left-out"]')).toContainText(
            copy.combinedLeftOut,
          );
          await expect(page.locator('[data-combined="left-out"]')).toContainText(held[1]!.name);
          await expect(page.locator('[data-combined="unsearched"]')).toContainText(
            copy.combinedUnsearched,
          );
          await expect(page.locator('[data-combined="unsearched"]')).toContainText(held[2]!.name);
        }
        await page.reload();
        await expect(
          page.getByRole("heading", { name: copy.combinedPlan, exact: true }),
        ).toBeVisible();
        expect(posts).toHaveLength(2);
        const size = await page.evaluate(() => ({
          scroll: document.documentElement.scrollWidth,
          width: globalThis.innerWidth,
        }));
        expect(size.scroll).toBeLessThanOrEqual(size.width);
        if (failed) {
          await expect(page.getByText(copy.combinedFailed, { exact: true })).toBeVisible();
          await page
            .getByRole("button", {
              name: `${copy.remove} · ${copy.rules.avoid_player} · ${held[1]!.name}`,
              exact: true,
            })
            .click();
          await page.getByRole("button", { name: copy.compute, exact: true }).click();
          await expect.poll(() => posts.length).toBe(4);
          expect(posts[2]!.run.run_id).not.toBe(posts[0]!.run.run_id);
          expect(posts[3]!.preference_bundle?.program?.preferences).toHaveLength(2);
        }
      });
    }
