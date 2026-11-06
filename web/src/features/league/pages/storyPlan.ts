import type { AdviceChip, EntryAdvice } from "../types";

/**
 * The in-page targets of the week's decisions (#1134): the armband line for the captain, and
 * the chip choice the decision card's chip line opens into.
 */
export const STORY_ANCHORS = {
  captain: "hafta-kaptan",
  chip: "hafta-cip",
} as const;

/** Whether the document holds a solved plan: a proved or feasible eleven, bench and armband. */
export function hasPublishedPlan(view: EntryAdvice): boolean {
  return (
    (view.solver_status === "OPTIMAL" || view.solver_status === "FEASIBLE") &&
    view.starting_xi?.length === 11 &&
    view.bench?.length === 4 &&
    view.captain != null &&
    view.vice_captain != null
  );
}

/**
 * The chip the member chose for this week, as the document's chip choice names it, or null
 * without one. Only the member's own choice is told in the decision card: a chip the
 * producer's chip strategy names is left to the chip strategy below, because the page never
 * says on its own that this is the week to play a chip.
 */
export function chosenChip(view: EntryAdvice): AdviceChip | null {
  return view.chip_choice?.chip ?? null;
}
