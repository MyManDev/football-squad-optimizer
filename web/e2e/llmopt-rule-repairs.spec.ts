import { expect, test, type Page } from "@playwright/test";
import { mockEntryAdviceEnvelope } from "../src/fixtures/league";
import {
  checkedPreferences,
  preferenceScope,
  type DecisionPreferences,
} from "../src/features/league/advice/decisionPreferences";
import { LLMOPT_COPY } from "../src/features/league/llmopt/copy";
import type { PlanDraft } from "../src/features/league/llmopt/intent";
import { points } from "../src/lib/format";
import { holdModel, routeChat } from "./llmoptChat";
import { startQueuedJob } from "./queuedAdviceJob";
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

type Family = "club" | "bank" | "hit" | "frozen" | "chip";

const statusText = {
  en: {
    missing: "Try calculating again when the missing plan data is available.",
    budget: "This run has used its allowance, so review the rules and start a new calculation.",
  },
  tr: {
    missing: "Eksik plan verileri hazır olduğunda yeniden hesapla.",
    budget:
      "Bu çalışmanın hesaplama hakkı doldu, kuralları gözden geçirip yeni bir hesaplama başlat.",
  },
};
async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
}

for (const language of ["en", "tr"] as const) {
  for (const family of ["club", "bank", "hit", "frozen", "chip"] as Family[]) {
    test(`verified ${family} repair recalculates its actual device plan in ${language} on a phone`, async ({
      page,
    }) => {
      test.skip(!API, "API-origin build required for rule interpretation");
      const { squad, block, held, players } = await installMember(page, language);
      const copy = LLMOPT_COPY[language];
      const keep = { kind: "keep_player" as const, player_id: block.held[0]! };
      const hold = { kind: "hold_transfers" as const };
      const buy = (id: number) => ({
        kind: "buy_player" as const,
        player_id: id,
        week: 1 as const,
      });
      // Both targets exist in the shipped solver table and fit together with one paid move.
      const targets = [127, 109];
      const drafts: Record<Family, PlanDraft> = {
        club: { hard: [keep, hold, { kind: "club_count", club: "Club 1", count: 3 }], soft: [] },
        bank: { hard: [keep, hold], soft: [], min_bank: { tenths: 30 } },
        hit: { hard: [keep, { kind: "no_hits" }, ...targets.map(buy)], soft: [] },
        frozen: { hard: [keep, buy(targets[0]!)], soft: [], keep_weeks: [1] },
        chip: { hard: [keep, { kind: "wildcard" }], soft: [] },
      };
      const edits: Record<Family, RegExp> = {
        club: /Club 1.*3.*Club 1.*2/,
        bank: /budget.*2\.6|bütçe.*2,6/i,
        hit: /Remove.*No transfer hits|Puan cezası alma.*kaldır/i,
        frozen: new RegExp(
          language === "tr"
            ? `GW ${squad.gameweek} kilidini kaldır`
            : `Unlock GW ${squad.gameweek}`,
        ),
        chip: /Remove.*Wildcard|Wildcard.*kaldır/i,
      };
      const conflicts: Record<Family, RegExp> = {
        club: /Club 1.*3.*(conflict|uyuşmuyor)/,
        bank: /3\.0m.*bank|kasada 3,0m/,
        hit: /incur a hit your rules do not allow|puan cezası getiriyor ve kuralların buna izin vermiyor/,
        frozen: /locked decision for GW|GW \d+ için kilitlenen karar/,
        chip: /Wildcard.*GW|GW.*Wildcard/,
      };
      await routeChat(page, API, (route) =>
        answer(route, {
          status: "draft",
          draft: {
            window: 1,
            ...(route.request().postDataJSON().message === "First hold"
              ? { hard: [keep, hold], soft: [] }
              : drafts[family]),
          },
        }),
      );
      let posts = 0,
        workers = 0;
      page.on("worker", () => workers++);
      await page.route(ADVICE, (route) => {
        if (route.request().method() === "POST") posts++;
        return answer(route, { error: { code: "NOT_COMPUTED" } }, 404);
      });
      await page.goto(PAGE);
      await holdModel(page);
      if (family === "frozen") {
        await instructions(page, language, "First hold");
        await page.getByRole("button", { name: copy.compute }).click();
        const base = page.locator("article[data-plan-ready]").first();
        await expect(base).toBeVisible();
        await base.getByRole("button", { name: copy.revisePlan }).click();
      }
      await instructions(page, language, "Check this set of rules");
      const region = page.locator("[data-rule-repairs]");
      await expect(region.getByRole("status")).toHaveText(conflicts[family]);
      const options = region.locator("[data-repair-plan]");
      await expect(options).toHaveCount(0);
      await checkButton(page, language).click();
      // This input has one conflicting hard rule in the relevant family.
      await expect(options).toHaveCount(1);
      const option = options.first();
      await expect(option.getByRole("button")).toHaveText(edits[family]);
      const id = await option.getAttribute("data-repair-plan");
      expect(id).toMatch(/^[0-9a-f]{64}$/);
      const net = Number(await option.getAttribute("data-repair-net"));
      expect(Number.isFinite(net)).toBe(true);
      await noOverflow(page);
      const before = workers;
      await option.getByRole("button").click();
      const selected = page.locator(`article[data-plan-id="${id}"]`);
      await expect(selected).toBeVisible();
      await expect(selected.getByText(copy.net, { exact: true }).locator("xpath=../dd")).toHaveText(
        points(net, 1, language === "tr" ? "tr-TR" : "en-GB"),
      );
      expect(workers).toBeGreaterThan(before);
      const [chip, ids] = JSON.parse((await selected.getAttribute("data-transfer-decision"))!) as [
        string | null,
        number[],
      ];
      expect(ids).toContain(keep.player_id);
      if (family === "club")
        expect(ids.filter((id) => players.get(id)?.team === "Club 1")).toHaveLength(2);
      if (family === "bank" || family === "club")
        expect([...ids].sort((a, b) => a - b)).toEqual(held.map((p) => p.id).sort((a, b) => a - b));
      if (family === "hit") for (const target of targets) expect(ids).toContain(target);
      if (family === "frozen") expect(ids).toContain(targets[0]);
      if (family === "chip") expect(chip).toBeNull();
      expect(posts).toBe(0);
      await noOverflow(page);
    });
  }
  test(`missing chip history has its own sentence and no repair in ${language} on a phone`, async ({
    page,
  }) => {
    test.skip(!API, "API-origin build required");
    await installMember(page, language, false);
    await routeChat(page, API, (route) =>
      answer(route, {
        status: "draft",
        draft: { hard: [{ kind: "wildcard" }], soft: [], window: 1 },
      }),
    );
    let posts = 0;
    await page.route(ADVICE, (route) => {
      if (route.request().method() === "POST") posts++;
      return answer(route, { error: { code: "NOT_COMPUTED" } }, 404);
    });
    await page.goto(PAGE);
    await holdModel(page);
    await instructions(page, language, "Wildcard");
    await expect(page.locator("[data-rule-repairs]").getByRole("status")).toHaveText(
      statusText[language].missing,
    );
    await expect(checkButton(page, language)).toHaveCount(0);
    await expect(page.locator("[data-repair-plan]")).toHaveCount(0);
    expect(posts).toBe(0);
    await noOverflow(page);
  });
}

