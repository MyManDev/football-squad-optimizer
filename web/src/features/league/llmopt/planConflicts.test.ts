import { expect, it } from "vitest";

import { LLMOPT_COPY } from "./copy";
import type { PlanDraft } from "./intent";
import { explainDraftConflict } from "./planConflicts";

const context = {
  gameweek: 11,
  window: 3 as const,
  held: new Set([1]),
  frozen: [],
  players: [
    { id: 1, name: "Held player", team: "Arsenal" },
    { id: 2, name: "Target player", team: "Brighton" },
  ],
  copy: LLMOPT_COPY.en,
};

it("names a previously frozen transfer conflict and keeps both draft rules available to edit", () => {
  const draft: PlanDraft = {
    hard: [{ kind: "buy_player", player_id: 2, week: 2 }],
    soft: [{ kind: "keep_player", player_id: 1 }],
    keep_weeks: [2],
  };
  const before = structuredClone(draft);
  expect(
    explainDraftConflict(draft, {
      ...context,
      frozen: [{ week: 2, chip: null, transfers_in: [], transfers_out: [] }],
    }),
  ).toMatch(/GW 12 is locked.*Target player.*unlock the week/);
  expect(draft).toEqual(before);
});

it("explains holds and opposite player rules only for overlapping weeks", () => {
  const draft: PlanDraft = {
    hard: [
      { kind: "hold_transfers", week: 1 },
      { kind: "buy_player", player_id: 2, week: 2 },
      { kind: "avoid_player", player_id: 2, week: 3 },
    ],
    soft: [],
  };
  expect(explainDraftConflict(draft, context)).toBeUndefined();
  draft.hard[2] = { kind: "avoid_player", player_id: 2, week: 2 };
  expect(explainDraftConflict(draft, context)).toMatch(/GW 12.*Target player.*Exclude player/);

  draft.hard[0] = { kind: "hold_transfers", week: 2 };
  expect(explainDraftConflict(draft, context)).toMatch(/GW 12.*Target player.*Roll the transfer/);
});
