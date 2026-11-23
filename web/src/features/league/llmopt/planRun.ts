import type { AdviceRequest } from "../advice/adviceClient";
import { checkedPreferences, type FrozenPlanWeek } from "../advice/decisionPreferences";
import { sameAdviceRequest } from "../advice/useAdviceJob";
import type { EntrySquad } from "../types";
import { isDevicePlanEntry } from "../device/types";
import { needsThreeWeeks, preparePlans, type Constraint, type PlanDraft } from "./intent";
import type { PlanRevision } from "./planRevision";
import { frozenForDraft, matchingScenarioReference, prepareOriginalScenario } from "./planScenario";
import { ALTERNATIVE_COUNT, type PlanSession } from "./planSession";

export type PreparedPlans = ReturnType<typeof preparePlans>;
export type PreparedPlan = NonNullable<PreparedPlans["base"]>;
export type PlanRequest = AdviceRequest & Pick<PreparedPlan, "preferences">;
export type ExplicitTitle = "with" | "without" | "alternative" | "scenarioOriginal";
export type BaseTitle = "base" | "without" | "scenarioOptimized";

/** A result slot the run reserved before any answer: a requested branch or one priced rule. */
export type ReservedAlternative =
  | { kind: "explicit"; title: ExplicitTitle; request: PlanRequest | null; conflict: boolean }
  | { kind: "priced"; request: PlanRequest };

/** Where a preferred rule is priced: in a reserved slot, or why it has no plan of its own. */
export interface PriceTarget {
  rule: Constraint;
  outcome: number | "same" | "conflict" | "unavailable" | "skipped";
}

export interface PlanRun {
  /** What the run was prepared from, so a later plan of the same run is built the same way. */
  inputs: RunInputs;
  baseRequest: PlanRequest | null;
  baseTitle: BaseTitle;
  baseConflict: boolean;
  automaticBasis: PlanRequest | null;
  slots: ReservedAlternative[];
  prices: PriceTarget[];
  wildcardUnavailable: boolean;
  scenario?: true;
}

export interface RunInputs {
  paths3w?: true;
  compareOnly?: boolean;
  draft: PlanDraft;
  held: ReadonlySet<number>;
  request: AdviceRequest;
  plans: PreparedPlans;
  wildcardNotHeld: boolean;
  frozenWeeks?: readonly FrozenPlanWeek[];
  reference?: PlanRevision;
  bundleMode?: boolean;
}

/** The advice request for this member and window, before any rule is applied. */
export function requestFor(
  squad: EntrySquad,
  forwarded: boolean | undefined,
  window: AdviceRequest["window"],
  allowDevice = false,
): AdviceRequest {
  const device = allowDevice && window === 1 && isDevicePlanEntry(squad.device_plan);
  return {
    deviceRun: device,
    deviceAlternatives: device,
    publicEntry: forwarded,
    leagueId: squad.league_id,
    entryId: squad.entry.entry_id,
    strategy: "saf-puan",
    window,
    season: squad.season,
    gameweek: squad.gameweek,
  };
}

/** A plan's request in a priced run, where the solver maximises expected net points. */
export function pricedRequest(request: AdviceRequest, plan: PreparedPlan): PlanRequest {
  return {
    ...request,
    ...plan,
    preferences: checkedPreferences({ ...plan.preferences, net_points_priority: true }),
  };
}

/** The draft the base plan is prepared from: required rules only, in a settled window. */
export function baseDraft(draft: PlanDraft): PlanDraft {
  return {
    ...draft,
    window: draft.window ?? (needsThreeWeeks(draft) ? 3 : 1),
    soft: [],
    comparison: draft.scenario ? undefined : draft.comparison,
  };
}

/**
 * Every request one Compute press makes, before any of them is sent.
 *
 * The base request is the required-rule plan. Each preferred rule is priced on its own in one of
 * the reserved slots; a rule whose plan matches a slot already reserved shares that slot.
 */
