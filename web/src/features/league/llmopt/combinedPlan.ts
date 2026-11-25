import { preparePlans } from "./intent";
import type { PriceReview } from "./planResults";
import { pricedRequest, type PlanRequest, type PlanRun } from "./planRun";

/** The plan that applies every accepted preferred rule at once, and the rules it applies. */
export interface CombinedPlan {
  /** Indexes into the draft's preferred rules, in draft order. */
  applied: number[];
  /** Null when no rule fits; otherwise the request of the plan with all of them. */
  request: PlanRequest | null;
}

/**
 * The preferred rules the plan with all preferences tries to apply, or null when no such plan
 * is due.
 *
 * It is due once at least two accepted rules each priced a plan of their own, or when a rule
 * had no slot of its own and has no point-loss limit. It tries every accepted rule (priced
 * within its limit) and every unbounded rule that had no slot. A bounded rule needs its own
 * verified price. The single prices must be in: a review still pending gives null.
 */
export function combinedCandidates(run: PlanRun, review: readonly PriceReview[]): number[] | null {
  if (run.scenario || !run.prices.length || review.length !== run.prices.length) return null;
  const outcomes = run.prices.map(({ outcome }) => outcome);
  if (review.some(({ outcome, price }) => outcome !== "skipped" && price.status === "pending"))
    return null;
  const accepted = review.flatMap(({ price }, index) =>
    price.status === "priced" && !price.aboveCeiling ? [index] : [],
  );
  const unslotted = outcomes.flatMap((outcome, index) =>
    outcome === "skipped" && run.prices[index]?.rule.max_cost_tenths === undefined ? [index] : [],
  );
  const ownPlans = new Set(
    accepted.flatMap((index) => {
      const outcome = outcomes[index];
      return typeof outcome === "number" ? [outcome] : [];
    }),
  );
  if (ownPlans.size < 2 && !unslotted.length) return null;
  return [...accepted, ...unslotted].sort((left, right) => left - right);
}

/**
 * Applies the candidates one at a time, in draft order, beside the required rules. A rule that
 * cannot be added to those already applied, or that needs a Wildcard the team does not hold,
 * is left out and the rest are still applied.
 */
export function prepareCombined(run: PlanRun, candidates: readonly number[]): CombinedPlan {
  const { draft, held, request, plans, wildcardNotHeld, frozenWeeks } = run.inputs;
  const hardDraft = {
    window: plans.window,
    hard: draft.hard,
    keep_weeks: draft.keep_weeks,
    min_bank: draft.min_bank,
  };
  const fit = (indexes: readonly number[]) => {
    const rules = indexes.flatMap((index) => {
      const rule = draft.soft[index];
      return rule ? [rule] : [];
    });
    if (rules.length !== indexes.length) return null;
    const branch = preparePlans({ ...hardDraft, soft: rules }, held, frozenWeeks);
    if (branch.alternativeConflict) return null;
    const plan = branch.alternative ?? branch.base;
    if (!plan || (wildcardNotHeld && plan.chip === "wildcard")) return null;
    try {
      return pricedRequest(
        request.run ? { ...request, run: { ...request.run, stage: "followup" } } : request,
        plan,
      );
    } catch {
      return null;
    }
  };
  let applied: number[] = [];
  let combined: PlanRequest | null = null;
  for (const index of candidates) {
    if (applied.includes(index)) continue;
    const target = run.prices[index];
    if (target?.outcome === "skipped" && target.rule.max_cost_tenths !== undefined) continue;
    const next = fit([...applied, index]);
    if (!next) continue;
    applied = [...applied, index];
    combined = next;
  }
  return { applied, request: combined };
}