for (const language of ["tr", "en"] as const) {
  test(`a saved server diagnosis survives rollback and reload in ${language}`, async ({ page }) => {
    test.skip(!API, "API-origin build required");
    const { release, block } = await installMember(page, language);
    const jobId = "llmopt-bank-diagnosis";
    const required = { tenths: 40, week: 2 };
    await routeChat(page, API, (route) =>
      answer(route, {
        status: "draft",
        draft: {
          window: 3,
          hard: [{ kind: "keep_player", player_id: block.held[0] }],
          soft: [],
          min_bank: required,
        },
      }),
    );
    let posts = 0;
    let polls = 0;
    await page.route(ADVICE, (route) => {
      if (route.request().method() !== "POST")
        return answer(route, { error: { code: "NOT_COMPUTED" } }, 404);
      posts++;
      if (posts === 1) return answer(route, { job_id: jobId, status: "queued" }, 202);
      expect(route.request().postDataJSON().preferences.min_bank).toEqual({ tenths: 26, week: 2 });
      return answer(route, { error: { code: "RUN_BUDGET_EXHAUSTED" } }, 409);
    });
    await page.route(`${API}/api/v1/advice-jobs/${jobId}`, (route) => {
      if (route.request().method() === "GET") polls++;
      return answer(route, {
        job_id: jobId,
        status: "failed",
        error_code: "PLAN_NOT_FOUND",
        infeasibility: {
          repairs: [],
          bank: { required: 40, reachable: 26, week: 2, exact: true },
        },
      });
    });
    await page.clock.install();
    await page.goto(PAGE);
    await holdModel(page);
    await instructions(page, language, "Require a bank floor after the second week");
    await startQueuedJob(
      page,
      jobId,
      page.getByRole("button", { name: LLMOPT_COPY[language].compute, exact: true }),
      language,
      "failed",
    );
    const region = page.locator("[data-rule-repairs]");
    const diagnosis = await region.getByRole("status").innerText();
    expect(diagnosis).toMatch(language === "en" ? /4\.0m in the bank/ : /kasada 4,0m/);
    await checkButton(page, language).click();
    await expect(region.getByRole("status")).toHaveText(statusText[language].budget);
    release.master = false;
    await page.reload();
    await expect(page.locator("[data-saved-conflict]")).toHaveText(diagnosis);
    await expect(region).toHaveCount(0);
    await expect(checkButton(page, language)).toHaveCount(0);
    expect({ posts, polls }).toEqual({ posts: 2, polls: 1 });
    await noOverflow(page);
  });

  for (const removeCount of [2, 3]) {
    test(`choosing the change to the ${removeCount}-player rule preserves the other club count in ${language}`, async ({
      page,
    }) => {
      test.skip(!API, "API-origin build required");
      const { players } = await installMember(page, language);
      const counts = [2, 3].map((count) => ({ kind: "club_count", club: "Club 1", count }));
      await routeChat(page, API, (route) =>
        answer(route, { status: "draft", draft: { window: 1, hard: counts, soft: [] } }),
      );
      let posts = 0;
      await page.route(ADVICE, (route) => {
        if (route.request().method() === "POST") posts++;
        return answer(route, { error: { code: "NOT_COMPUTED" } }, 404);
      });
      await page.goto(PAGE);
      await holdModel(page);
      await instructions(page, language, "Require both club counts");
      const options = page.locator("[data-repair-plan]");
      await expect(options).toHaveCount(0);
      await checkButton(page, language).click();
      await expect(options).toHaveCount(2);
      const option = options.filter({
        has: page.getByRole("button", { name: new RegExp(`Club 1.*${removeCount}`) }),
      });
      const id = await option.getAttribute("data-repair-plan");
      await option.getByRole("button").click();
      const card = page.locator(`article[data-plan-id="${id}"]`);
      await expect(card).toBeVisible();
      const [, ids] = JSON.parse((await card.getAttribute("data-transfer-decision"))!) as [
        unknown,
        number[],
      ];
      expect(ids.filter((id) => players.get(id)?.team === "Club 1")).toHaveLength(
        removeCount === 2 ? 3 : 2,
      );
      expect(posts).toBe(0);
      await noOverflow(page);
    });
  }
}

