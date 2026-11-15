import { expect, it } from "vitest";

import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import { type PlanDraft } from "./intent";
import { referenceCaptains, summarizeRevision } from "./planRevision";
import { frozenForDraft, matchingScenarioReference, prepareOriginalScenario } from "./planScenario";

const ENTRY = 35249001;

function referencePlan() {
  const plan = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3).payload;
  const captain = plan.captain!;
  plan.plan_weeks = plan.plan_weeks!.map((week) => ({
    ...week,
    chip: null,
    lineup: {
      starting_xi: plan.starting_xi!,
      captain,
      vice_captain: plan.vice_captain!,
      bench: plan.bench!,
    },
  }));
  return { reference: summarizeRevision(plan)!, captain };
}

it("keeps the unaffected frozen lineup and exposes reference captains to chat", () => {
  const { reference, captain } = referencePlan();
  const draft: PlanDraft = {
    hard: [],
    soft: [],
    keep_weeks: [1, 2],
    scenario: { kind: "unavailable", player_id: captain.player_id, week: 2 },
  };
  expect(referenceCaptains(reference)).toEqual(
    [1, 2, 3].map((week) => ({ week, player_id: captain.player_id })),
  );
  const [first, second] = frozenForDraft(draft, reference);
  expect(first).toMatchObject({ week: 1, captain: captain.player_id });
  expect(second?.week).toBe(2);
  expect(second?.captain).toBeUndefined();
  expect(second?.starting_xi).toBeUndefined();
});

it("replays every selected week's original transfers with a matching shock and no fixed lineup", () => {
  const { reference, captain } = referencePlan();
  const scenario = { kind: "price_increase", player_id: captain.player_id, tenths: 1 } as const;
  const draft: PlanDraft = {
    hard: [{ kind: "no_hits" }],
    soft: [{ kind: "hold_transfers" }],
    scenario,
  };
  const replay = prepareOriginalScenario(draft, new Set(), 3, reference);
  expect(replay?.preferences).toMatchObject({ no_hits: true, scenario });
  expect(replay?.preferences.hold_transfers).toBeUndefined();
  expect(
    replay?.preferences.frozen_weeks?.map((week) => [week.week, week.captain, week.starting_xi]),
  ).toEqual([
    [1, undefined, undefined],
    [2, undefined, undefined],
    [3, undefined, undefined],
  ]);
  expect(matchingScenarioReference(reference, 1)).toBe(false);
  expect(prepareOriginalScenario(draft, new Set(), 1, reference)).toBeNull();
});
