/** Compile the existing price decisions into one server preference job. */
import { checkedPreferences } from "../advice/decisionPreferences";
import type { ComputePhase } from "../advice/useAdviceJob";
import {
  PREFERENCE_BUNDLE_VERSION,
  type PreferenceBundle,
  type PreferenceSelection,
  type PreferenceComponent,
  expandSelection,
} from "../advice/preferenceBundle";
import { combinedCandidates, prepareCombined } from "./combinedPlan";
import { constraintKey, preparePlans } from "./intent";
import type { PriceReview } from "./planResults";
import type { PlanRequest, PlanRun } from "./planRun";
import type { SlotName } from "./planSlots";

export function selectionDifference(main: PlanRequest, next: PlanRequest): PreferenceSelection {
  const base: Record<string, unknown> = { ...checkedPreferences(main.preferences) };
  const chosen: Record<string, unknown> = { ...checkedPreferences(next.preferences) };
  const preferences = Object.fromEntries(
    [...new Set([...Object.keys(base), ...Object.keys(chosen)])]
      .sort()
      .flatMap((key) =>
        JSON.stringify(base[key]) === JSON.stringify(chosen[key])
          ? []
          : [[key, chosen[key] ?? null]],
      ),
  );
  return { preferences, chip: next.chip === "wildcard" ? "wildcard" : null };
}

/** All acceptance patterns reachable from the two computed prices, including failed slots. */
function pricePatterns(run: PlanRun): number[] {
  const same = run.prices.reduce(
    (mask, target, index) => (target.outcome === "same" ? mask | (1 << index) : mask),
    0,
  );
  let masks = [same];
  run.slots.forEach((_slot, slot) => {
    const thresholds = run.prices.flatMap((target) =>
      target.outcome === slot && target.rule.max_cost_tenths !== undefined
        ? [target.rule.max_cost_tenths / 10]
        : [],
    );
    const costs = [0, ...thresholds.map((value) => value + 1e-6), Infinity];
    const patterns = new Set([0]);
    for (const cost of costs) {
      patterns.add(
        run.prices.reduce(
          (mask, target, index) =>
            target.outcome === slot &&
            (target.rule.max_cost_tenths === undefined ||
              cost - target.rule.max_cost_tenths / 10 <= 1e-9)
              ? mask | (1 << index)
              : mask,
          0,
        ),
      );
    }
    masks = [...new Set(masks.flatMap((mask) => [...patterns].map((pattern) => mask | pattern)))];
  });
  return masks.sort((left, right) => left - right);
}

export function preferenceExecution(run: PlanRun | null): PlanRequest | null {
  if (!run?.inputs.bundleMode || !run.baseRequest || !run.inputs.draft.soft.length || run.scenario)
    return null;
  const main = run.baseRequest;
  const { draft, held, plans } = run.inputs;
  const slots = run.slots.map((slot) =>
    slot.request ? selectionDifference(main, slot.request) : null,
  );
  let program: PreferenceBundle["program"] = null;
  if (draft.max_total_cost_tenths !== undefined) {
    if (draft.soft.some(({ kind }) => kind === "wildcard"))
      throw new Error("Total allowance does not support optional Wildcard");
    program = {
      max_total_cost_tenths: draft.max_total_cost_tenths,
      preferences: draft.soft.map((rule) => {
        const branch = preparePlans({ hard: [], soft: [rule], window: plans.window }, held);
        const selected = branch.alternative ?? branch.base;
        if (!selected || branch.alternativeConflict) throw new Error("Invalid priority rule");
        return {
          priority: rule.priority ?? 2,
          rules: checkedPreferences({
            ...selected.preferences,
            save_chips: rule.kind === "save_chips",
            net_points_priority: false,
          }),
        };
      }),
    };
  }
  const choices: PreferenceBundle["choices"] = program
    ? []
    : pricePatterns(run).map((accepted) => {
        const review = run.prices.map((target, index): PriceReview => ({
          outcome: target.outcome,
          price: {
            key: constraintKey(target.rule),
            label: "",
            ceiling: target.rule.max_cost_tenths,
            status:
              typeof target.outcome === "number" || target.outcome === "same"
                ? "priced"
                : target.outcome,
            cost: 0,
            aboveCeiling: (accepted & (1 << index)) === 0,
          },
        }));
        const candidates = combinedCandidates(run, review);
        const choice = candidates
          ? prepareCombined(run, candidates)
          : { applied: [], request: null };
        return {
          accepted,
          applied: choice.applied,
          selection: choice.request ? selectionDifference(main, choice.request) : null,
        };
      });
  return {
    ...main,
    ...(main.run ? { run: { ...main.run, stage: "followup" } } : {}),
    preferenceBundle: {
      contract_version: PREFERENCE_BUNDLE_VERSION,
      slots,
      prices: program
        ? []
        : run.prices.map((target) => ({
            outcome: target.outcome,
            ceiling: target.rule.max_cost_tenths ?? null,
          })),
      choices,
      program,
    },
  };
}

export function preferenceStates(
  states: Record<SlotName, ComputePhase>,
  run: PlanRun | null,
  execution: PlanRequest | null,
): Record<SlotName, ComputePhase> {
  const parent = states.first;
  if (!run || !execution?.preferenceBundle || parent.phase !== "done") return states;
  const result = parent.envelope.payload.preference_bundle_result;
  if (!result) return states;
  const { envelope, source } = parent;
  function state(
    component: PreferenceComponent | null,
    selection: PreferenceSelection | null,
    request: PlanRequest | null,
  ): ComputePhase {
    if (!component || !selection || !request) return { phase: "idle" };
    const selected = {
      ...request,
      preferences: expandSelection(run!.baseRequest!.preferences, selection),
      chip: selection.chip,
    };
    if (component.status === "done" && component.payload)
      return {
        phase: "done",
        request: selected,
        envelope: { ...envelope, payload: component.payload },
        source,
      };
    return {
      phase: "failed",
      request: selected,
      reason: component.error_code,
      ...(component.infeasibility ? { infeasibility: component.infeasibility } : {}),
    };
  }
  const bundle = execution.preferenceBundle;
  const choice = bundle.choices.find(({ accepted }) => accepted === result.accepted);
  const selection = bundle.program
    ? { preferences: {}, chip: run.baseRequest!.chip === "wildcard" ? ("wildcard" as const) : null }
    : (choice?.selection ?? null);
  const childRequest = { ...execution };
  delete childRequest.preferenceBundle;
  return {
    ...states,
    first: state(
      result.components[0] ?? null,
      bundle.slots[0] ?? null,
      run.slots[0]?.request ?? null,
    ),
    second: state(
      result.components[1] ?? null,
      bundle.slots[1] ?? null,
      run.slots[1]?.request ?? null,
    ),
    combined: state(result.selected, selection, childRequest),
  };
}

/** The outcome of the preference plan after the bundle itself reaches a terminal state. */
export function preferencePlanProblem(state: ComputePhase) {
  if (state.phase === "failed" || state.phase === "unavailable")
    return state.reason === "RUN_BUDGET_EXHAUSTED" ? "combinedExhausted" : "combinedFailed";
  if (state.phase !== "done") return undefined;
  const result = state.envelope.payload.preference_bundle_result;
  if (!result?.selected) return result?.budget_exhausted ? "combinedExhausted" : "combinedMissing";
  switch (result.selected.status) {
    case "done":
      return undefined;
    case "failed":
      return "combinedFailed";
    case "unavailable":
      return "combinedMissing";
    case "exhausted":
      return "combinedExhausted";
  }
}