for (const language of ["en", "tr"] as const) {
  for (const mode of [
    "replays the selected complete path",
    "reports exhausted capacity",
    "refuses search after rollback",
    "discards a candidate completed after rollback",
    "refuses selection after rollback",
    "discards a replay completed after rollback",
    "keeps the first witness when the second change exhausts capacity",
  ] as const) {
    test(`three-week repair ${mode} in ${language} on a phone`, async ({ page }) => {
      test.skip(!API, "API-origin build required");
      const { squad, release } = await installMember(page, language);
      const copy = LLMOPT_COPY[language];
      const twoCandidates =
        mode === "keeps the first witness when the second change exhausts capacity" ||
        mode === "discards a candidate completed after rollback";
      const firstRefused = mode === "reports exhausted capacity";
      const counts = [3, 2].map((count) => ({ kind: "club_count", club: "Club 1", count }));
      await routeChat(page, API, (route) =>
        answer(route, {
          status: "draft",
          draft: {
            window: 3,
            hard: twoCandidates ? counts : [{ kind: "hold_transfers" }],
            soft: [],
            ...(twoCandidates ? {} : { min_bank: { tenths: 30 } }),
          },
        }),
      );
      const submitted: {
        run: { run_id: string; stage: string };
        preferences: DecisionPreferences;
        model?: string;
      }[] = [];
      const captain = squad.starting_xi.find((p) => p.is_captain)!;
      const vice = squad.starting_xi.find((p) => p.is_vice_captain)!;
      const lineup = {
        starting_xi: squad.starting_xi,
        bench: squad.bench,
        captain,
        vice_captain: vice,
      };
      const score = [...squad.starting_xi, captain].reduce(
        (sum, p) => sum + (p.expected_points ?? 0),
        0,
      );
      await page.route(ADVICE, (route) => {
        const req = route.request();
        if (req.method() !== "POST") return answer(route, { error: { code: "NOT_COMPUTED" } }, 404);
        const body = req.postDataJSON() as (typeof submitted)[number];
        submitted.push(body);
        const rules = checkedPreferences(body.preferences);
        if (twoCandidates) {
          expect(rules.club_counts).toEqual([
            { club: "Club 1", count: submitted.length === 2 ? 3 : 2 },
          ]);
        } else {
          expect(rules.hold_transfers).toBe(true);
          expect(rules.min_bank?.tenths).toBe(squad.bank_tenths);
        }
        if (firstRefused || (twoCandidates && submitted.length === 2)) {
          expect(rules.frozen_weeks).toBeUndefined();
          return answer(route, { error: { code: "RUN_BUDGET_EXHAUSTED" } }, 409);
        }
        if (
          mode === "discards a candidate completed after rollback" ||
          (mode === "discards a replay completed after rollback" && submitted.length === 2)
        )
          release.master = false;
        const envelope = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3);
        const weeks = Array.from({ length: 3 }, (_, i) => ({
          gameweek: squad.gameweek + i,
          transfers_in: [],
          transfers_out: [],
          transfer_hit_points: 0,
          chip: null,
          bank_after_tenths: squad.bank_tenths!,
          free_transfers_before: i + 1,
          free_transfers_after: i + 2,
          expected_points: score,
          lineup,
        }));
        if (submitted.length === (twoCandidates ? 3 : 2)) {
          const expected = weeks.map((_, i) => ({
            week: i + 1,
            transfers_in: [],
            transfers_out: [],
            chip: null,
            starting_xi: squad.starting_xi.map((p) => p.player_id).sort((a, b) => a - b),
            captain: captain.player_id,
          }));
          expect(rules.frozen_weeks).toEqual(expected);
        } else expect(rules.frozen_weeks).toBeUndefined();
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
            transfer_hit_points: 0,
            free_transfers_after: 2,
            expected_own_points: score,
            plan_weeks: weeks,
            preferences: rules,
            preferences_scope: preferenceScope(rules),
          },
        });
      });
      await page.goto(PAGE);
      await holdModel(page);
      await instructions(
        page,
        language,
        twoCandidates ? "Require both club counts" : "Keep all transfers and raise the bank floor",
      );
      const region = page.locator("[data-rule-repairs]");
      await expect(region.getByRole("status")).toHaveText(
        twoCandidates ? /Club 1.*3.*(?:conflicts|uyuşmuyor)/ : /3\.0m.*bank|kasada 3,0m/,
      );
      if (mode === "refuses search after rollback") release.master = false;
      await checkButton(page, language).click();
      if (
        mode === "refuses search after rollback" ||
        mode === "discards a candidate completed after rollback"
      ) {
        await expect(region).toHaveCount(0);
        expect(submitted).toHaveLength(mode === "refuses search after rollback" ? 0 : 1);
        await expect(page.locator("article[data-plan-id]")).toHaveCount(0);
      } else if (firstRefused) {
        await expect(region.getByRole("status")).toHaveText(statusText[language].budget);
        await expect(region.locator("[data-repair-plan]")).toHaveCount(0);
        expect(submitted).toHaveLength(1);
      } else {
        const options = region.locator("[data-repair-plan]");
        if (twoCandidates) await expect.poll(() => submitted.length).toBe(2);
        await expect(options).toHaveCount(1);
        if (twoCandidates) await expect(options.getByRole("button")).toHaveText(/Club 1.*3/);
        await expect(options.getByRole("button")).toBeEnabled();
        const id = await options.getAttribute("data-repair-plan");
        expect(Number(await options.getAttribute("data-repair-net"))).toBeCloseTo(3 * score, 8);
        if (
          mode === "refuses selection after rollback" ||
          mode === "discards a replay completed after rollback"
        ) {
          if (mode === "refuses selection after rollback") release.repairs = false;
          await options.getByRole("button").click();
          await expect(region).toHaveCount(0);
          await expect(page.locator(`article[data-plan-id="${id}"]`)).toHaveCount(0);
          expect(submitted).toHaveLength(mode === "refuses selection after rollback" ? 1 : 2);
          await page.reload();
          await expect(page.locator("[data-saved-conflict]")).toHaveText(/3\.0m.*bank|kasada 3,0m/);
          await expect(region).toHaveCount(0);
          await expect(checkButton(page, language)).toHaveCount(0);
          expect(submitted).toHaveLength(mode === "refuses selection after rollback" ? 1 : 2);
          await noOverflow(page);
          return;
        }
        await options.getByRole("button").click();
        const selected = page.locator(`article[data-plan-id="${id}"]`);
        await expect(selected).toBeVisible();
        await expect(
          selected.getByText(copy.totalNet, { exact: true }).locator("xpath=../dd"),
        ).toHaveText(points(3 * score, 1, language === "tr" ? "tr-TR" : "en-GB"));
        expect(submitted.map((row) => row.run.stage)).toEqual(
          twoCandidates ? ["base", "repair", "repair"] : ["base", "repair"],
        );
        expect(new Set(submitted.map((row) => row.run.run_id)).size).toBe(1);
        await page.reload();
        await expect(selected).toBeVisible();
        expect(submitted).toHaveLength(twoCandidates ? 3 : 2);
      }
      await noOverflow(page);
    });
  }
}
