import { expect, it } from "vitest";

import type { AdviceRequest } from "../advice/adviceClient";
import type { PlanRepair } from "../advice/planInfeasibility";
import { preparePlans, type PlanDraft } from "./intent";
import { repairOptions } from "./planRepairs";

const players = [{ id: 7, name: "Target player", team: "Brighton" }];
const original: PlanDraft = {
  window: 3,
  hard: [{ kind: "no_hits" }, { kind: "buy_player", player_id: 7, week: 2 }],
  soft: [{ kind: "hold_transfers", week: 1, max_cost_tenths: 5 }],
  comparison: { kind: "include_player", player_id: 7, week: 3, both: true },
  keep_weeks: [1],
  min_bank: { tenths: 20, week: 2 },
};
const request: AdviceRequest = {
  strategy: "saf-puan",
  season: "2026-27",
  gameweek: 11,
  leagueId: 1,
  entryId: 11,
  window: 3,
  preferences: preparePlans({ ...original, comparison: undefined, soft: [] }, new Set(), [
    { week: 1, transfers_in: [], transfers_out: [], chip: null },
  ]).base!.preferences,
};

it("applies only the selected failed-request edit and preserves unrelated draft choices", () => {
  const alternatives: PlanRepair[] = [
    { kind: "lower_bank_floor", tenths: 15 },
    { kind: "defer_purchase", player_id: 7, from_week: 2, to_week: 3 },
    { kind: "release_purchase", player_id: 7, week: 2 },
  ];
  const before = structuredClone(original);
  const options = repairOptions(original, request, alternatives, players);
  expect(options.map(({ draft }) => draft)).toEqual([
    { ...original, min_bank: { tenths: 15, week: 2 } },
    { ...original, hard: [original.hard[0], { kind: "buy_player", player_id: 7, week: 3 }] },
    { ...original, hard: [original.hard[0]] },
  ]);
  expect(original).toEqual(before);
});

it("ignores a repair when the current draft or failed request names a different rule", () => {
  expect(
    repairOptions(
      { ...original, min_bank: { tenths: 20, week: 3 } },
      request,
      [
        { kind: "lower_bank_floor", tenths: 15 },
        { kind: "release_purchase", player_id: 7, week: 1 },
      ],
      players,
    ),
  ).toEqual([]);
});
