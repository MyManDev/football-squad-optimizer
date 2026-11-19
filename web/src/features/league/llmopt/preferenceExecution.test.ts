import { describe, expect, it } from "vitest";
import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { preferencesKey } from "../advice/decisionPreferences";
import { bundleKey, expandSelection } from "../advice/preferenceBundle";
import { combinedCandidates, prepareCombined } from "./combinedPlan";
import { preparePlans, type PlanDraft } from "./intent";
import { baseDraft, prepareRun, requestFor, restoreRun } from "./planRun";
import type { PriceReview } from "./planResults";
import { preferenceExecution, selectionDifference } from "./preferenceExecution";

const squad = mockEntrySquadEnvelopes[35249001]!.payload;
const held = new Set([...squad.starting_xi, ...squad.bench].map(({ player_id }) => player_id));
const [first, second, third] = [...held] as [number, number, number];
function run(draft: PlanDraft, bundleMode = true) {
  const plans = preparePlans(baseDraft(draft), held);
  return prepareRun({
    draft,
    held,
    plans,
    bundleMode,
    wildcardNotHeld: false,
    request: {
      ...requestFor(squad, false, plans.window),
      run: {
        contract_version: "llmopt_run_v1",
        run_id: "a".repeat(32),
        stage: "base",
      },
    },
  });
}

describe("one preference execution", () => {
  it("packages two old prices and their combined choice without another request", () => {
    const prepared = run({
      hard: [],
      soft: [
        { kind: "keep_player", player_id: first },
        { kind: "avoid_player", player_id: second },
        { kind: "keep_player", player_id: third },
      ],
    });
    const request = preferenceExecution(prepared)!;
    expect(request.run?.stage).toBe("followup");
    expect(request.preferenceBundle?.slots).toHaveLength(2);
    const choice = request.preferenceBundle!.choices.find(({ accepted }) => accepted === 3)!;
    expect(choice.applied).toEqual([0, 1, 2]);
    const preferences = expandSelection(prepared.baseRequest!.preferences, choice.selection!);
    expect(preferences.keep_players).toEqual([first, third].sort((a, b) => a - b));
    expect(preferences.avoid_players).toEqual([second]);
  });

  it("preserves different ceilings for rules sharing the same computed price", () => {
    const prepared = run({
      hard: [],
      soft: [
        { kind: "keep_player", player_id: first, max_cost_tenths: 0 },
        { kind: "avoid_player", player_id: second, max_cost_tenths: 15 },
        { kind: "keep_player", player_id: third },
      ],
    });
    prepared.prices[1]!.outcome = 0;
    const bundle = preferenceExecution(prepared)!.preferenceBundle!;
    expect(bundle.choices.map(({ accepted }) => accepted)).toContain(2);
    for (const cost of [0, 0.001, 1.5, 1.500001, 8, null]) {
      const review = prepared.prices.map((target, index): PriceReview => ({
        outcome: target.outcome,
        price: {
          key: String(index),
          label: "",
          ceiling: target.rule.max_cost_tenths,
          status:
            target.outcome === "skipped" ? "skipped" : cost === null ? "unavailable" : "priced",
          cost: cost ?? 0,
          aboveCeiling:
            target.rule.max_cost_tenths !== undefined &&
            cost !== null &&
            cost - target.rule.max_cost_tenths / 10 > 1e-9,
        },
      }));
      const accepted = review.reduce(
        (mask, { price }, index) =>
          price.status === "priced" && !price.aboveCeiling ? mask | (1 << index) : mask,
        0,
      );
      const encoded = bundle.choices.find((choice) => choice.accepted === accepted)!;
      expect(encoded).toBeDefined();
      const candidates = combinedCandidates(prepared, review);
      const legacy = candidates
        ? prepareCombined(prepared, candidates)
        : { applied: [], request: null };
      expect(encoded.applied).toEqual(legacy.applied);
      expect(
        encoded.selection
          ? preferencesKey(expandSelection(prepared.baseRequest!.preferences, encoded.selection))
          : null,
      ).toBe(legacy.request ? preferencesKey(legacy.request.preferences) : null);
    }
  });

  it("a total allowance skips all individual prices and ignores individual ceilings", () => {
    const draft: PlanDraft = {
      hard: [],
      max_total_cost_tenths: 15,
      soft: [
        { kind: "keep_player", player_id: first, priority: 1, max_cost_tenths: 0 },
        { kind: "avoid_player", player_id: second, priority: 2, max_cost_tenths: 0 },
        { kind: "no_hits", priority: 3 },
      ],
    };
    const prepared = run(draft);
    expect(prepared.slots).toEqual([]);
    expect(prepared.prices).toEqual([]);
    const bundle = preferenceExecution(prepared)!.preferenceBundle!;
    expect(bundle.slots).toEqual([]);
    expect(bundle.prices).toEqual([]);
    expect(bundle.choices).toEqual([]);
    expect(bundle.program?.max_total_cost_tenths).toBe(15);
    expect(bundle.program?.preferences.map(({ priority }) => priority)).toEqual([1, 2, 3]);
    expect(JSON.stringify(bundle.program)).not.toContain("max_cost_tenths");
  });

  it("equal-priority writing order has the same execution identity", () => {
    const soft: PlanDraft["soft"] = [
      { kind: "keep_player", player_id: first },
      { kind: "avoid_player", player_id: second },
    ];
    const firstRequest = preferenceExecution(run({ hard: [], soft, max_total_cost_tenths: 0 }))!;
    const secondRequest = preferenceExecution(
      run({ hard: [], soft: [...soft].reverse(), max_total_cost_tenths: 0 }),
    )!;
    expect(bundleKey(firstRequest.preferenceBundle!)).toBe(
      bundleKey(secondRequest.preferenceBundle!),
    );
  });

  it("old confirmed sessions retain their original transport", () => {
    const draft: PlanDraft = { hard: [], soft: [{ kind: "keep_player", player_id: first }] };
    expect(preferenceExecution(run(draft, false))).toBeNull();
    const request = (window: 1 | 3 | 5) => requestFor(squad, false, window);
    const old = restoreRun(
      { draft, confirmation: { runId: "a".repeat(32), wildcardNotHeld: false } },
      held,
      request,
    );
    expect(preferenceExecution(old)).toBeNull();
    const current = restoreRun(
      { draft, confirmation: { runId: "a".repeat(32), wildcardNotHeld: false, bundleMode: true } },
      held,
      request,
    );
    expect(preferenceExecution(current)?.preferenceBundle).toBeDefined();
  });

  it("frozen decisions are inherited once rather than copied into every component", () => {
    const prepared = run({ hard: [], soft: [{ kind: "keep_player", player_id: first }] });
    const main = {
      ...prepared.baseRequest!,
      preferences: {
        ...prepared.baseRequest!.preferences!,
        frozen_weeks: [{ week: 1 as const, transfers_in: [], transfers_out: [], chip: null }],
      },
    };
    const selection = selectionDifference(main, {
      ...main,
      preferences: { ...main.preferences, keep_players: [first] },
    });
    expect(selection.preferences).not.toHaveProperty("frozen_weeks");
    expect(expandSelection(main.preferences, selection).frozen_weeks).toEqual(
      main.preferences.frozen_weeks,
    );
  });
});
