import type { ComputePhase } from "../advice/useAdviceJob";
import type { EntryAdvice } from "../types";
import type { LLMOptCopy } from "./copy";
import { constraintKey } from "./intent";
import type { PreferencePrice } from "./PlanResult";
import {
  expectedNet,
  meaningfulOpeningAlternative,
  sameOpeningDecision,
  samePlan,
} from "./planComparison";
import type { ExplicitTitle, PlanRun, PriceTarget } from "./planRun";
import { isWorking } from "./planSlots";

/** The cost of one preferred rule against the reference plan, as far as the jobs have answered. */
export function preferencePrice(
  target: PriceTarget,
  label: string,
  reference: ComputePhase,
  alternatives: readonly ComputePhase[],
  canStart: boolean,
): PreferencePrice {
  const review = { key: constraintKey(target.rule), label, ceiling: target.rule.max_cost_tenths };
  const { outcome } = target;
  if (outcome === "conflict" || outcome === "unavailable" || outcome === "skipped")
    return { ...review, status: outcome };
  if (reference.phase !== "done")
    return {
      ...review,
      status: isWorking(reference.phase) ? "pending" : "unavailable",
    };
  const referencePlan = reference.envelope.payload;
  if (outcome === "same")
    return {
      ...review,
      status: "priced",
      cost: 0,
      aboveCeiling: false,
    };
  const candidate = alternatives[outcome];
  if (candidate?.phase !== "done")
    return {
      ...review,
      status:
        candidate && (isWorking(candidate.phase) || (candidate.phase === "idle" && canStart))
          ? "pending"
          : "unavailable",
    };

  const candidatePlan = candidate.envelope.payload;
  const referenceNet = expectedNet(referencePlan);
  const candidateNet = expectedNet(candidatePlan);
  if (referenceNet === null || candidateNet === null) return { ...review, status: "unavailable" };
  const cost = samePlan(reference, candidate) ? 0 : Math.max(0, referenceNet - candidateNet);
  return {
    ...review,
    status: "priced",
    cost,
    aboveCeiling: review.ceiling !== undefined && cost - review.ceiling / 10 > 1e-9,
  };
}

/** An automatic roll or bank alternative worth showing beside the reference plan, or null. */
export function visibleAutomatic(
  state: ComputePhase,
  reference?: EntryAdvice,
  previous: readonly EntryAdvice[] = [],
) {
  if (state.phase !== "done" || !reference) return null;
  const plan = state.envelope.payload;
  const preferences = state.request.preferences;
  const kind =
    preferences?.min_opening_bank_tenths !== undefined
      ? "bank"
      : preferences?.hold_opening_transfers
        ? "roll"
        : null;
  return kind &&
    meaningfulOpeningAlternative(reference, plan, kind) &&
    !previous.some((shown) => sameOpeningDecision(shown, plan))
    ? { kind, state, plan }
    : null;
}

export interface PriceReview {
  outcome: PriceTarget["outcome"];
  price: PreferencePrice;
}

export interface ShownResult {
  title: string;
  state: ComputePhase;
  conflict?: boolean;
  conflictMessage?: string;
}

/**
 * The alternative cards a run shows beside its base plan, in slot order.
 *
 * A priced plan is shown only once its rule is priced within its limit, or when it is
 * infeasible. A plan that repeats the base or an earlier card is not shown again; `same` says
 * that a requested branch matched the base.
 */
export function planResults({
  run,
  base,
  alternatives,
  priceReview,
  copy,
  explain,
}: {
  run: PlanRun;
  base: ComputePhase;
  alternatives: readonly ComputePhase[];
  priceReview: readonly PriceReview[];
  copy: LLMOptCopy;
  explain: (title: ExplicitTitle) => string | undefined;
}): { results: ShownResult[]; same: boolean } {
  const results: ShownResult[] = [];
  let same = false;
  if (run.scenario) return { results, same };
  const baseAnswer = base.phase === "done" ? base.envelope.payload : undefined;
  alternatives.forEach((state, index) => {
    const slot = run.slots[index];
    if (slot?.kind === "explicit") {
      // A requested with/without pair remains visible alongside an independent pricing reference.
      if (
        !slot.conflict &&
        slot.title !== "without" &&
        (run.baseTitle === "without" || slot.title === "alternative") &&
        samePlan(base, state)
      ) {
        same = true;
      } else {
        results.push({
          title: copy[slot.title],
          state,
          conflict: slot.conflict,
          conflictMessage: slot.conflict ? explain(slot.title) : undefined,
        });
      }
    } else if (slot?.kind === "priced") {
      if (state.phase === "failed" && state.infeasibility) {
        const reason = priceReview.find(({ outcome }) => outcome === index);
        if (reason) results.push({ title: copy.pricedPlan(reason.price.label), state });
        return;
      }
      if (
        state.phase !== "done" ||
        samePlan(base, state) ||
        results.some((shown) => samePlan(shown.state, state))
      )
        return;
      const approved = priceReview.find(
        ({ outcome, price }) =>
          outcome === index && price.status === "priced" && !price.aboveCeiling,
      );
      if (approved) results.push({ title: copy.pricedPlan(approved.price.label), state });
    } else if (!alternatives.slice(0, index).some(({ phase }) => isWorking(phase))) {
      const previous = results.flatMap(({ state }) =>
        state.phase === "done" ? [state.envelope.payload] : [],
      );
      const automatic = visibleAutomatic(state, baseAnswer, previous);
      if (automatic)
        results.push({ title: automatic.kind === "roll" ? copy.rollPlan : copy.bankPlan, state });
    }
  });
  return { results, same };
}
