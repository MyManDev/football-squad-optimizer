import { describe, expect, it } from "vitest";

import type { PlanDraft } from "./intent";
import { BANK_FLOOR, KEEP_WEEK, SCENARIO, draftChanges, ruleIdentity } from "./planChanges";

const before: PlanDraft = {
  hard: [
    { kind: "hold_transfers" },
    { kind: "club_count", club: "Arsenal", count: 2 },
    { kind: "keep_player", player_id: 7, week: 1 },
  ],
  soft: [{ kind: "no_hits", max_cost_tenths: 10 }],
  keep_weeks: [1],
  min_bank: { tenths: 5 },
};

describe("draftChanges", () => {
  it("is null when the model answer leaves the rules as they were", () => {
    const reordered: PlanDraft = {
      ...before,
      hard: [...before.hard].reverse(),
      soft: [{ max_cost_tenths: 10, kind: "no_hits" }],
    };
    expect(draftChanges(before, reordered)).toBeNull();
  });

  it("marks added and changed rules and lists the removed ones where they were", () => {
    const after: PlanDraft = {
      hard: [
        { kind: "club_count", club: "Arsenal", count: 3 },
        { kind: "keep_player", player_id: 7, week: 1 },
        { kind: "no_hits" },
      ],
      soft: [],
      comparison: { kind: "include_player", player_id: 9, both: true },
      keep_weeks: [1, 2],
      min_bank: { tenths: 8 },
      scenario: { kind: "unavailable", player_id: 7, week: 2 },
    };
    const changes = draftChanges(before, after)!;

    expect(Object.fromEntries(changes.marks)).toEqual({
      [ruleIdentity("hard", { kind: "club_count", club: "Arsenal", count: 3 })]: "changed",
      [ruleIdentity("hard", { kind: "no_hits" })]: "added",
      [ruleIdentity("comparison", { kind: "include_player", player_id: 9 })]: "added",
      [KEEP_WEEK(2)]: "added",
      [BANK_FLOOR]: "changed",
      [SCENARIO]: "added",
    });
    expect(changes.removed).toEqual([
      { group: "hard", rule: { kind: "hold_transfers" } },
      { group: "soft", rule: { kind: "no_hits", max_cost_tenths: 10 } },
    ]);
  });

  it("lists a dropped revision rule and scenario as removed", () => {
    const scenario = { kind: "price_increase", player_id: 7, tenths: 3 } as const;
    const changes = draftChanges(
      { ...before, scenario },
      { hard: before.hard, soft: before.soft },
    )!;
    expect(changes.marks.size).toBe(0);
    expect(changes.removed).toEqual([
      { group: "revision", keepWeek: 1 },
      { group: "revision", bank: { tenths: 5 } },
      { group: "scenario", scenario },
    ]);
  });
});
