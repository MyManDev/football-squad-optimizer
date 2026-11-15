import { money } from "../../../lib/format";
import type { FrozenPlanWeek, PlanScenario } from "../advice/decisionPreferences";
import type { LLMOptCopy } from "./copy";
import { preparePlans, type CatalogPlayer, type PlanDraft } from "./intent";
import { freezeReference, referenceWeeks, type PlanRevision } from "./planRevision";

export function scenarioLabel(
  scenario: PlanScenario,
  players: readonly CatalogPlayer[],
  gameweek: number,
  locale: string,
  copy: LLMOptCopy,
) {
  const player =
    players.find(({ id }) => id === scenario.player_id)?.name ?? String(scenario.player_id);
  const week = gameweek + (scenario.week ?? 1) - 1;
  return scenario.kind === "price_increase"
    ? copy.scenarioPrice(player, money(scenario.tenths, locale), week)
    : copy.scenarioUnavailable(player, week);
}

function transactions({ week, transfers_in, transfers_out, chip }: FrozenPlanWeek): FrozenPlanWeek {
  return { week, transfers_in, transfers_out, chip };
}

export function frozenForDraft(draft: PlanDraft, reference?: PlanRevision) {
  const frozen = freezeReference(reference, draft.keep_weeks);
  const scenario = draft.scenario;
  if (scenario?.kind !== "unavailable") return frozen;
  return frozen.map((row) => (row.week === (scenario.week ?? 1) ? transactions(row) : row));
}

export function matchingScenarioReference(reference: PlanRevision | undefined, window: 1 | 3) {
  return reference?.window === window && reference.weeks.length === window;
}

export function prepareOriginalScenario(
  draft: PlanDraft,
  held: ReadonlySet<number>,
  window: 1 | 3,
  reference?: PlanRevision,
) {
  const weeks = referenceWeeks(reference);
  if (!weeks || !matchingScenarioReference(reference, window)) return null;
  return preparePlans(
    { ...draft, window, keep_weeks: weeks, soft: [], comparison: undefined },
    held,
    freezeReference(reference, weeks).map(transactions),
  ).base;
}
