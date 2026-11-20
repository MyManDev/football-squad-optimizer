/** The service's single preference execution, over proved device answers. */
import {
  checkedPreferences,
  preferencesKey,
  type DecisionPreferences,
} from "../advice/decisionPreferences";
import {
  checkedPreferenceBundle,
  expandSelection,
  type PreferenceBundle,
  type PreferenceSelection,
} from "../advice/preferenceBundle";
import { oneWeekPreferences } from "./preferences";
import { solvePriorityPreferences } from "./priority";
import { DevicePlanRefused, DeviceWeekInfeasible } from "./solve/week";
import type { LpSolver } from "./lp/problem";
import type {
  DeviceChip,
  DevicePlanAnswer,
  DevicePlanDocument,
  DevicePlanEntry,
  DevicePreferenceComponent,
} from "./types";

export function oneWeekBundle(value: unknown, hard?: DecisionPreferences): PreferenceBundle {
  const bundle = checkedPreferenceBundle(value);
  oneWeekPreferences(hard);
  for (const selection of [...bundle.slots, ...bundle.choices.map((choice) => choice.selection)])
    if (selection) oneWeekPreferences(expandSelection(hard, selection));
  if (bundle.program) {
    if (!hard?.net_points_priority)
      throw new Error("A total allowance requires the net-points objective.");
    for (const preference of bundle.program.preferences) {
      const rules = oneWeekPreferences(preference.rules)!;
      if (rules.net_points_priority || rules.frozen_weeks?.length)
        throw new Error("Unsupported priority rule.");
    }
  }
  return bundle;
}

export function solvePreferenceBundle(
  solver: LpSolver,
  input: {
    document: DevicePlanDocument;
    entry: DevicePlanEntry;
    preferences?: DecisionPreferences;
    chip: DeviceChip | null;
    bundle: PreferenceBundle;
  },
  plain: (preferences: DecisionPreferences, chip: DeviceChip | null) => DevicePlanAnswer,
  now: () => number,
): DevicePlanAnswer {
  const started = now();
  const hard = checkedPreferences(input.preferences);
  const bundle = oneWeekBundle(input.bundle, hard);
  const baseline = plain(hard, input.chip);
  const net = (answer: DevicePlanAnswer) => answer.expected_own_points - answer.transfer_hit_points;
  const reference = net(baseline);
  const cache = new Map<string, DevicePlanAnswer>([
    [JSON.stringify([preferencesKey(hard), input.chip]), baseline],
  ]);
  let exhausted = false;
  const component = (selection: PreferenceSelection): DevicePreferenceComponent => {
    const preferences = expandSelection(hard, selection);
    const address = JSON.stringify([preferencesKey(preferences), selection.chip]);
    const cached = cache.get(address);
    if (cached)
      return {
        status: "done",
        answer: { ...cached, expected_points_cost: Math.max(0, reference - net(cached)) },
        error_code: null,
      };
    if ((solver.remainingSeconds?.() ?? Infinity) <= 0) {
      exhausted = true;
      return { status: "exhausted", answer: null, error_code: "RUN_BUDGET_EXHAUSTED" };
    }
    try {
      const answer = plain(preferences, selection.chip);
      cache.set(address, answer);
      return {
        status: "done",
        answer: { ...answer, expected_points_cost: Math.max(0, reference - net(answer)) },
        error_code: null,
      };
    } catch (error) {
      if (!(error instanceof DevicePlanRefused)) throw error;
      if (error instanceof DeviceWeekInfeasible)
        return { status: "failed", answer: null, error_code: "PLAN_NOT_FOUND" };
      if (error.status !== "Time limit reached") throw error;
      exhausted = true;
      return { status: "exhausted", answer: null, error_code: "RUN_BUDGET_EXHAUSTED" };
    }
  };
  const components = bundle.slots.map((selection): DevicePreferenceComponent =>
    selection
      ? component(selection)
      : { status: "unavailable", answer: null, error_code: "PLAN_NOT_FOUND" },
  );
  let selected: DevicePreferenceComponent | null = null;
  let accepted = 0;
  let applied: number[] = [];
  if (bundle.program) {
    const answer = solvePriorityPreferences(
      solver,
      input.document,
      input.entry,
      baseline,
      bundle.program,
      now,
    );
    selected = { status: "done", answer, error_code: null };
    exhausted ||= answer.priority_preferences?.budget_exhausted === true;
  } else {
    bundle.prices.forEach((price, index) => {
      if (price.outcome === "same") accepted |= 1 << index;
      else if (typeof price.outcome === "number") {
        const result = components[price.outcome];
        if (result?.status === "done" && result.answer) {
          const cost = Math.max(0, reference - net(result.answer));
          if (price.ceiling === null || cost - price.ceiling / 10 <= 1e-9) accepted |= 1 << index;
        }
      }
    });
    const choice = bundle.choices.find((row) => row.accepted === accepted);
    if (bundle.choices.length && !choice) throw new Error("Missing device preference combination.");
    if (choice?.selection) {
      selected = component(choice.selection);
      if (selected.status === "done") applied = choice.applied;
    }
  }
  return {
    ...baseline,
    seconds: (now() - started) / 1000,
    preference_bundle: {
      contract_version: "llmopt_device_preference_v1",
      request: bundle,
      components,
      selected,
      accepted,
      applied,
      budget_exhausted: exhausted,
    },
  };
}