export function prepareRun(inputs: RunInputs): PlanRun {
  const {
    draft,
    held,
    compareOnly = false,
    request: originalRequest,
    plans,
    wildcardNotHeld,
    frozenWeeks,
    reference,
  } = inputs;
  const request = { ...originalRequest };
  if (
    draft.scenario ||
    [...draft.hard, ...draft.soft, ...(draft.comparison ? [draft.comparison] : [])].some(
      (rule) => rule.kind === "wildcard",
    )
  )
    request.deviceRun = false;
  if (draft.soft.length || draft.scenario || draft.comparison || compareOnly)
    delete request.deviceAlternatives;
  const preparedInputs =
    originalRequest.deviceAlternatives !== request.deviceAlternatives ||
    originalRequest.deviceRun !== request.deviceRun
      ? { ...inputs, request }
      : inputs;
  const pricing = !draft.scenario && draft.soft.length > 0;
  const compareBoth = !draft.scenario && draft.comparison?.both === true;
  const hardDraft = {
    window: plans.window,
    hard: draft.hard,
    soft: [],
    keep_weeks: draft.keep_weeks,
    min_bank: draft.min_bank,
  };
  const hard = compareBoth ? preparePlans(hardDraft, held, frozenWeeks).base : plans.base;
  const baseline = pricing ? hard : plans.base;
  let wildcardUnavailable = false;
  const submit = (plan: PreparedPlan | null) => {
    if (!plan) return null;
    if (wildcardNotHeld && plan.chip === "wildcard") {
      wildcardUnavailable = true;
      return null;
    }
    const addressed = request.run
      ? { ...request, run: { ...request.run, stage: "followup" as const } }
      : request;
    return pricing ||
      draft.scenario ||
      compareOnly ||
      (request.deviceAlternatives && !draft.comparison)
      ? pricedRequest(addressed, plan)
      : { ...addressed, ...plan, preferences: plan.preferences };
  };
  const base = submit(baseline);
  const baseRequest = base?.run ? { ...base, run: { ...base.run, stage: "base" as const } } : base;
  if (baseRequest?.deviceRun && inputs.bundleMode && draft.max_total_cost_tenths !== undefined)
    baseRequest.priorityMain = true;
  if (draft.scenario) {
    const previous = prepareOriginalScenario(draft, held, plans.window, reference);
    const replay = submit(previous);
    return {
      inputs: preparedInputs,
      scenario: true,
      baseTitle: "scenarioOptimized",
      baseRequest,
      baseConflict: plans.baseConflict,
      automaticBasis: null,
      slots: [
        { kind: "explicit", title: "scenarioOriginal", request: replay, conflict: !previous },
      ],
      prices: [],
      wildcardUnavailable,
    };
  }
  const automaticBasis = compareOnly ? null : pricing || !compareBoth ? base : submit(hard);
  const slots: ReservedAlternative[] = [];
  function addExplicit(plan: PreparedPlan | null, conflict: boolean, title: ExplicitTitle) {
    const request = submit(plan);
    if (request || conflict) slots.push({ kind: "explicit", title, request, conflict });
  }
  if (pricing && compareBoth) addExplicit(plans.base, plans.baseConflict, "without");
  if (draft.comparison)
    addExplicit(plans.alternative, plans.alternativeConflict, compareBoth ? "with" : "alternative");
  const prices =
    draft.max_total_cost_tenths !== undefined
      ? []
      : draft.soft.map((rule): PriceTarget => {
          if (compareBoth) return { rule, outcome: "skipped" };
          const branch = preparePlans({ ...hardDraft, soft: [rule] }, held, frozenWeeks);
          if (branch.alternativeConflict) return { rule, outcome: "conflict" };
          if (!branch.alternative) return { rule, outcome: "same" };
          const request = submit(branch.alternative);
          if (!request) return { rule, outcome: "unavailable" };
          const existing = slots.findIndex(
            (slot) => slot.request && sameAdviceRequest(slot.request, request),
          );
          if (existing >= 0) return { rule, outcome: existing };
          if (slots.length === ALTERNATIVE_COUNT) return { rule, outcome: "skipped" };
          const outcome = slots.length;
          slots.push({ kind: "priced", request });
          return { rule, outcome };
        });
  return {
    inputs: preparedInputs,
    baseTitle: !pricing && compareBoth ? "without" : "base",
    baseConflict: pricing ? plans.hardConflict : plans.baseConflict,
    baseRequest,
    automaticBasis,
    slots,
    prices,
    wildcardUnavailable,
  };
}

/**
 * The run a saved confirmation stands for, rebuilt from its draft, or null when the saved draft
 * can no longer be calculated as it was.
 */
export function restoreRun(
  restored: PlanSession | null,
  held: ReadonlySet<number>,
  requestForWindow: (window: AdviceRequest["window"]) => AdviceRequest,
): PlanRun | null {
  if (!restored?.confirmation || restored.confirmation.repairSearch) return null;
  const { draft, confirmation, reference } = restored;
  const frozenWeeks = frozenForDraft(draft, reference);
  const plans = preparePlans(baseDraft(draft), held, frozenWeeks);
  if (plans.hardConflict || (draft.scenario && !matchingScenarioReference(reference, plans.window)))
    return null;
  return prepareRun({
    draft,
    held,
    request: {
      ...requestForWindow(plans.window),
      deviceRun: !!confirmation.runId && confirmation.deviceRun === true,
      deviceAlternatives:
        !!confirmation.runId &&
        confirmation.deviceRun === true &&
        confirmation.deviceAlternatives === true,
      ...(confirmation.runId
        ? {
            run: {
              contract_version: "llmopt_run_v1" as const,
              run_id: confirmation.runId,
              stage: "base" as const,
            },
          }
        : {}),
    },
    plans,
    wildcardNotHeld: confirmation.wildcardNotHeld,
    compareOnly: confirmation.compareOnly === true,
    ...(confirmation.runId && plans.window === 3 && confirmation.paths3w === true
      ? { paths3w: true as const }
      : {}),
    frozenWeeks,
    reference,
    bundleMode: confirmation.bundleMode === true,
  });
}
