import type { AdviceChip, EntryAdvice } from "../types";

/**
 * The in-page targets the week's story cards (#1134) open into: the decision for the
 * transfers, the armband line for the captain, the chip choice for the chip.
 */
export const STORY_ANCHORS = {
  transfers: "entry-advice-title",
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

/** The chip the advice document names for this week, or null where it names none. */
export function namedChip(view: EntryAdvice): AdviceChip | null {
  return view.chip ?? view.chip_choice?.chip ?? view.chip_strategy?.selected_chip ?? null;
}
